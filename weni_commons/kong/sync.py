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

sync_to_kong() reconciles instead of blindly upserting: it reads the Kong state
in bulk (routes and plugins, paginated), writes only what differs, and prunes
the ``allow-*`` routes of this service that discovery no longer finds. Prune is
on by default and guarded — see prune_routes().
"""
import logging
import os
from typing import Dict, List, Optional, Tuple

import requests as http

from weni_commons.kong.config import resolved_kong_service
from weni_commons.kong.discovery import iter_exposed_views, kong_route_name
from weni_commons.kong.paths import (
    has_path_params,
    join_prefix,
    kong_regex_path,
    normalize_path,
    rewrite_mode_for,
)

logger = logging.getLogger(__name__)

REQUEST_TRANSFORMER_PLUGIN = "request-transformer"
PRE_FUNCTION_PLUGIN = "pre-function"

ADMIN_TIMEOUT = 10
PAGE_SIZE = 1000
ROUTE_NAME_PREFIX = "allow-"
ROUTE_TAG = "kong-sync"


class PruneLimitExceeded(Exception):
    """Prune would delete more routes than the safety threshold allows."""


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


def discover_routes(
    suffix: str = ".json",
    default_service: Optional[str] = None,
) -> List[Dict]:
    """
    Walks Django's URL resolver and returns all views decorated with
    @api_gateway_expose, resolving each URL pattern to gateway path(s).

    Supports:
        - APIView (``callback.view_class``)
        - ViewSet / @action (``callback.cls`` + ``callback.actions``)
        - Class-level or method-level decorator (method wins for alias/service)
        - Path params as Kong regex ``(?<pk>[^/]+)`` with rewrite_mode

    A decorator with ``service=None`` (the default) is filled with
    ``default_service``, or derived from ``KONG_URL_PREFIX`` when that is
    omitted (``/flows`` → ``flows-service``). An explicit ``service=`` on
    the decorator is kept as-is.

    Raises:
        KeyError: if KONG_URL_PREFIX is not set in the environment.
        ValueError: if a None service cannot be derived from the prefix.
    """
    url_prefix = os.environ["KONG_URL_PREFIX"].rstrip("/")

    # Keyed by Kong route name so duplicate aliases overwrite (last-writer-wins).
    routes_by_name: Dict[str, Dict] = {}

    for record in iter_exposed_views(suffix):
        upstream_template = record["upstream_path"]
        alias = record["alias"]

        rewrite_mode, alias_for_paths = rewrite_mode_for(upstream_template, alias)
        if alias and alias_for_paths is None and has_path_params(upstream_template):
            logger.warning(
                "discover_routes: alias %r has no path params but upstream "
                "%s requires them — registering prefix path only",
                alias,
                upstream_template,
            )

        paths = _gateway_paths(
            url_prefix,
            upstream_template,
            alias_for_paths,
            rewrite_mode,
        )
        route_name = kong_route_name(upstream_template, alias_for_paths)

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
            "methods": record["methods"],
            "service": resolved_kong_service(
                record["service"] or default_service, url_prefix
            ),
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
            routes_by_name[route_name]["service"],
        )

    routes = list(routes_by_name.values())
    logger.info("discover_routes: %d route(s) discovered", len(routes))
    return routes


def _list_route_plugins(admin_url: str, route_name: str) -> List[dict]:
    listed = http.get(f"{admin_url}/routes/{route_name}/plugins", timeout=ADMIN_TIMEOUT)
    listed.raise_for_status()
    return listed.json().get("data", [])


def _paginate(admin_url: str, path: str) -> List[dict]:
    """Collect every entity from a paginated Admin API collection."""
    items: List[dict] = []
    url = f"{admin_url}{path}?size={PAGE_SIZE}"

    while url:
        resp = http.get(url, timeout=ADMIN_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json() or {}
        items.extend(payload.get("data") or [])

        next_url = payload.get("next")
        if not next_url:
            break
        if not next_url.startswith("http"):
            next_url = f"{admin_url}{next_url}"
        if next_url == url:
            break
        url = next_url

    return items


def _list_all_routes(admin_url: str) -> List[dict]:
    """All Kong routes, so route existence is checked globally (names are unique)."""
    return _paginate(admin_url, "/routes")


def _list_all_plugins(admin_url: str) -> Dict[str, List[dict]]:
    """All route-scoped plugins, grouped by route id."""
    grouped: Dict[str, List[dict]] = {}
    for plugin in _paginate(admin_url, "/plugins"):
        route_id = (plugin.get("route") or {}).get("id")
        if route_id:
            grouped.setdefault(route_id, []).append(plugin)
    return grouped


def _resolve_service_id(
    admin_url: str, service: str, cache: Dict[str, Optional[str]]
) -> Optional[str]:
    """Service id for ``service``, memoized across routes of the same run."""
    if service not in cache:
        resp = http.get(f"{admin_url}/services/{service}", timeout=ADMIN_TIMEOUT)
        if resp.status_code == 200:
            cache[service] = (resp.json() or {}).get("id")
        elif resp.status_code == 404:
            cache[service] = None
        else:
            resp.raise_for_status()
            cache[service] = None
    return cache[service]


def _prefix_tag(url_prefix: str) -> str:
    """
    Ownership tag for this service's prefix.

    Uses ``prefix-<slug>`` (e.g. ``prefix-flows``) instead of ``prefix:/flows``.
    Older Kong builds reject ``:`` inside tags with a schema-violation 400.
    """
    return f"prefix-{url_prefix.strip('/')}"


def _route_tags(url_prefix: str) -> List[str]:
    return [ROUTE_TAG, _prefix_tag(url_prefix)]


def _raise_for_status(response, action: str) -> None:
    """Like ``raise_for_status``, but includes Kong's response body in the error."""
    try:
        response.raise_for_status()
    except http.HTTPError as exc:
        body = (response.text or "").strip()
        detail = f"{action}: {exc}"
        if body:
            detail = f"{detail} — {body}"
        raise http.HTTPError(detail, response=response) from exc


def _delete_plugins_named(admin_url: str, plugins: List[dict], names: set) -> List[dict]:
    """Delete the named plugins and return the ones left untouched."""
    remaining: List[dict] = []
    for plugin in plugins:
        if plugin.get("name") in names:
            http.delete(
                f"{admin_url}/plugins/{plugin['id']}", timeout=ADMIN_TIMEOUT
            ).raise_for_status()
            logger.info(
                "sync_to_kong: removed plugin %s from route",
                plugin.get("name"),
            )
        else:
            remaining.append(plugin)
    return remaining


def _request_transformer_payload(upstream_uri: str) -> dict:
    return {
        "name": REQUEST_TRANSFORMER_PLUGIN,
        "config": {
            "replace": {
                "uri": upstream_uri,
            }
        },
    }


def _pre_function_payload(lua_source: str) -> dict:
    return {
        "name": PRE_FUNCTION_PLUGIN,
        "config": {
            "access": [lua_source],
        },
    }


def _prefix_strip_lua(url_prefix: str) -> str:
    """Strip KONG_URL_PREFIX from the request path, preserving the rest (incl. pk)."""
    prefix = url_prefix.rstrip("/")
    # Escape for Lua string literal.
    prefix_lua = prefix.replace("\\", "\\\\").replace('"', '\\"')
    return (
        f'local prefix = "{prefix_lua}"\n'
        "local path = kong.request.get_path()\n"
        "if path:sub(1, #prefix) == prefix then\n"
        "  local new_path = path:sub(#prefix + 1)\n"
        '  if new_path == "" then new_path = "/" end\n'
        "  kong.service.request.set_path(new_path)\n"
        "end"
    )


def _capture_rewrite_lua(upstream_template: str, url_prefix: str) -> str:
    """
    Rewrite URI to the Django upstream template using Kong named captures.

    Also strips the service prefix when the matched path still includes it
    (compat paths under KONG_URL_PREFIX).
    """
    # Build Lua that substitutes {name} from uri captures into upstream template.
    template_lua = upstream_template.replace("\\", "\\\\").replace('"', '\\"')
    prefix_lua = url_prefix.rstrip("/").replace("\\", "\\\\").replace('"', '\\"')
    return (
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


def _desired_rewrite_plugin(route: Dict, url_prefix: str) -> dict:
    """Plugin payload this route should carry, per its rewrite_mode."""
    mode = route.get("rewrite_mode") or "static_uri"
    upstream_uri = route["upstream_uri"]

    if mode == "strip_prefix":
        return _pre_function_payload(_prefix_strip_lua(url_prefix))
    if mode == "alias_captures":
        return _pre_function_payload(_capture_rewrite_lua(upstream_uri, url_prefix))
    if has_path_params(upstream_uri):
        return _pre_function_payload(_prefix_strip_lua(url_prefix))
    return _request_transformer_payload(upstream_uri)


def _obsolete_plugin_name(desired_name: str) -> str:
    if desired_name == REQUEST_TRANSFORMER_PLUGIN:
        return PRE_FUNCTION_PLUGIN
    return REQUEST_TRANSFORMER_PLUGIN


def _plugin_config_matches(existing: dict, desired: dict) -> bool:
    config = existing.get("config") or {}
    desired_config = desired["config"]

    if desired["name"] == REQUEST_TRANSFORMER_PLUGIN:
        current = (config.get("replace") or {}).get("uri")
        return current == desired_config["replace"]["uri"]

    return (config.get("access") or []) == desired_config["access"]


def _rewrite_plugin_in_sync(desired: dict, plugins: List[dict]) -> bool:
    """Whether the route's plugins already match ``desired`` (no HTTP calls)."""
    obsolete = _obsolete_plugin_name(desired["name"])
    if any(plugin.get("name") == obsolete for plugin in plugins):
        return False

    existing = next((p for p in plugins if p.get("name") == desired["name"]), None)
    if existing is None:
        return False

    return _plugin_config_matches(existing, desired)


def _apply_rewrite_plugin(
    admin_url: str, route_name: str, desired: dict, plugins: List[dict]
) -> None:
    remaining = _delete_plugins_named(
        admin_url, plugins, {_obsolete_plugin_name(desired["name"])}
    )
    existing = next((p for p in remaining if p.get("name") == desired["name"]), None)

    if existing:
        if _plugin_config_matches(existing, desired):
            return
        http.patch(
            f"{admin_url}/plugins/{existing['id']}",
            json=desired,
            timeout=ADMIN_TIMEOUT,
        ).raise_for_status()
        logger.info(
            "sync_to_kong: updated %s on %s", desired["name"], route_name
        )
        return

    http.post(
        f"{admin_url}/routes/{route_name}/plugins",
        json=desired,
        timeout=ADMIN_TIMEOUT,
    ).raise_for_status()
    logger.info("sync_to_kong: created %s on %s", desired["name"], route_name)


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
    resp = http.get(f"{admin_url}/services/{service_id}", timeout=ADMIN_TIMEOUT)
    if resp.status_code != 200:
        return service_id
    return resp.json().get("name") or service_id


def _route_needs_patch(payload: Dict, existing: dict, service_id: Optional[str]) -> bool:
    """Whether the live route diverges on any field this sync manages."""
    if set(payload["paths"]) != set(existing.get("paths") or []):
        return True
    if set(payload["methods"]) != set(existing.get("methods") or []):
        return True
    if bool(payload["strip_path"]) != bool(existing.get("strip_path")):
        return True
    if set(payload["tags"]) != set(existing.get("tags") or []):
        return True
    if service_id and (existing.get("service") or {}).get("id") != service_id:
        return True
    return False


def _path_under_prefix(path: str, url_prefix: str) -> bool:
    candidate = path[1:] if path.startswith("~") else path
    prefix = url_prefix.rstrip("/")
    if not prefix:
        return False
    return candidate == prefix or candidate.startswith(prefix + "/")


def _is_managed_route(route: dict, service_id: str, url_prefix: str) -> bool:
    """
    Whether this sync owns the route and may therefore delete it.

    Ownership requires the route to sit on this service, to carry the ``allow-``
    name prefix (so the default-block and hand-made routes are never touched),
    and to be recognizable as ours — by our prefix tag, or, for routes written
    before tagging, by serving a path under KONG_URL_PREFIX.

    Matching the prefix tag rather than the generic ROUTE_TAG is what keeps
    routes of another prefix safe when they happen to sit on this Kong service.
    ``api_gateway_expose`` defaults ``service`` to this sync's service (derived
    from KONG_URL_PREFIX), and an explicit ``service=`` can still point a view
    here; those routes already carry ``kong-sync``, but their prefix tag is
    their own. If prune trusted the generic tag, this sync would treat them as
    its own and delete them.
    """
    name = route.get("name") or ""
    if not name.startswith(ROUTE_NAME_PREFIX):
        return False
    if (route.get("service") or {}).get("id") != service_id:
        return False
    if _prefix_tag(url_prefix) in (route.get("tags") or []):
        return True
    return any(_path_under_prefix(p, url_prefix) for p in route.get("paths") or [])


def prune_routes(
    admin_url: str,
    service_id: Optional[str],
    url_prefix: str,
    desired_names: set,
    existing_routes: List[dict],
    force: bool = False,
    dry_run: bool = False,
) -> List[str]:
    """
    Delete the allow-routes of this service that discovery no longer produces.

    ``desired_names`` must carry every discovered route name, including those
    targeting another Kong service, so a route moving across services in this
    same run is not mistaken for an orphan.

    Args:
        admin_url:       Kong Admin API base URL
        service_id:      Kong id of the service being synced
        url_prefix:      KONG_URL_PREFIX of this service
        desired_names:   Every route name produced by discover_routes()
        existing_routes: Kong route snapshot taken before the upsert
        force:           Bypass the volume threshold
        dry_run:         Report the deletions without applying them

    Returns:
        Names of the deleted routes.

    Raises:
        PruneLimitExceeded: if the deletions exceed the safety threshold and
            ``force`` is not set.
    """
    if not desired_names:
        logger.warning("prune_routes: discovery is empty — skipping prune")
        return []
    if not service_id:
        logger.warning("prune_routes: service id unavailable — skipping prune")
        return []

    owned = [r for r in existing_routes if _is_managed_route(r, service_id, url_prefix)]
    orphans = [r for r in owned if (r.get("name") or "") not in desired_names]
    if not orphans:
        return []

    limit = max(3, len(owned) // 2)
    if len(orphans) > limit and not force:
        names = ", ".join(sorted(r["name"] for r in orphans))
        raise PruneLimitExceeded(
            f"prune would delete {len(orphans)} of {len(owned)} managed route(s), "
            f"above the safety limit of {limit}: {names}. "
            "Re-run with --force-prune to confirm."
        )

    deleted: List[str] = []
    for route in orphans:
        name = route["name"]
        if not dry_run:
            http.delete(
                f"{admin_url}/routes/{name}", timeout=ADMIN_TIMEOUT
            ).raise_for_status()
        deleted.append(name)
        logger.info(
            "sync_to_kong: deleted orphan route %s -> %s",
            name,
            route.get("paths"),
        )

    return deleted


def sync_to_kong(
    admin_url: str,
    service: str,
    routes: List[Dict],
    prune: bool = True,
    force_prune: bool = False,
    dry_run: bool = False,
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    Reconciles discovered routes with Kong via the Admin API.

    Reads the Kong state in bulk (routes and plugins), then per route:
      - creates it when missing
      - patches paths/methods/strip_path/tags/service only when they diverge
      - writes the rewrite plugin only when it diverges:
          static_uri      → request-transformer replace.uri
          strip_prefix    → pre-function strip KONG_URL_PREFIX
          alias_captures  → pre-function rewrite with named captures
      - leaves it untouched otherwise

    Then, unless ``prune`` is off, deletes the allow-routes of ``service`` that
    discovery no longer produces (see prune_routes).

    Alias routes (``allow-{alias}``) are last-writer-wins across services:
    PATCH reassigns ``service`` when another microservice claims the same alias.

    Args:
        admin_url:   Kong Admin API base URL, e.g. http://localhost:8001
        service:     Fallback Kong service name when a route has no ``service`` key
        routes:      Route definitions returned by discover_routes()
        prune:       Delete orphan allow-routes of ``service``
        force_prune: Bypass the prune volume threshold
        dry_run:     Compute the plan without writing to Kong

    Returns:
        Tuple of (created, updated, skipped, deleted) route names.

    Raises:
        requests.HTTPError: if the Admin API returns an unexpected error.
        PruneLimitExceeded: if prune exceeds the safety threshold.
    """
    admin_url = admin_url.rstrip("/")
    url_prefix = os.environ.get("KONG_URL_PREFIX", "").rstrip("/")
    tags = _route_tags(url_prefix)

    existing_routes = _list_all_routes(admin_url)
    routes_by_name = {r["name"]: r for r in existing_routes if r.get("name")}
    plugins_by_route = _list_all_plugins(admin_url)
    service_ids: Dict[str, Optional[str]] = {}

    created: List[str] = []
    updated: List[str] = []
    skipped: List[str] = []

    for route in routes:
        upstream_uri = route.get("upstream_uri")
        if not upstream_uri:
            raise ValueError(
                f"route {route['name']} is missing upstream_uri; "
                "re-run discover_routes() with the updated weni_commons"
            )

        route_name = route["name"]
        route_service = route.get("service") or service
        payload = {
            "name": route_name,
            "paths": route["paths"],
            "methods": route["methods"],
            "strip_path": route["strip_path"],
            "tags": tags,
            "service": {"name": route_service},
        }
        desired_plugin = _desired_rewrite_plugin(route, url_prefix)
        existing = routes_by_name.get(route_name)

        if existing is None:
            if not dry_run:
                # POST under the target service; the service is implied by the URL.
                create_payload = {k: v for k, v in payload.items() if k != "service"}
                create_resp = http.post(
                    f"{admin_url}/services/{route_service}/routes",
                    json=create_payload,
                    timeout=ADMIN_TIMEOUT,
                )
                _raise_for_status(
                    create_resp,
                    f"creating route {route_name} (payload={create_payload!r})",
                )
                _apply_rewrite_plugin(admin_url, route_name, desired_plugin, [])
            created.append(route_name)
            logger.info(
                "sync_to_kong: created route %s -> %s (upstream %s, mode %s, service %s)",
                route_name,
                route["paths"],
                upstream_uri,
                route.get("rewrite_mode", "static_uri"),
                route_service,
            )
            continue

        target_service_id = _resolve_service_id(admin_url, route_service, service_ids)
        plugins = plugins_by_route.get(existing.get("id"), [])
        route_diverged = _route_needs_patch(payload, existing, target_service_id)
        plugin_diverged = not _rewrite_plugin_in_sync(desired_plugin, plugins)

        if not route_diverged and not plugin_diverged:
            skipped.append(route_name)
            logger.debug("sync_to_kong: route %s already in sync", route_name)
            continue

        if route_diverged:
            if target_service_id and (existing.get("service") or {}).get("id") != target_service_id:
                logger.warning(
                    "sync_to_kong: overwriting route %s: service %s -> %s",
                    route_name,
                    _route_service_name(admin_url, existing),
                    route_service,
                )
            if not dry_run:
                patch_resp = http.patch(
                    f"{admin_url}/routes/{route_name}",
                    json=payload,
                    timeout=ADMIN_TIMEOUT,
                )
                _raise_for_status(
                    patch_resp,
                    f"updating route {route_name} (payload={payload!r})",
                )

        if plugin_diverged and not dry_run:
            _apply_rewrite_plugin(admin_url, route_name, desired_plugin, plugins)

        updated.append(route_name)
        logger.info(
            "sync_to_kong: updated route %s -> %s (upstream %s, mode %s, service %s)",
            route_name,
            route["paths"],
            upstream_uri,
            route.get("rewrite_mode", "static_uri"),
            route_service,
        )

    deleted: List[str] = []
    if prune:
        deleted = prune_routes(
            admin_url,
            _resolve_service_id(admin_url, service, service_ids),
            url_prefix,
            {r["name"] for r in routes},
            existing_routes,
            force=force_prune,
            dry_run=dry_run,
        )

    return created, updated, skipped, deleted
