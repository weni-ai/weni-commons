"""
Route discovery and Kong Admin API sync.

discover_routes() walks Django's URL resolver to find all views marked with
@kong_expose whose URL pattern ends with the given suffix (default: .json).

sync_to_kong() applies the discovered routes to Kong via the Admin API.
Both functions require Kong running in DB mode (with PostgreSQL). DB-less
mode does not support route creation via the Admin API.

Required environment variable:
    KONG_URL_PREFIX  — gateway path prefix for this service, e.g. /flows
"""
import logging
import os
from typing import Dict, List

import requests as http

logger = logging.getLogger(__name__)


def discover_routes(suffix: str = ".json") -> List[Dict]:
    """
    Walks Django's URL resolver and returns all views decorated with
    @kong_expose, resolving each to a concrete gateway path.

    Paths are resolved with ``reverse()`` rather than by parsing the raw
    pattern string. This works with both clean ``RoutePattern`` URLs and
    regex ``url()``/``re_path()`` entries that use DRF's
    ``format_suffix_patterns`` (e.g. ``events\\.(?P<format>(json|api))``).

    The Kong path for each route is built as:
        {KONG_URL_PREFIX}{reverse(name, format=json)}

    Raises:
        KeyError: if KONG_URL_PREFIX is not set in the environment.
    """
    url_prefix = os.environ["KONG_URL_PREFIX"].rstrip("/")
    fmt = suffix.lstrip(".")

    from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, reverse

    # Collect one view class per named route that opts in via @kong_expose.
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

        kong_path = url_prefix + "/" + path.lstrip("/")
        route_name = "allow-" + path.strip("/").replace("/", "-").replace(".", "-")
        routes.append(
            {
                "name": route_name,
                "paths": [kong_path],
                "methods": view_class._kong_methods,
                "service": view_class._kong_service,
                "strip_path": True,
            }
        )
        logger.debug("discover_routes: found %s -> %s", route_name, kong_path)

    logger.info("discover_routes: %d route(s) discovered", len(routes))
    return routes


def sync_to_kong(admin_url: str, service: str, routes: List[Dict]) -> List[str]:
    """
    Registers discovered routes in Kong via the Admin API.

    Idempotent: routes that already exist (HTTP 200 on GET /routes/{name})
    are skipped without raising an error.

    Args:
        admin_url: Kong Admin API base URL, e.g. http://localhost:8001
        service:   Kong service name to attach routes to
        routes:    Route definitions returned by discover_routes()

    Returns:
        List of route names that were newly created (skips pre-existing ones).

    Raises:
        requests.HTTPError: if the Admin API returns an unexpected error.
    """
    admin_url = admin_url.rstrip("/")
    created: List[str] = []

    for route in routes:
        check = http.get(
            f"{admin_url}/routes/{route['name']}",
            timeout=10,
        )
        if check.status_code == 200:
            logger.info("sync_to_kong: route %s already exists — skipping", route["name"])
            continue

        payload = {
            "name": route["name"],
            "paths": route["paths"],
            "methods": route["methods"],
            "strip_path": route["strip_path"],
        }
        http.post(
            f"{admin_url}/services/{service}/routes",
            json=payload,
            timeout=10,
        ).raise_for_status()

        created.append(route["name"])
        logger.info("sync_to_kong: created route %s -> %s", route["name"], route["paths"])

    return created
