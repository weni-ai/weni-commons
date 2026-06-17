"""
@kong_expose — marks a Django view to be exposed via Kong API Gateway.

The decorator does not register paths at import time. Paths are discovered
automatically at sync time by walking Django's URL resolver (see sync.py).

Usage:

    from weni_commons.kong import kong_expose

    @kong_expose
    class WorkspaceEndpoint(BaseAPIView):
        ...

    @kong_expose(methods=["GET", "POST"])
    class FlowStartsEndpoint(BaseAPIView):
        ...
"""
import functools
import logging
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


def kong_expose(
    _view: Any = None,
    *,
    methods: Optional[List[str]] = None,
    service: str = "flows-service",
) -> Any:
    """
    Marks a view as exposed via Kong.

    Can be used with or without arguments:
        @kong_expose
        @kong_expose(methods=["GET", "POST"])
        @kong_expose(methods=["GET"], service="nexus-service")

    Args:
        methods: HTTP methods allowed on this route. Defaults to ["GET"].
        service: Kong service name this view belongs to.

    The decorator does not modify the view in any way — it only sets
    private attributes used by the kong_sync management command.
    """
    normalized_methods = [m.upper() for m in (methods or ["GET"])]

    def decorator(view: Any) -> Any:
        view._kong_expose = True
        view._kong_methods = normalized_methods
        view._kong_service = service
        logger.debug(
            "kong_expose: marked %s (methods=%s, service=%s)",
            getattr(view, "__name__", repr(view)),
            normalized_methods,
            service,
        )
        return view

    if _view is not None:
        # Used as bare @kong_expose (without parentheses)
        return decorator(_view)

    # Used as @kong_expose(...) — return the decorator
    return decorator
