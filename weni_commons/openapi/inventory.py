"""
Inventory of the endpoints this service exposes through the API Gateway.

This is the deterministic half of OpenAPI generation. It answers, from code
alone, the questions a documentation generator must not get wrong:

    - which endpoints are public (the @api_gateway_expose decorator)
    - what URL a customer calls (the alias, or the prefixed Django path)
    - which HTTP methods the gateway lets through
    - what the request and response payloads look like (DRF serializers)

Everything left over — summaries, descriptions, realistic examples — is prose,
and is written on top of this inventory rather than guessed alongside it.

The inventory also reports what it could *not* settle, in ``warnings``, so the
gaps are visible instead of silently filled in. Two are worth calling out:

    missing_alias    the route is only reachable under the service prefix, so
                     it is not a customer-facing URL yet
    method_mismatch  the view implements methods the gateway blocks, which
                     would be a 405 if documented
"""
import logging
from typing import Any, Dict, List, Optional

from weni_commons.kong.discovery import (
    converter_types,
    iter_exposed_views,
    kong_route_name,
)
from weni_commons.kong.paths import (
    has_path_params,
    join_prefix,
    normalize_path,
    path_param_names,
    rewrite_mode_for,
)
from weni_commons.openapi.serializers import (
    describe_serializer,
    dotted_path,
    jsonable,
    unresolved_field_names,
)

logger = logging.getLogger(__name__)

INVENTORY_VERSION = 1

# Django path converter class name → (OpenAPI type, OpenAPI format).
_CONVERTER_TYPES = {
    "UUIDConverter": ("string", "uuid"),
    "IntConverter": ("integer", None),
    "SlugConverter": ("string", None),
    "StringConverter": ("string", None),
    "PathConverter": ("string", None),
}

# Ordered probes: the first attribute that holds a serializer wins for the role.
_SERIALIZER_ATTRS = (
    ("read", ("serializer_class", "read_serializer_class")),
    ("write", ("write_serializer_class",)),
)

_PAGINATION_QUERY_ATTRS = (
    "page_query_param",
    "page_size_query_param",
    "cursor_query_param",
    "limit_query_param",
    "offset_query_param",
)


def _package_version() -> Optional[str]:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - Python < 3.8
        return None
    try:
        return version("weni-commons")
    except PackageNotFoundError:  # pragma: no cover - running from a source tree
        return None


def _describe_view(view_class: Any) -> Dict[str, Any]:
    import inspect

    described: Dict[str, Any] = {
        "class": dotted_path(view_class),
        "module": getattr(view_class, "__module__", None),
    }
    try:
        described["file"] = inspect.getsourcefile(view_class)
        described["line"] = inspect.getsourcelines(view_class)[1]
    except (TypeError, OSError):  # pragma: no cover - dynamically built views
        pass
    return described


def _view_http_methods(view_class: Any, callback: Any) -> List[str]:
    """
    HTTP methods the view actually implements.

    Compared against the methods the decorator allows so a gateway that would
    reject an implemented method is reported instead of documented.
    """
    actions = getattr(callback, "actions", None)
    if actions:
        return sorted(method.upper() for method in actions)

    names = getattr(view_class, "http_method_names", None) or []
    return sorted(
        name.upper()
        for name in names
        if name not in {"options", "trace", "head"} and hasattr(view_class, name)
    )


def _describe_serializers(view_class: Any) -> Dict[str, Any]:
    described: Dict[str, Any] = {}
    for role, attrs in _SERIALIZER_ATTRS:
        for attr in attrs:
            serializer = describe_serializer(getattr(view_class, attr, None))
            if serializer:
                serializer["attribute"] = attr
                described[role] = serializer
                break
    return described


def _describe_pagination(view_class: Any) -> Optional[Dict[str, Any]]:
    pagination_class = getattr(view_class, "pagination_class", None)
    if pagination_class is None:
        return None

    described: Dict[str, Any] = {"class": dotted_path(pagination_class)}
    page_size = getattr(pagination_class, "page_size", None)
    if page_size is not None:
        described["page_size"] = jsonable(page_size)

    query_params = []
    for attr in _PAGINATION_QUERY_ATTRS:
        value = getattr(pagination_class, attr, None)
        if value:
            query_params.append(str(value))
    if query_params:
        described["query_params"] = query_params
    return described


def _describe_filters(view_class: Any) -> Optional[Dict[str, Any]]:
    described: Dict[str, Any] = {}

    backends = getattr(view_class, "filter_backends", None) or []
    dotted_backends = [dotted_path(backend) for backend in backends]
    dotted_backends = [name for name in dotted_backends if name]
    if dotted_backends:
        described["backends"] = dotted_backends

    for attr in ("filterset_class", "filter_class"):
        value = getattr(view_class, attr, None)
        if value is not None:
            described["filterset_class"] = dotted_path(value)
            break

    for attr in ("filterset_fields", "filter_fields"):
        value = getattr(view_class, attr, None)
        if value:
            described["filterset_fields"] = jsonable(value)
            break

    return described or None


def _describe_throttle(view_class: Any) -> Optional[Dict[str, Any]]:
    described: Dict[str, Any] = {}
    scope = getattr(view_class, "throttle_scope", None)
    if scope:
        described["scope"] = str(scope)
    classes = getattr(view_class, "throttle_classes", None) or []
    dotted_classes = [name for name in (dotted_path(item) for item in classes) if name]
    if dotted_classes:
        described["classes"] = dotted_classes
    return described or None


def _describe_model(view_class: Any) -> Optional[str]:
    model = getattr(view_class, "model", None)
    if model is None:
        queryset = getattr(view_class, "queryset", None)
        model = getattr(queryset, "model", None)
    return dotted_path(model)


def _describe_path_params(
    public_path: str, pattern: Any, upstream_path: str
) -> List[Dict[str, Any]]:
    converters = converter_types(pattern)
    params = []
    for name in path_param_names(public_path) or path_param_names(upstream_path):
        converter = converters.get(name)
        openapi_type, openapi_format = _CONVERTER_TYPES.get(
            converter or "", ("string", None)
        )
        param: Dict[str, Any] = {"name": name, "type": openapi_type}
        if openapi_format:
            param["format"] = openapi_format
        if converter:
            param["converter"] = converter
        params.append(param)
    return params


def _public_paths(url_prefix: str, upstream_path: str, alias: Optional[str]):
    """
    Return (public_path, compat_paths, rewrite_mode, alias_for_paths).

    The public path is the flat alias when the decorator sets one, because that
    is the URL customers call. Without an alias the only reachable URL keeps the
    service prefix, which is a gateway detail rather than a public contract.

    ``alias_for_paths`` is passed straight to kong_route_name so the inventory
    and kong_sync always agree on the route identity.
    """
    rewrite_mode, alias_for_paths = rewrite_mode_for(upstream_path, alias)

    if alias_for_paths:
        alias_path = normalize_path(alias_for_paths)
        return (
            alias_path,
            [join_prefix(url_prefix, alias_path), join_prefix(url_prefix, upstream_path)],
            rewrite_mode,
            alias_for_paths,
        )

    return join_prefix(url_prefix, upstream_path), [], rewrite_mode, None


def _is_same_endpoint(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
    """Two records describing the same view reached through equivalent patterns."""
    return (
        first["upstream_path"] == second["upstream_path"]
        and first["view"].get("class") == second["view"].get("class")
    )


def build_inventory(
    url_prefix: str,
    suffix: str = ".json",
    service: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the OpenAPI generation inventory for this project's exposed views.

    Args:
        url_prefix: gateway prefix for this service, e.g. ``/flows``.
        suffix: URL suffix used during discovery (matches kong_sync).
        service: when set, only routes exposed to this Kong service.

    Duplicate route names follow the same last-writer-wins rule as kong_sync,
    so the inventory always describes the routes Kong will end up with.
    """
    prefix = url_prefix.rstrip("/")
    routes: Dict[str, Dict[str, Any]] = {}
    conflicts: List[Dict[str, Any]] = []

    for record in iter_exposed_views(suffix):
        if service and record["service"] != service:
            continue

        upstream_path = record["upstream_path"]
        alias = record["alias"]
        view_class = record["view_class"]

        public_path, compat_paths, rewrite_mode, alias_for_paths = _public_paths(
            prefix, upstream_path, alias
        )
        route_name = kong_route_name(upstream_path, alias_for_paths)
        needs_alias = alias_for_paths is None

        gateway_methods = sorted(record["methods"])
        view_methods = _view_http_methods(view_class, record["callback"])
        serializers = _describe_serializers(view_class)

        entry: Dict[str, Any] = {
            "route_name": route_name,
            "public_path": public_path,
            "gateway_methods": gateway_methods,
            "view_methods": view_methods,
            "service": record["service"],
            "alias": alias,
            "upstream_path": upstream_path,
            "compat_paths": compat_paths,
            "rewrite_mode": rewrite_mode,
            "path_params": _describe_path_params(
                public_path, record["pattern"], upstream_path
            ),
            "view": _describe_view(view_class),
            "serializers": serializers,
            "permission_classes": [
                name
                for name in (
                    dotted_path(item)
                    for item in (getattr(view_class, "permission_classes", None) or [])
                )
                if name
            ],
            "authentication_classes": [
                name
                for name in (
                    dotted_path(item)
                    for item in (
                        getattr(view_class, "authentication_classes", None) or []
                    )
                )
                if name
            ],
        }

        for key, value in (
            ("pagination", _describe_pagination(view_class)),
            ("filters", _describe_filters(view_class)),
            ("throttle", _describe_throttle(view_class)),
            ("model", _describe_model(view_class)),
        ):
            if value:
                entry[key] = value

        existing = routes.get(route_name)
        if existing is not None:
            # format_suffix_patterns registers each view twice (with and without
            # the .json suffix), and both resolve to the same upstream. That is
            # not a conflict, so it must not be reported as one.
            if _is_same_endpoint(existing, entry):
                continue
            conflicts.append(
                {
                    "code": "duplicate_route_name",
                    "route": route_name,
                    "message": (
                        f"{route_name} was already registered by "
                        f"{existing['view'].get('class')} at {existing['upstream_path']}; "
                        f"{entry['view'].get('class')} at {upstream_path} overwrites it "
                        "(last-writer-wins, same as kong_sync)"
                    ),
                }
            )

        entry["warnings"] = _route_warnings(entry, needs_alias)
        routes[route_name] = entry

    # Built from the surviving routes so an overwritten entry takes its own
    # warnings with it.
    warnings = list(conflicts)
    for route in routes.values():
        warnings.extend(route["warnings"])

    inventory = {
        "inventory_version": INVENTORY_VERSION,
        "weni_commons_version": _package_version(),
        "url_prefix": prefix,
        "suffix": suffix,
        "service_filter": service,
        "route_count": len(routes),
        "routes": list(routes.values()),
        "warnings": warnings,
    }
    logger.info("build_inventory: %d route(s), %d warning(s)", len(routes), len(warnings))
    return inventory


def _route_warnings(entry: Dict[str, Any], needs_alias: bool) -> List[Dict[str, Any]]:
    route_name = entry["route_name"]
    found: List[Dict[str, Any]] = []

    if needs_alias:
        reason = (
            "the alias has no path params but the upstream requires them"
            if entry["alias"] and has_path_params(entry["upstream_path"])
            else "no alias on @api_gateway_expose"
        )
        found.append(
            {
                "code": "missing_alias",
                "route": route_name,
                "message": (
                    f"{route_name} is only reachable at {entry['public_path']} "
                    f"({reason}), so it has no customer-facing URL yet"
                ),
            }
        )

    blocked = sorted(set(entry["view_methods"]) - set(entry["gateway_methods"]))
    if blocked:
        found.append(
            {
                "code": "method_mismatch",
                "route": route_name,
                "message": (
                    f"{route_name} implements {', '.join(blocked)} but the gateway "
                    f"allows only {', '.join(entry['gateway_methods'])} — document "
                    "the allowed methods and widen the decorator if the rest "
                    "should be public"
                ),
            }
        )

    if not entry["serializers"]:
        found.append(
            {
                "code": "no_serializer",
                "route": route_name,
                "message": (
                    f"{route_name} exposes no serializer_class — payload shapes must "
                    f"be read from {entry['view'].get('class')}"
                ),
            }
        )

    for role, described in entry["serializers"].items():
        if described.get("introspection") == "declared":
            found.append(
                {
                    "code": "serializer_declared_only",
                    "route": route_name,
                    "message": (
                        f"{described['class']} ({role}) could not be instantiated "
                        f"({described.get('introspection_error')}); only declared "
                        "fields are listed, model fields are missing"
                    ),
                }
            )
        unresolved = unresolved_field_names(described)
        if unresolved:
            found.append(
                {
                    "code": "unresolved_fields",
                    "route": route_name,
                    "message": (
                        f"{described['class']} ({role}) has fields whose shape needs "
                        f"a human or a read of the code: {', '.join(unresolved)}"
                    ),
                }
            )

    return found
