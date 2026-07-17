"""Standardized multi-source resolution of tenant identifiers.

Keycloak requests do not carry tenant scope inside the token, so
``project_uuid`` and ``vtex_account`` must be resolved from the request itself.
To keep every endpoint consistent — and to let a future permission class check
project access in a uniform way — only a fixed set of key spellings is accepted,
searched across a fixed set of locations in a fixed order:

1. URL keyword arguments (``request.resolver_match.kwargs``)
2. Query parameters (``request.query_params`` / ``request.GET``)
3. Headers (``request.headers``)
4. Request body (``request.data``)

Keys are matched case-insensitively, ignoring ``-`` and ``_`` separators, so
``project_uuid``, ``project-uuid``, ``projectUuid`` and ``PROJECT_UUID`` all
match the same canonical key. Endpoints exposing these values under other names
must be refactored to one of the standard keys.
"""

from typing import Any, FrozenSet, Iterable, Optional

from weni_commons.auth.constants import (
    PROJECT_UUID_REQUEST_KEYS,
    VTEX_ACCOUNT_REQUEST_KEYS,
)


def _normalize(key: str) -> str:
    """Normalize a key for spelling-insensitive comparison.

    Args:
        key: The raw key name from a request source.

    Returns:
        The key lowercased with ``-`` and ``_`` separators removed.
    """
    return key.lower().replace("-", "").replace("_", "")


def _match_in_mapping(mapping: Any, targets: FrozenSet[str]) -> Optional[str]:
    """Return the first truthy value whose normalized key matches ``targets``.

    Args:
        mapping: A dict-like source (URL kwargs, query params, headers, body).
        targets: Normalized candidate keys to look for.

    Returns:
        The matched value coerced to ``str``, or ``None`` when the mapping is
        empty, not dict-like, or holds no matching key.
    """
    if not mapping:
        return None

    items = getattr(mapping, "items", None)
    if not callable(items):
        return None

    for key, value in items():
        if isinstance(key, str) and _normalize(key) in targets and value:
            return str(value)
    return None


def _match_in_body(request: Any, targets: FrozenSet[str]) -> Optional[str]:
    """Resolve a value from the request body, guarding against parse errors.

    Body access is wrapped defensively because reading ``request.data`` during
    authentication can raise for streamed or non-parseable payloads; in that
    case the body is simply treated as an unavailable source.

    Args:
        request: The incoming request.
        targets: Normalized candidate keys to look for.

    Returns:
        The matched value, or ``None`` when unavailable.
    """
    try:
        body = request.data
    except Exception:
        return None
    return _match_in_mapping(body, targets)


def resolve_from_request(request: Any, keys: Iterable[str]) -> Optional[str]:
    """Resolve a tenant field from the standardized request locations.

    Args:
        request: The incoming request (DRF ``Request`` or Django ``HttpRequest``).
        keys: Canonical candidate key spellings to accept.

    Returns:
        The first value found, searching URL kwargs, query params, headers and
        body in that order, or ``None`` when no source holds a matching key.
    """
    targets = frozenset(_normalize(key) for key in keys)

    resolver_match = getattr(request, "resolver_match", None)
    url_kwargs = getattr(resolver_match, "kwargs", None)

    query_params = getattr(request, "query_params", None)
    if query_params is None:
        query_params = getattr(request, "GET", None)

    headers = getattr(request, "headers", None)

    for source in (url_kwargs, query_params, headers):
        value = _match_in_mapping(source, targets)
        if value:
            return value

    return _match_in_body(request, targets)


def resolve_project_uuid_from_request(request: Any) -> Optional[str]:
    """Resolve ``project_uuid`` from the standardized request locations.

    Args:
        request: The incoming request.

    Returns:
        The project UUID, or ``None`` when it cannot be resolved.
    """
    return resolve_from_request(request, PROJECT_UUID_REQUEST_KEYS)


def resolve_vtex_account_from_request(request: Any) -> Optional[str]:
    """Resolve ``vtex_account`` from the standardized request locations.

    Args:
        request: The incoming request.

    Returns:
        The VTEX account, or ``None`` when it cannot be resolved.
    """
    return resolve_from_request(request, VTEX_ACCOUNT_REQUEST_KEYS)
