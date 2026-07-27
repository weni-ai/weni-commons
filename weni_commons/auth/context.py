from typing import Any, Dict, Optional

from rest_framework.exceptions import PermissionDenied, ValidationError

TOKEN_TYPE_JWT = "jwt"
TOKEN_TYPE_KEYCLOAK = "keycloak"


class WeniAuthContext:
    """Authentication context exposed via ``request.auth`` in DRF views.

    Tenant scope is resolved once, at authentication time: from the signed token
    for JWT callers (which must carry at least one of ``project_uuid`` /
    ``vtex_account``), or from the standardized request locations for Keycloak
    callers (where a missing tenant is allowed — identity-only access).

    Accessing :attr:`project_uuid` or :attr:`vtex_account` means the field is
    **required in that context**: it returns the value or raises
    ``PermissionDenied`` (HTTP 403) when absent, because they define the
    tenant/authorization scope. Use :attr:`has_project_uuid` /
    :attr:`has_vtex_account` for optional checks that must not raise.

    :attr:`account_id` is an **optional** identity claim (not tenant scope):
    only some routes require it. Accessing it means the route requires it, so it
    returns the value or raises ``ValidationError`` (HTTP 400) when absent — a
    malformed request for that endpoint, not an authorization failure. Use
    :attr:`has_account_id` for optional checks that must not raise.

    Attributes:
        user_email: Email of the authenticated principal. Read from the token,
            except for internal Keycloak callers (service-to-service), whose
            token holds the service account — for those, it is the acting user
            resolved from the request.
        is_internal: ``True`` for service-to-service (internal) callers.
        token_type: Either ``"jwt"`` or ``"keycloak"``.
        raw_payload: The raw decoded claims, kept for advanced use cases.
    """

    __slots__ = (
        "_project_uuid",
        "_vtex_account",
        "_account_id",
        "user_email",
        "is_internal",
        "token_type",
        "raw_payload",
    )

    def __init__(
        self,
        project_uuid: Optional[str] = None,
        vtex_account: Optional[str] = None,
        user_email: Optional[str] = None,
        is_internal: bool = False,
        token_type: str = TOKEN_TYPE_JWT,
        raw_payload: Optional[Dict[str, Any]] = None,
        account_id: Optional[str] = None,
    ):
        """Initialize the context.

        Args:
            project_uuid: Resolved project identifier, or ``None``.
            vtex_account: Resolved VTEX account identifier, or ``None``.
            user_email: Email of the authenticated principal, when available.
            is_internal: Whether the caller is an internal service.
            token_type: The token type, ``"jwt"`` or ``"keycloak"``.
            raw_payload: The raw decoded claims.
            account_id: Optional account identity claim from the token, or
                ``None`` when the token does not carry it.
        """
        self._project_uuid = project_uuid
        self._vtex_account = vtex_account
        self._account_id = account_id
        self.user_email = user_email
        self.is_internal = is_internal
        self.token_type = token_type
        self.raw_payload = raw_payload

    @property
    def project_uuid(self) -> str:
        """Return the project UUID, raising when it was not provided.

        Returns:
            The resolved project UUID.

        Raises:
            PermissionDenied: When no project UUID is available in this context.
        """
        if not self._project_uuid:
            raise PermissionDenied(
                "project_uuid could not be resolved from the request."
            )
        return self._project_uuid

    @property
    def vtex_account(self) -> str:
        """Return the VTEX account, raising when it was not provided.

        Returns:
            The resolved VTEX account.

        Raises:
            PermissionDenied: When no VTEX account is available in this context.
        """
        if not self._vtex_account:
            raise PermissionDenied(
                "vtex_account could not be resolved from the request."
            )
        return self._vtex_account

    @property
    def has_project_uuid(self) -> bool:
        """Report whether a project UUID is available without raising.

        Returns:
            ``True`` when a project UUID was resolved, otherwise ``False``.
        """
        return bool(self._project_uuid)

    @property
    def has_vtex_account(self) -> bool:
        """Report whether a VTEX account is available without raising.

        Returns:
            ``True`` when a VTEX account was resolved, otherwise ``False``.
        """
        return bool(self._vtex_account)

    @property
    def account_id(self) -> str:
        """Return the account id, raising when the route requires it but it is absent.

        Unlike tenant fields, a missing ``account_id`` is a malformed request
        for the endpoint that requires it, not an authorization failure — hence
        ``ValidationError`` (HTTP 400) instead of ``PermissionDenied``.

        Returns:
            The account id carried by the token.

        Raises:
            ValidationError: When no account id is available in this context.
        """
        if not self._account_id:
            raise ValidationError(
                {"account_id": "account_id is required for this request."}
            )
        return self._account_id

    @property
    def has_account_id(self) -> bool:
        """Report whether an account id is available without raising.

        Returns:
            ``True`` when an account id was resolved, otherwise ``False``.
        """
        return bool(self._account_id)

    @property
    def is_jwt(self) -> bool:
        """Report whether the request was authenticated with a Weni JWT.

        Returns:
            ``True`` when ``token_type`` is ``"jwt"``, otherwise ``False``.
        """
        return self.token_type == TOKEN_TYPE_JWT

    @property
    def is_keycloak(self) -> bool:
        """Report whether the request was authenticated with Keycloak.

        Returns:
            ``True`` when ``token_type`` is ``"keycloak"``, otherwise ``False``.
        """
        return self.token_type == TOKEN_TYPE_KEYCLOAK


class WeniAuthUser:
    """Lightweight authenticated principal for JWT-based module communication.

    Used as ``request.user`` for JWT callers, where no Django user exists. It
    satisfies the minimal interface DRF and permission classes expect from an
    authenticated user.

    Attributes:
        is_authenticated: Always ``True``.
        is_anonymous: Always ``False``.
        is_active: Always ``True``.
        email: Email of the JWT principal, when present in the token.
    """

    is_authenticated = True
    is_anonymous = False
    is_active = True

    def __init__(self, email: Optional[str] = None):
        """Initialize the principal.

        Args:
            email: Email extracted from the JWT payload, when available.
        """
        self.email = email

    def __str__(self) -> str:
        """Return a human-readable identifier for logs and admin.

        Returns:
            The principal's email, or a stable placeholder when unset.
        """
        return self.email or "weni-auth-user"
