"""
Configuration lookup shared by the Kong management commands.

Values may be declared either in the host project's Django settings or in the
process environment, using the same name in both places (e.g. ``KONG_ADMIN_URL``).
Settings win so a project can pin a value regardless of what the deploy injects.
"""
import os
from typing import Optional

from django.conf import settings


def resolve_config(name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Resolve a Kong configuration value.

    Looks up ``name`` in Django settings first, then in the environment. Values
    that are empty or whitespace-only count as unset, so a placeholder left
    behind by a deploy template falls through instead of taking effect.

    Args:
        name: Configuration name, shared by the setting and the env var.
        default: Value returned when neither source provides one.

    Returns:
        The resolved value stripped of surrounding whitespace, or ``default``.
    """
    for value in (getattr(settings, name, None), os.environ.get(name)):
        if value is None:
            continue

        value = str(value).strip()
        if value:
            return value

    return default


def kong_service_name(url_prefix: str) -> str:
    """
    Derive the Kong service name from a gateway URL prefix.

    ``/flows`` becomes ``flows-service``. The prefix must be a single path
    segment: ``/foo/bar`` cannot map to one service name without guessing.

    Args:
        url_prefix: Gateway path prefix, such as ``/flows``.

    Returns:
        The Kong service name, ``{segment}-service``.

    Raises:
        ValueError: if the prefix is empty or has more than one segment.
    """
    slug = (url_prefix or "").strip().strip("/")
    if not slug:
        raise ValueError(
            "cannot derive Kong service name from an empty KONG_URL_PREFIX"
        )
    if "/" in slug:
        raise ValueError(
            "KONG_URL_PREFIX must be a single path segment such as /flows "
            f"(got {url_prefix!r})"
        )
    return f"{slug}-service"


def resolved_kong_service(service: Optional[str], url_prefix: str) -> str:
    """Return ``service`` if set, otherwise derive it from ``url_prefix``."""
    name = (service or "").strip()
    if name:
        return name
    return kong_service_name(url_prefix)
