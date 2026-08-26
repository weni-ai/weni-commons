"""
Shared traversal of Django's URL resolver for @api_gateway_expose views.

Two consumers need the same answers to "which patterns are exposed?" and
"what is the upstream Django path for this pattern?":

    - ``kong.sync.discover_routes`` turns each record into a Kong route.
    - ``openapi.inventory.build_inventory`` turns each record into an entry of
      the OpenAPI generation inventory.

They must never disagree, otherwise the gateway would serve routes the
documentation does not describe (or vice versa), so the walk lives here.
"""
import logging
from typing import Any, Dict, Iterator, List, Optional, Tuple

from weni_commons.kong.paths import (
    has_path_params,
    normalize_path,
    path_template_from_regex,
    path_template_from_route,
)

logger = logging.getLogger(__name__)


def resolve_view_target(callback: Any) -> Optional[Any]:
    """Return APIView.view_class or ViewSet.cls from a URL callback."""
    return getattr(callback, "view_class", None) or getattr(callback, "cls", None)


def exposure_for_pattern(callback: Any, view_class: Any) -> Optional[Dict[str, Any]]:
    """
    Decide if this URL pattern is exposed and which decorator attrs apply.

    Method-level @api_gateway_expose on an action wins over class-level for
    alias / service; HTTP methods come from callback.actions when present.
    """
    actions = getattr(callback, "actions", None)

    if actions:
        marked: List[Tuple[str, Any]] = []
        for http_method, action_name in actions.items():
            action_fn = getattr(view_class, action_name, None)
            if action_fn is not None and getattr(action_fn, "_kong_expose", False):
                marked.append((http_method.upper(), action_fn))

        if marked:
            # First marked action supplies alias/service (method wins).
            _, first_fn = marked[0]
            return {
                "methods": [m for m, _ in marked],
                "service": first_fn._kong_service,
                "alias": first_fn._kong_alias,
            }

        if getattr(view_class, "_kong_expose", False):
            return {
                "methods": [m.upper() for m in actions.keys()],
                "service": view_class._kong_service,
                "alias": view_class._kong_alias,
            }
        return None

    if getattr(view_class, "_kong_expose", False):
        return {
            "methods": list(view_class._kong_methods),
            "service": view_class._kong_service,
            "alias": view_class._kong_alias,
        }
    return None


def _sample_converter_value(converter: Any, name: str) -> str:
    """Return a reverse()-valid sample value for a Django path converter."""
    cls_name = type(converter).__name__.lower()
    if "uuid" in cls_name:
        return "00000000-0000-4000-8000-000000000001"
    if "int" in cls_name:
        return "999999001"
    if "slug" in cls_name:
        return f"kong-{name}-placeholder"
    return f"kong-{name}-placeholder"


def _placeholder_kwargs(pattern: Any) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Build reverse() kwargs and a map of sample value → param name for
    rewriting the reversed URL into a ``{name}`` template.
    """
    kwargs: Dict[str, str] = {}
    samples: Dict[str, str] = {}
    converters = getattr(pattern.pattern, "converters", None) or {}
    for name, converter in converters.items():
        sample = _sample_converter_value(converter, name)
        kwargs[name] = sample
        samples[sample] = name
    if kwargs:
        return kwargs, samples
    regex = getattr(pattern.pattern, "regex", None)
    if regex is not None:
        for gname in getattr(regex, "groupindex", {}) or {}:
            if gname != "format":
                sample = f"kong-{gname}-placeholder"
                kwargs[gname] = sample
                samples[sample] = gname
    return kwargs, samples


def converter_types(pattern: Any) -> Dict[str, str]:
    """
    Map path param name → Django converter class name for a leaf pattern.

    Only the leaf pattern is inspected, so params contributed by parent
    includes are absent — callers must treat a missing name as unknown.
    """
    converters = getattr(pattern.pattern, "converters", None) or {}
    return {name: type(converter).__name__ for name, converter in converters.items()}


def django_path_template(
    pattern: Any,
    name: Optional[str],
    suffix: str,
    parent_prefix: str = "",
) -> Optional[str]:
    """
    Build a Django upstream path template for a URLPattern.

    Prefers ``reverse()`` (with placeholder kwargs for path converters) so
    nested includes resolve to the full path. Falls back to joining the
    walked parent prefix with the leaf route/regex template.
    """
    from django.urls import NoReverseMatch, reverse

    fmt = suffix.lstrip(".")
    placeholders, samples = _placeholder_kwargs(pattern)

    if name:
        path: Optional[str] = None
        try:
            kwargs = dict(placeholders)
            kwargs["format"] = fmt
            path = reverse(name, kwargs=kwargs)
        except NoReverseMatch:
            try:
                if placeholders:
                    # ViewSet detail / converter routes — never invent a .json suffix.
                    path = reverse(name, kwargs=placeholders)
                else:
                    path = reverse(name)
                    # APIView + format_suffix_patterns: bare reverse omits .json.
                    if not path.endswith(suffix) and "." not in path.rsplit("/", 1)[-1]:
                        path = path.rstrip("/") + suffix
            except NoReverseMatch:
                path = None

        if path is not None:
            for sample, key in samples.items():
                path = path.replace(str(sample), f"{{{key}}}")
            return normalize_path(path)

    # Fallback: parent include prefix + leaf pattern (full reverse unavailable).
    route_pattern = pattern.pattern
    route = getattr(route_pattern, "_route", None)
    if route is not None:
        leaf = path_template_from_route(route)
    else:
        leaf = path_template_from_regex(str(route_pattern))

    if parent_prefix:
        template = normalize_path(parent_prefix.rstrip("/") + leaf)
    else:
        template = leaf

    if suffix and not has_path_params(template) and not template.endswith(suffix):
        last = template.rsplit("/", 1)[-1]
        if "." not in last:
            template = template.rstrip("/") + suffix

    return normalize_path(template)


def kong_route_name(upstream_template: str, alias: Optional[str]) -> str:
    """
    Build the Kong route name that identifies this route.

    Shared so the OpenAPI inventory can be cross-referenced with the routes
    kong_sync creates (and prunes) by name.
    """
    if alias:
        return "allow-" + alias.strip("/").replace("/", "-").replace("{", "").replace("}", "")
    slug = (
        upstream_template.strip("/")
        .replace("/", "-")
        .replace(".", "-")
        .replace("{", "")
        .replace("}", "")
    )
    return "allow-" + slug


def iter_exposed_views(suffix: str = ".json") -> Iterator[Dict[str, Any]]:
    """
    Yield one record per URL pattern whose view is marked @api_gateway_expose.

    Each record carries the decorator intent plus the resolved upstream path:

        view_class     — the APIView / ViewSet class
        callback       — the URL callback (has ``actions`` for ViewSets)
        pattern        — the Django URLPattern
        methods        — HTTP methods the decorator allows through the gateway
        service        — Kong service name from the decorator
        alias          — short public path from the decorator, or None
        upstream_path  — Django path template, e.g. ``/api/v2/contacts.json``

    Patterns whose path cannot be resolved are logged and skipped. Records are
    yielded in resolver order, so duplicate aliases arrive in registration
    order and the caller decides how to break the tie.
    """
    from django.urls import URLPattern, URLResolver, get_resolver

    def walk(resolver: Any, parent_prefix: str = "") -> Iterator[Dict[str, Any]]:
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                route = getattr(pattern.pattern, "_route", None)
                if route is not None:
                    child_prefix = parent_prefix.rstrip("/") + "/" + str(route).strip("/")
                else:
                    child_prefix = parent_prefix
                for record in walk(pattern, child_prefix):
                    yield record
            elif isinstance(pattern, URLPattern):
                callback = pattern.callback
                view_class = resolve_view_target(callback)
                if not view_class:
                    continue

                exposure = exposure_for_pattern(callback, view_class)
                if not exposure:
                    continue

                upstream_path = django_path_template(
                    pattern, pattern.name, suffix, parent_prefix
                )
                if not upstream_path:
                    logger.warning(
                        "iter_exposed_views: could not resolve path for %s — skipping",
                        pattern.name or view_class,
                    )
                    continue

                yield {
                    "pattern": pattern,
                    "callback": callback,
                    "view_class": view_class,
                    "methods": exposure["methods"],
                    "service": exposure["service"],
                    "alias": exposure["alias"],
                    "upstream_path": upstream_path,
                }

    for record in walk(get_resolver()):
        yield record
