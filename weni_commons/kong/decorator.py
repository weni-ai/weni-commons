"""
@api_gateway_expose — marks a Django view to be exposed via Kong API Gateway.

The decorator does not register paths at import time. Paths are discovered
automatically at sync time by walking Django's URL resolver (see sync.py).

Usage:

    from weni_commons.kong import api_gateway_expose

    @api_gateway_expose
    class WorkspaceEndpoint(BaseAPIView):
        ...
        # Public: /flows/api/v2/workspace.json  (requires KONG_URL_PREFIX=/flows)

    @api_gateway_expose(methods=["GET", "POST"])
    class FlowStartsEndpoint(BaseAPIView):
        ...

    @api_gateway_expose(alias="events")
    class EventsEndpoint(BaseAPIView):
        ...
        # Public (flat):   /events
        # Compat:          /flows/events  and  /flows/api/v2/events.json
        # Upstream:        /api/v2/events.json
        #
        # Alias routes are last-writer-wins: another service that syncs the
        # same alias overwrites the Kong route (service + upstream).
"""
import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def _normalize_alias(alias: Optional[str]) -> Optional[str]:
    if alias is None:
        return None
    normalized = alias.strip().strip("/")
    if not normalized:
        raise ValueError(
            "api_gateway_expose(alias=...) must be a non-empty path segment "
            "(e.g. alias='events')"
        )
    return normalized


def api_gateway_expose(
    _view: Any = None,
    *,
    methods: Optional[List[str]] = None,
    service: str = "flows-service",
    alias: Optional[str] = None,
) -> Any:
    """
    Marks a view as exposed via the API gateway (Kong).

    Can be used with or without arguments:
        @api_gateway_expose
        @api_gateway_expose(methods=["GET", "POST"])
        @api_gateway_expose(methods=["GET"], service="nexus-service")
        @api_gateway_expose(alias="events")

    Args:
        methods: HTTP methods allowed on this route. Defaults to ["GET"].
        service: Kong service name this view belongs to.
        alias: Optional short public path (global). When set, Kong exposes:
            - ``/{alias}`` (flat public path, e.g. ``/events``)
            - ``/{KONG_URL_PREFIX}/{alias}`` (compat, e.g. ``/flows/events``)
            - ``/{KONG_URL_PREFIX}{django_path}`` (compat full path)
            Upstream remains the Django path. The Kong route is named
            ``allow-{alias}`` and is last-writer-wins across services.

    The decorator does not modify the view behaviour — it only sets
    private attributes used by the kong_sync management command.
    """
    normalized_methods = [m.upper() for m in (methods or ["GET"])]
    normalized_alias = _normalize_alias(alias)

    def decorator(view: Any) -> Any:
        view._kong_expose = True
        view._kong_methods = normalized_methods
        view._kong_service = service
        view._kong_alias = normalized_alias
        logger.debug(
            "api_gateway_expose: marked %s (methods=%s, service=%s, alias=%s)",
            getattr(view, "__name__", repr(view)),
            normalized_methods,
            service,
            normalized_alias,
        )
        return view

    if _view is not None:
        # Used as bare @api_gateway_expose (without parentheses)
        return decorator(_view)

    # Used as @api_gateway_expose(...) — return the decorator
    return decorator


# Backward-compatible alias; prefer api_gateway_expose in new code.
kong_expose = api_gateway_expose
