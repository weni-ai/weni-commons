"""
Route discovery and Kong Admin API sync.

discover_routes() walks Django's URL resolver to find all views marked with
@api_gateway_expose (APIView classes, ViewSets via callback.cls, and @action
methods), resolving each URL pattern to gateway path(s).

sync_to_kong() applies the discovered routes to Kong via the Admin API.
Both functions require Kong running in DB mode (with PostgreSQL). DB-less
mode does not support route creation via the Admin API.

Required environment variable:
    KONG_URL_PREFIX  — gateway path prefix for this service, e.g. /flows

Without alias, the public path keeps the service prefix:
    {KONG_URL_PREFIX}{django_path}   e.g. /flows/api/v2/contacts.json

With alias on @api_gateway_expose, three public paths are registered:
    /{alias}                         e.g. /events          (flat, public)
    {KONG_URL_PREFIX}/{alias}        e.g. /flows/events    (compat)
    {KONG_URL_PREFIX}{django_path}   e.g. /flows/api/v2/events.json (compat)

Parameterized routes (ViewSet detail / ``{pk}``) use Kong regex paths and
``pre-function`` rewrite instead of a static ``replace.uri``.

Upstream URIs for static routes use request-transformer:
    {django_path}                    e.g. /api/v2/contacts.json

Alias routes use a stable Kong name ``allow-{alias}``. Re-syncing the same
alias from another service overwrites service + upstream (last-writer-wins).

``strip_path`` must stay false on allow-routes: with the full gateway path in
``paths``, ``strip_path=true`` would strip the entire match and forward ``/``.
"""
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests as http

from weni_commons.kong.paths import (
    has_path_params,
    join_prefix,
    kong_regex_path,
    normalize_path,
    path_template_from_regex,
    path_template_from_route,
    rewrite_mode_for,
)

logger = logging.getLogger(__name__)

REQUEST_TRANSFORMER_PLUGIN = "request-transformer"
PRE_FUNCTION_PLUGIN = "pre-function"


def _resolve_view_target(callback: Any) -> Optional[Any]:
    """Return APIView.view_class or ViewSet.cls from a URL callback."""
    return getattr(callback, "view_class", None) or getattr(callback, "cls", None)


def _exposure_for_pattern(callback: Any, view_class: Any) -> Optional[Dict[str, Any]]:
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


def _django_path_template(
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


def _gateway_paths(
    url_prefix: str,
    upstream_template: str,
    alias: Optional[str],
    rewrite_mode: str,
) -> List[str]:
    """Build Kong ``paths`` list (regex-prefixed when parameterized)."""
    if has_path_params(upstream_template):
        django_kong = kong_regex_path(upstream_template)
    else:
        django_kong = normalize_path(upstream_template)

    full_gateway = join_prefix(url_prefix, django_kong)

    if rewrite_mode == "alias_captures" and alias:
        alias_template = normalize_path(alias)
        alias_kong = (
            kong_regex_path(alias_template)
            if has_path_params(alias_template)
            else alias_template
        )
        return [
            alias_kong if alias_kong.startswith("~") else normalize_path(alias_kong),
            join_prefix(url_prefix, alias_kong),
            full_gateway,
        ]

    if rewrite_mode == "static_uri" and alias:
        return [
            normalize_path(alias),
            f"{url_prefix.rstrip('/')}/{alias.strip('/')}",
            full_gateway,
        ]

    return [full_gateway]


def _route_name(upstream_template: str, alias: Optional[str]) -> str:
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


def discover_routes(suffix: str = ".json") -> List[Dict]:
    """
    Walks Django's URL resolver and returns all views decorated with
    @api_gateway_expose, resolving each URL pattern to gateway path(s).

    Supports:
        - APIView (``callback.view_class``)
        - ViewSet / @action (``callback.cls`` + ``callback.actions``)
        - Class-level or method-level decorator (method wins for alias/service)
        - Path params as Kong regex ``(?<pk>[^/]+)`` with rewrite_mode

    Raises:
        KeyError: if KONG_URL_PREFIX is not set in the environment.
    """
    url_prefix = os.environ["KONG_URL_PREFIX"].rstrip("/")

    from django.urls import URLPattern, URLResolver, get_resolver

    # Keyed by Kong route name so duplicate aliases overwrite (last-writer-wins).
    routes_by_name: Dict[str, Dict] = {}

    def walk(resolver: "URLResolver", parent_prefix: str = "") -> None:
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                route = getattr(pattern.pattern, "_route", None)
                if route is not None:
                    child_prefix = parent_prefix.rstrip("/") + "/" + str(route).strip("/")
                else:
                    child_prefix = parent_prefix
                walk(pattern, child_prefix)
            elif isinstance(pattern, URLPattern):
                callback = pattern.callback
                view_class = _resolve_view_target(callback)
                if not view_class:
                    continue

                exposure = _exposure_for_pattern(callback, view_class)
                if not exposure:
                    continue

                upstream_template = _django_path_template(
                    pattern, pattern.name, suffix, parent_prefix
                )
                if not upstream_template:
                    logger.warning(
                        "discover_routes: could not resolve path for %s — skipping",
                        pattern.name or view_class,
                    )
                    continue

                rewrite_mode, alias_for_paths = rewrite_mode_for(
                    upstream_template,
                    exposure.get("alias"),
                )
                if exposure.get("alias") and alias_for_paths is None and has_path_params(upstream_template):
                    logger.warning(
                        "discover_routes: alias %r has no path params but upstream "
                        "%s requires them — registering prefix path only",
                        exposure["alias"],
                        upstream_template,
                    )

                paths = _gateway_paths(
                    url_prefix,
                    upstream_template,
                    alias_for_paths,
                    rewrite_mode,
                )
                route_name = _route_name(upstream_template, alias_for_paths)

                if route_name in routes_by_name:
                    previous = routes_by_name[route_name]
                    logger.warning(
                        "discover_routes: duplicate route name %r — "
                        "overwriting previous registration (was upstream %s)",
                        route_name,
                        previous.get("upstream_uri"),
                    )

                routes_by_name[route_name] = {
                    "name": route_name,
                    "paths": paths,
                    "methods": exposure["methods"],
                    "service": exposure["service"],
                    "strip_path": False,
                    "upstream_uri": upstream_template,
                    "rewrite_mode": rewrite_mode,
                }
                logger.debug(
                    "discover_routes: found %s -> %s (upstream %s, mode %s, service %s)",
                    route_name,
                    paths,
                    upstream_template,
                    rewrite_mode,
                    exposure["service"],
                )

    walk(get_resolver())

    routes = list(routes_by_name.values())
    logger.info("discover_routes: %d route(s) discovered", len(routes))
    return routes


def _list_route_plugins(admin_url: str, route_name: str) -> List[dict]:
    listed = http.get(f"{admin_url}/routes/{route_name}/plugins", timeout=10)
    listed.raise_for_status()
    return listed.json().get("data", [])


def _delete_plugins_named(admin_url: str, plugins: List[dict], names: set) -> None:
    for plugin in plugins:
        if plugin.get("name") in names:
            http.delete(f"{admin_url}/plugins/{plugin['id']}", timeout=10).raise_for_status()
            logger.info(
                "sync_to_kong: removed plugin %s from route",
                plugin.get("name"),
            )


def _ensure_uri_rewrite_plugin(admin_url: str, route_name: str, upstream_uri: str) -> None:
    """
    Ensure the route has a request-transformer that rewrites the URI to the
    upstream Django path (service prefix removed).
    """
    plugins = _list_route_plugins(admin_url, route_name)
    _delete_plugins_named(admin_url, plugins, {PRE_FUNCTION_PLUGIN})
    plugins = _list_route_plugins(admin_url, route_name)

    plugin_payload = {
        "name": REQUEST_TRANSFORMER_PLUGIN,
        "config": {
            "replace": {
                "uri": upstream_uri,
            }
        },
    }

    existing = next((p for p in plugins if p.get("name") == REQUEST_TRANSFORMER_PLUGIN), None)
    if existing:
        current_uri = (existing.get("config") or {}).get("replace", {}).get("uri")
        if current_uri == upstream_uri:
            logger.debug(
                "sync_to_kong: route %s already has uri rewrite to %s",
                route_name,
                upstream_uri,
            )
            return
        http.patch(
            f"{admin_url}/plugins/{existing['id']}",
            json=plugin_payload,
            timeout=10,
        ).raise_for_status()
        logger.info(
            "sync_to_kong: updated uri rewrite on %s -> %s",
            route_name,
            upstream_uri,
        )
        return

    http.post(
        f"{admin_url}/routes/{route_name}/plugins",
        json=plugin_payload,
        timeout=10,
    ).raise_for_status()
    logger.info(
        "sync_to_kong: created uri rewrite on %s -> %s",
        route_name,
        upstream_uri,
    )


def _pre_function_payload(lua_source: str) -> dict:
    return {
        "name": PRE_FUNCTION_PLUGIN,
        "config": {
            "access": [lua_source],
        },
    }


def _ensure_pre_function_plugin(admin_url: str, route_name: str, lua_source: str) -> None:
    """Ensure route has pre-function with the given access Lua; drop request-transformer."""
    plugins = _list_route_plugins(admin_url, route_name)
    _delete_plugins_named(admin_url, plugins, {REQUEST_TRANSFORMER_PLUGIN})
    plugins = _list_route_plugins(admin_url, route_name)

    plugin_payload = _pre_function_payload(lua_source)
    existing = next((p for p in plugins if p.get("name") == PRE_FUNCTION_PLUGIN), None)
    if existing:
        current = (existing.get("config") or {}).get("access") or []
        if current == [lua_source]:
            logger.debug("sync_to_kong: route %s already has matching pre-function", route_name)
            return
        http.patch(
            f"{admin_url}/plugins/{existing['id']}",
            json=plugin_payload,
            timeout=10,
        ).raise_for_status()
        logger.info("sync_to_kong: updated pre-function on %s", route_name)
        return

    http.post(
        f"{admin_url}/routes/{route_name}/plugins",
        json=plugin_payload,
        timeout=10,
    ).raise_for_status()
    logger.info("sync_to_kong: created pre-function on %s", route_name)


def _ensure_prefix_strip_plugin(admin_url: str, route_name: str, url_prefix: str) -> None:
    """Strip KONG_URL_PREFIX from the request path, preserving the rest (incl. pk)."""
    prefix = url_prefix.rstrip("/")
    # Escape for Lua string literal.
    prefix_lua = prefix.replace("\\", "\\\\").replace('"', '\\"')
    lua = (
        f'local prefix = "{prefix_lua}"\n'
        "local path = kong.request.get_path()\n"
        "if path:sub(1, #prefix) == prefix then\n"
        "  local new_path = path:sub(#prefix + 1)\n"
        '  if new_path == "" then new_path = "/" end\n'
        "  kong.service.request.set_path(new_path)\n"
        "end"
    )
    _ensure_pre_function_plugin(admin_url, route_name, lua)


def _ensure_capture_rewrite_plugin(
    admin_url: str,
    route_name: str,
    upstream_template: str,
    url_prefix: str,
) -> None:
    """
    Rewrite URI to the Django upstream template using Kong named captures.

    Also strips the service prefix when the matched path still includes it
    (compat paths under KONG_URL_PREFIX).
    """
    # Build Lua that substitutes {name} from uri captures into upstream template.
    template_lua = upstream_template.replace("\\", "\\\\").replace('"', '\\"')
    prefix_lua = url_prefix.rstrip("/").replace("\\", "\\\\").replace('"', '\\"')
    lua = (
        "local named = {}\n"
        "local ok, caps = pcall(kong.request.get_uri_captures)\n"
        "if ok and caps and caps.named then named = caps.named end\n"
        f'local template = "{template_lua}"\n'
        'local path = template:gsub("{(%w+)}", function(name) return named[name] or "" end)\n'
        f'local prefix = "{prefix_lua}"\n'
        "local current = kong.request.get_path()\n"
        "if current:sub(1, #prefix) == prefix or named.pk or next(named) then\n"
        "  kong.service.request.set_path(path)\n"
        "end"
    )
    _ensure_pre_function_plugin(admin_url, route_name, lua)


def _apply_rewrite_plugin(admin_url: str, route: Dict, url_prefix: str) -> None:
    mode = route.get("rewrite_mode") or "static_uri"
    upstream_uri = route["upstream_uri"]
    route_name = route["name"]

    if mode == "strip_prefix":
        _ensure_prefix_strip_plugin(admin_url, route_name, url_prefix)
    elif mode == "alias_captures":
        _ensure_capture_rewrite_plugin(admin_url, route_name, upstream_uri, url_prefix)
    else:
        if has_path_params(upstream_uri):
            _ensure_prefix_strip_plugin(admin_url, route_name, url_prefix)
        else:
            _ensure_uri_rewrite_plugin(admin_url, route_name, upstream_uri)


def _route_service_name(admin_url: str, existing_route: dict) -> str:
    """
    Resolve the Kong service name attached to a route.

    GET /routes/{name} usually returns ``service: {id}`` without ``name``;
    resolve via GET /services/{id} when needed.
    """
    service = existing_route.get("service") or {}
    name = service.get("name") or ""
    if name:
        return name
    service_id = service.get("id")
    if not service_id:
        return ""
    resp = http.get(f"{admin_url}/services/{service_id}", timeout=10)
    if resp.status_code != 200:
        return service_id
    return resp.json().get("name") or service_id


def sync_to_kong(admin_url: str, service: str, routes: List[Dict]) -> Tuple[List[str], List[str]]:
    """
    Registers discovered routes in Kong via the Admin API.

    Idempotent upsert:
      - creates the route when missing
      - patches paths/methods/strip_path/service when the route already exists
      - applies rewrite plugin based on rewrite_mode:
          static_uri      → request-transformer replace.uri
          strip_prefix    → pre-function strip KONG_URL_PREFIX
          alias_captures  → pre-function rewrite with named captures

    Alias routes (``allow-{alias}``) are last-writer-wins across services:
    PATCH reassigns ``service`` when another microservice claims the same alias.

    Args:
        admin_url: Kong Admin API base URL, e.g. http://localhost:8001
        service:   Fallback Kong service name when a route has no ``service`` key
        routes:    Route definitions returned by discover_routes()

    Returns:
        Tuple of (created route names, updated route names).

    Raises:
        requests.HTTPError: if the Admin API returns an unexpected error.
    """
    admin_url = admin_url.rstrip("/")
    url_prefix = os.environ.get("KONG_URL_PREFIX", "").rstrip("/")
    created: List[str] = []
    updated: List[str] = []

    for route in routes:
        upstream_uri = route.get("upstream_uri")
        if not upstream_uri:
            raise ValueError(
                f"route {route['name']} is missing upstream_uri; "
                "re-run discover_routes() with the updated weni_commons"
            )

        route_service = route.get("service") or service
        payload = {
            "name": route["name"],
            "paths": route["paths"],
            "methods": route["methods"],
            "strip_path": route["strip_path"],
            "service": {"name": route_service},
        }

        check = http.get(
            f"{admin_url}/routes/{route['name']}",
            timeout=10,
        )

        if check.status_code == 200:
            existing = check.json()
            previous_service = _route_service_name(admin_url, existing)
            if previous_service and previous_service != route_service:
                logger.warning(
                    "sync_to_kong: overwriting route %s: service %s -> %s",
                    route["name"],
                    previous_service,
                    route_service,
                )
            http.patch(
                f"{admin_url}/routes/{route['name']}",
                json=payload,
                timeout=10,
            ).raise_for_status()
            _apply_rewrite_plugin(admin_url, route, url_prefix)
            updated.append(route["name"])
            logger.info(
                "sync_to_kong: updated route %s -> %s (upstream %s, mode %s, service %s)",
                route["name"],
                route["paths"],
                upstream_uri,
                route.get("rewrite_mode", "static_uri"),
                route_service,
            )
            continue

        if check.status_code != 404:
            check.raise_for_status()

        # POST under the target service; body also carries service for clarity.
        create_payload = {
            "name": route["name"],
            "paths": route["paths"],
            "methods": route["methods"],
            "strip_path": route["strip_path"],
        }
        http.post(
            f"{admin_url}/services/{route_service}/routes",
            json=create_payload,
            timeout=10,
        ).raise_for_status()
        _apply_rewrite_plugin(admin_url, route, url_prefix)

        created.append(route["name"])
        logger.info(
            "sync_to_kong: created route %s -> %s (upstream %s, mode %s, service %s)",
            route["name"],
            route["paths"],
            upstream_uri,
            route.get("rewrite_mode", "static_uri"),
            route_service,
        )

    return created, updated
