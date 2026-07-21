"""
Route discovery and Kong Admin API sync.

discover_routes() walks Django's URL resolver to find all views marked with
@api_gateway_expose, resolving each to a concrete gateway path.

sync_to_kong() applies the discovered routes to Kong via the Admin API.
Both functions require Kong running in DB mode (with PostgreSQL). DB-less
mode does not support route creation via the Admin API.

Required environment variable:
    KONG_URL_PREFIX  — gateway path prefix for this service, e.g. /flows

Gateway URLs keep the service prefix (client-facing):
    {KONG_URL_PREFIX}{django_path}   e.g. /flows/api/v2/contacts.json

When a view sets ``alias`` on @api_gateway_expose, an additional short path
is also registered:
    {KONG_URL_PREFIX}/{alias}        e.g. /flows/events

Upstream URIs drop only that prefix (via request-transformer):
    {django_path}                    e.g. /api/v2/contacts.json

``strip_path`` must stay false on allow-routes: with the full gateway path in
``paths``, ``strip_path=true`` would strip the entire match and forward ``/``.
"""
import logging
import os
from typing import Dict, List, Set, Tuple

import requests as http

logger = logging.getLogger(__name__)

REQUEST_TRANSFORMER_PLUGIN = "request-transformer"


def discover_routes(suffix: str = ".json") -> List[Dict]:
    """
    Walks Django's URL resolver and returns all views decorated with
    @api_gateway_expose, resolving each to a concrete gateway path.

    Paths are resolved with ``reverse()`` rather than by parsing the raw
    pattern string. This works with both clean ``RoutePattern`` URLs and
    regex ``url()``/``re_path()`` entries that use DRF's
    ``format_suffix_patterns`` (e.g. ``events\\.(?P<format>(json|api))``).

    The Kong path for each route is built as:
        {KONG_URL_PREFIX}{reverse(name, format=json)}

    If the view defines ``_kong_alias``, an additional short path
    ``{KONG_URL_PREFIX}/{alias}`` is included in the same route.

    Raises:
        KeyError: if KONG_URL_PREFIX is not set in the environment.
    """
    url_prefix = os.environ["KONG_URL_PREFIX"].rstrip("/")
    fmt = suffix.lstrip(".")

    from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, reverse

    # Collect one view class per named route that opts in via @api_gateway_expose.
    exposed: Dict[str, object] = {}

    def walk(resolver: "URLResolver") -> None:
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern)
            elif isinstance(pattern, URLPattern):
                view_class = getattr(pattern.callback, "view_class", None)
                if not view_class or not getattr(view_class, "_kong_expose", False):
                    continue
                if not pattern.name or pattern.name in exposed:
                    continue
                exposed[pattern.name] = view_class

    walk(get_resolver())

    routes: List[Dict] = []
    seen_aliases: Set[str] = set()

    for name, view_class in exposed.items():
        path = None
        # Prefer the format-suffixed URL (…/events.json); fall back to the
        # bare URL with the suffix appended.
        try:
            path = reverse(name, kwargs={"format": fmt})
        except NoReverseMatch:
            try:
                path = reverse(name).rstrip("/") + suffix
            except NoReverseMatch:
                logger.warning("discover_routes: could not reverse %s — skipping", name)
                continue

        upstream_uri = "/" + path.lstrip("/")
        full_gateway_path = url_prefix + upstream_uri
        paths = [full_gateway_path]

        alias = getattr(view_class, "_kong_alias", None)
        if alias:
            if alias in seen_aliases:
                logger.warning(
                    "discover_routes: duplicate alias %r on %s — "
                    "keeping full path only for this view",
                    alias,
                    getattr(view_class, "__name__", name),
                )
            else:
                seen_aliases.add(alias)
                paths.insert(0, f"{url_prefix}/{alias}")

        route_name = "allow-" + path.strip("/").replace("/", "-").replace(".", "-")
        routes.append(
            {
                "name": route_name,
                "paths": paths,
                "methods": view_class._kong_methods,
                "service": view_class._kong_service,
                "strip_path": False,
                "upstream_uri": upstream_uri,
            }
        )
        logger.debug(
            "discover_routes: found %s -> %s (upstream %s)",
            route_name,
            paths,
            upstream_uri,
        )

    logger.info("discover_routes: %d route(s) discovered", len(routes))
    return routes


def _ensure_uri_rewrite_plugin(admin_url: str, route_name: str, upstream_uri: str) -> None:
    """
    Ensure the route has a request-transformer that rewrites the URI to the
    upstream Django path (service prefix removed).
    """
    plugin_payload = {
        "name": REQUEST_TRANSFORMER_PLUGIN,
        "config": {
            "replace": {
                "uri": upstream_uri,
            }
        },
    }

    listed = http.get(f"{admin_url}/routes/{route_name}/plugins", timeout=10)
    listed.raise_for_status()
    plugins = listed.json().get("data", [])

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


def sync_to_kong(admin_url: str, service: str, routes: List[Dict]) -> Tuple[List[str], List[str]]:
    """
    Registers discovered routes in Kong via the Admin API.

    Idempotent upsert:
      - creates the route when missing
      - patches strip_path/paths/methods when the route already exists
      - ensures a request-transformer rewrites URI to the Django path

    Args:
        admin_url: Kong Admin API base URL, e.g. http://localhost:8001
        service:   Kong service name to attach routes to
        routes:    Route definitions returned by discover_routes()

    Returns:
        Tuple of (created route names, updated route names).

    Raises:
        requests.HTTPError: if the Admin API returns an unexpected error.
    """
    admin_url = admin_url.rstrip("/")
    created: List[str] = []
    updated: List[str] = []

    for route in routes:
        upstream_uri = route.get("upstream_uri")
        if not upstream_uri:
            raise ValueError(
                f"route {route['name']} is missing upstream_uri; "
                "re-run discover_routes() with the updated weni_commons"
            )

        payload = {
            "name": route["name"],
            "paths": route["paths"],
            "methods": route["methods"],
            "strip_path": route["strip_path"],
        }

        check = http.get(
            f"{admin_url}/routes/{route['name']}",
            timeout=10,
        )

        if check.status_code == 200:
            http.patch(
                f"{admin_url}/routes/{route['name']}",
                json=payload,
                timeout=10,
            ).raise_for_status()
            _ensure_uri_rewrite_plugin(admin_url, route["name"], upstream_uri)
            updated.append(route["name"])
            logger.info(
                "sync_to_kong: updated route %s -> %s (upstream %s)",
                route["name"],
                route["paths"],
                upstream_uri,
            )
            continue

        if check.status_code != 404:
            check.raise_for_status()

        http.post(
            f"{admin_url}/services/{service}/routes",
            json=payload,
            timeout=10,
        ).raise_for_status()
        _ensure_uri_rewrite_plugin(admin_url, route["name"], upstream_uri)

        created.append(route["name"])
        logger.info(
            "sync_to_kong: created route %s -> %s (upstream %s)",
            route["name"],
            route["paths"],
            upstream_uri,
        )

    return created, updated
