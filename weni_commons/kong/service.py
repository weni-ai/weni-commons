"""
Idempotent Kong service + default-block registration via the Admin API.

Used by the ``kong_ensure_service`` management command so a new microservice
can be onboarded to the gateway without a declarative ``deck sync`` (which
would wipe dynamically created allow-routes).
"""
import logging

import requests as http

logger = logging.getLogger(__name__)

REQUEST_TERMINATION_PLUGIN = "request-termination"
DEFAULT_BLOCK_MESSAGE = "Route not authorized by the gateway"
DEFAULT_BLOCK_STATUS = 403


def _default_block_route_name(url_prefix: str) -> str:
    return f"{url_prefix.strip('/')}-default-block"


def ensure_service(admin_url: str, name: str, url: str) -> str:
    """
    Ensure a Kong service exists with the given upstream URL.

    Idempotent: creates on 404, patches ``url`` when it differs.

    Returns:
        The service name.
    """
    admin_url = admin_url.rstrip("/")
    url = url.rstrip("/")

    check = http.get(f"{admin_url}/services/{name}", timeout=10)
    if check.status_code == 200:
        current_url = (check.json().get("url") or "").rstrip("/")
        if current_url == url:
            logger.info("ensure_service: service %s already up to date", name)
            return name
        http.patch(
            f"{admin_url}/services/{name}",
            json={"url": url},
            timeout=10,
        ).raise_for_status()
        logger.info("ensure_service: updated service %s url -> %s", name, url)
        return name

    if check.status_code != 404:
        check.raise_for_status()

    http.post(
        f"{admin_url}/services",
        json={"name": name, "url": url},
        timeout=10,
    ).raise_for_status()
    logger.info("ensure_service: created service %s -> %s", name, url)
    return name


def _ensure_request_termination_plugin(admin_url: str, route_name: str) -> None:
    """Ensure the route has request-termination with the gateway default-block config."""
    plugin_payload = {
        "name": REQUEST_TERMINATION_PLUGIN,
        "config": {
            "status_code": DEFAULT_BLOCK_STATUS,
            "message": DEFAULT_BLOCK_MESSAGE,
        },
    }

    listed = http.get(f"{admin_url}/routes/{route_name}/plugins", timeout=10)
    listed.raise_for_status()
    plugins = listed.json().get("data", [])

    existing = next(
        (p for p in plugins if p.get("name") == REQUEST_TERMINATION_PLUGIN),
        None,
    )
    if existing:
        config = existing.get("config") or {}
        if (
            config.get("status_code") == DEFAULT_BLOCK_STATUS
            and config.get("message") == DEFAULT_BLOCK_MESSAGE
        ):
            logger.debug(
                "ensure_default_block: route %s already has request-termination",
                route_name,
            )
            return
        http.patch(
            f"{admin_url}/plugins/{existing['id']}",
            json=plugin_payload,
            timeout=10,
        ).raise_for_status()
        logger.info(
            "ensure_default_block: updated request-termination on %s",
            route_name,
        )
        return

    http.post(
        f"{admin_url}/routes/{route_name}/plugins",
        json=plugin_payload,
        timeout=10,
    ).raise_for_status()
    logger.info(
        "ensure_default_block: created request-termination on %s",
        route_name,
    )


def ensure_default_block(admin_url: str, service: str, url_prefix: str) -> str:
    """
    Ensure a catch-all default-block route exists under ``url_prefix``.

    Creates/updates a route named ``{prefix}-default-block`` with
    ``request-termination`` (403). Does not touch allow-routes.

    Returns:
        The default-block route name.
    """
    admin_url = admin_url.rstrip("/")
    prefix = "/" + url_prefix.strip("/")
    route_name = _default_block_route_name(prefix)
    route_payload = {
        "name": route_name,
        "paths": [prefix],
        "strip_path": False,
    }

    check = http.get(f"{admin_url}/routes/{route_name}", timeout=10)
    if check.status_code == 200:
        http.patch(
            f"{admin_url}/routes/{route_name}",
            json=route_payload,
            timeout=10,
        ).raise_for_status()
        logger.info(
            "ensure_default_block: updated route %s -> %s",
            route_name,
            prefix,
        )
    elif check.status_code == 404:
        http.post(
            f"{admin_url}/services/{service}/routes",
            json=route_payload,
            timeout=10,
        ).raise_for_status()
        logger.info(
            "ensure_default_block: created route %s -> %s (service %s)",
            route_name,
            prefix,
            service,
        )
    else:
        check.raise_for_status()

    _ensure_request_termination_plugin(admin_url, route_name)
    return route_name
