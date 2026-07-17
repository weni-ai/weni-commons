from typing import Any, Optional

from weni_commons.auth.context import WeniAuthContext
from weni_commons.auth.resolvers import (
    resolve_project_uuid_from_request,
    resolve_vtex_account_from_request,
)


def get_auth_context(request: Any) -> Optional[WeniAuthContext]:
    """Return the authenticated context placed on ``request.auth`` by DRF.

    This is **not** an HTTP header. ``WeniAuthentication`` decodes the token
    from ``X-Weni-Auth`` or ``Authorization`` and stores a ``WeniAuthContext``
    on ``request.auth`` before the view runs.

    Args:
        request: The DRF request whose ``auth`` attribute is inspected.

    Returns:
        The :class:`~weni_commons.auth.context.WeniAuthContext` set by the
        authenticator, or ``None`` when the request was not authenticated by
        ``WeniAuthentication``.
    """
    auth = getattr(request, "auth", None)
    if isinstance(auth, WeniAuthContext):
        return auth
    return None


def get_project_uuid(request: Any) -> Optional[str]:
    """Resolve the project UUID for the request.

    The value is always read from the auth context, which was populated at
    authentication time — from the token for JWT callers, or from the
    standardized request locations for Keycloak callers. When the request was
    not authenticated by ``WeniAuthentication``, it resolves directly from the
    request as a fallback.

    Args:
        request: The DRF request.

    Returns:
        The project UUID, or ``None`` when it cannot be resolved.
    """
    auth = get_auth_context(request)
    if auth is not None:
        return auth.project_uuid if auth.has_project_uuid else None
    return resolve_project_uuid_from_request(request)


def get_vtex_account(request: Any) -> Optional[str]:
    """Resolve the VTEX account for the request.

    The value is always read from the auth context — never from a spoofable
    request attribute — so JWT callers get the immutable claim from the token
    and Keycloak callers get the value resolved from the standardized request
    locations. When the request was not authenticated by ``WeniAuthentication``,
    it resolves directly from the request as a fallback.

    Args:
        request: The DRF request.

    Returns:
        The VTEX account, or ``None`` when it cannot be resolved.
    """
    auth = get_auth_context(request)
    if auth is not None:
        return auth.vtex_account if auth.has_vtex_account else None
    return resolve_vtex_account_from_request(request)


def get_account_id(request: Any) -> Optional[str]:
    """Resolve the optional account id for the request.

    The account id is an identity claim read only from the auth context (it is
    never resolved from the request body/params, to avoid spoofing). Returns
    ``None`` when absent instead of raising, unlike ``auth.account_id``.

    Args:
        request: The DRF request.

    Returns:
        The account id, or ``None`` when it is not available.
    """
    auth = get_auth_context(request)
    if auth is not None and auth.has_account_id:
        return auth.account_id
    return None


def get_user_email(request: Any) -> Optional[str]:
    """Resolve the authenticated user's email.

    Args:
        request: The DRF request.

    Returns:
        The email from the auth context when present, otherwise the email of
        the authenticated Django user, or ``None``.
    """
    auth = get_auth_context(request)
    if auth and auth.user_email:
        return auth.user_email

    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        return getattr(user, "email", None)
    return None


def is_internal_request(request: Any) -> bool:
    """Report whether the request comes from an internal (service) caller.

    Args:
        request: The DRF request.

    Returns:
        ``True`` when the auth context is marked internal, or when the
        authenticated Django user holds the ``can_communicate_internally``
        permission. Otherwise ``False``.
    """
    auth = get_auth_context(request)
    if auth:
        return auth.is_internal

    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return False

    return user.user_permissions.filter(
        codename="can_communicate_internally"
    ).exists()
