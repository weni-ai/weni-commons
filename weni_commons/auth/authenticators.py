import logging
from typing import Any, Dict, Optional, Tuple

import jwt
from django.conf import settings
from django.utils.module_loading import import_string
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from weni_commons.auth.constants import (
    INTERNAL_CALLER_CLAIMS,
    JWT_ALGORITHMS,
    JWT_DECODE_OPTIONS,
    KEYCLOAK_ACCOUNT_ID_CLAIMS,
    KEYCLOAK_EMAIL_CLAIMS,
    KEYCLOAK_PROJECT_UUID_CLAIMS,
    KEYCLOAK_VTEX_ACCOUNT_CLAIMS,
)
from weni_commons.auth.context import (
    TOKEN_TYPE_JWT,
    TOKEN_TYPE_KEYCLOAK,
    WeniAuthContext,
    WeniAuthUser,
)
from weni_commons.auth.resolvers import (
    resolve_project_uuid_from_request,
    resolve_vtex_account_from_request,
)
from weni_commons.auth.token import extract_token

logger = logging.getLogger(__name__)


class WeniAuthentication(BaseAuthentication):
    """Unified DRF authentication for Weni backends.

    The class accepts two token formats through a single entry point and
    resolves them in order:

    1. **JWT** — App IO / inter-module tokens signed with ``JWT_PUBLIC_KEY``.
       Tenant claims (``project_uuid``, ``vtex_account``) are read from the
       signed payload only (immutable, never from request data) and the token
       must carry at least one of them or authentication fails.
    2. **Keycloak (OIDC)** — used as a fallback when the token is not a valid
       Weni JWT. Identity is resolved by the OIDC backend, while tenant scope
       is resolved by the library from the token claims and, when absent, from
       the standardized request locations (URL, query, headers, body). A
       missing tenant is allowed here — it becomes identity-only access.

    Both flows populate ``request.auth`` with a
    :class:`~weni_commons.auth.context.WeniAuthContext`::

        request.auth.user_email
        request.auth.is_internal
        request.auth.token_type   # "jwt" or "keycloak"
        request.auth.project_uuid  # raises 403 when not resolved
        request.auth.vtex_account  # raises 403 when not resolved

    Attributes:
        _oidc_backend: Optional pre-built OIDC backend instance. When ``None``,
            the backend is resolved lazily from ``OIDC_DRF_AUTH_BACKEND``.
    """

    def __init__(self, oidc_backend: Any = None):
        """Initialize the authenticator.

        Args:
            oidc_backend: Optional OIDC backend instance used for the Keycloak
                fallback. Injected mainly for testing; production callers
                normally leave it ``None`` so the backend is loaded from
                ``settings.OIDC_DRF_AUTH_BACKEND``.
        """
        self._oidc_backend = oidc_backend

    def authenticate(self, request: Request) -> Optional[Tuple[Any, WeniAuthContext]]:
        """Authenticate a request using the JWT-first, Keycloak-fallback flow.

        Args:
            request: The incoming DRF request.

        Returns:
            A ``(user, auth_context)`` tuple when a token is present and valid,
            where ``auth_context`` is a
            :class:`~weni_commons.auth.context.WeniAuthContext`. Returns
            ``None`` when no token is supplied, letting DRF try the next
            authenticator.

        Raises:
            AuthenticationFailed: When a token is present but invalid, expired,
                or missing required claims.
        """
        token = extract_token(request)
        if not token:
            return None

        jwt_context = self._try_jwt_authentication(token)
        if jwt_context is not None:
            return WeniAuthUser(email=jwt_context.user_email), jwt_context

        return self._authenticate_with_keycloak(request, token)

    def _try_jwt_authentication(self, token: str) -> Optional[WeniAuthContext]:
        """Attempt to validate the token as a Weni JWT.

        Args:
            token: The raw token extracted from the request headers.

        Returns:
            A :class:`~weni_commons.auth.context.WeniAuthContext` when the token
            is a valid Weni JWT. Returns ``None`` when ``JWT_PUBLIC_KEY`` is not
            configured or the token is not a Weni JWT, signalling the caller to
            fall back to Keycloak.

        Raises:
            AuthenticationFailed: When the token is a Weni JWT but expired, or
                when it is valid yet missing required tenant claims.
        """
        public_key = getattr(settings, "JWT_PUBLIC_KEY", None)
        if not public_key:
            return None

        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=JWT_ALGORITHMS,
                options=JWT_DECODE_OPTIONS,
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationFailed("Token expired.") from exc
        except jwt.InvalidTokenError:
            return None

        return self._build_jwt_auth_context(payload)

    def _build_jwt_auth_context(self, payload: Dict[str, Any]) -> WeniAuthContext:
        """Build the auth context from a decoded JWT payload.

        Args:
            payload: The decoded and verified JWT claims.

        Returns:
            A :class:`~weni_commons.auth.context.WeniAuthContext` populated with
            the token's tenant claims and identity.

        Raises:
            AuthenticationFailed: When neither ``project_uuid`` nor
                ``vtex_account`` is present in the payload.
        """
        project_uuid = payload.get("project_uuid")
        vtex_account = payload.get("vtex_account")
        user_email = payload.get("user_email") or payload.get("email")

        if not project_uuid and not vtex_account:
            raise AuthenticationFailed(
                "Token must contain 'project_uuid' or 'vtex_account'."
            )

        return WeniAuthContext(
            project_uuid=project_uuid,
            vtex_account=vtex_account,
            user_email=user_email,
            is_internal=self._has_internal_caller_claim(payload),
            token_type=TOKEN_TYPE_JWT,
            raw_payload=payload,
            account_id=payload.get("account_id"),
        )

    def _authenticate_with_keycloak(
        self, request: Request, token: str
    ) -> Tuple[Any, WeniAuthContext]:
        """Authenticate the token against the Keycloak OIDC backend.

        Args:
            request: The incoming request, used to resolve tenant scope from
                its standardized locations.
            token: The raw token that was not recognized as a Weni JWT.

        Returns:
            A ``(user, auth_context)`` tuple, where ``user`` is the Django user
            resolved by the OIDC backend and ``auth_context`` is a
            :class:`~weni_commons.auth.context.WeniAuthContext` of type
            ``keycloak``.

        Raises:
            AuthenticationFailed: When the OIDC backend rejects the token or
                cannot resolve a user.
        """
        backend = self._get_oidc_backend()
        try:
            user = backend.get_or_create_user(token, None, None)
        except Exception as exc:
            logger.debug(f"Keycloak authentication failed: {exc}")
            raise AuthenticationFailed("Invalid token.") from exc

        if user is None:
            raise AuthenticationFailed("Invalid token.")

        claims = self._extract_keycloak_claims(token, backend, user)
        auth_context = self._build_keycloak_auth_context(request, user, claims)

        return user, auth_context

    def _get_oidc_backend(self) -> Any:
        """Return the OIDC backend, injected or loaded from settings.

        Returns:
            The OIDC backend instance to use for Keycloak authentication.

        Raises:
            AuthenticationFailed: When no backend was injected and
                ``OIDC_DRF_AUTH_BACKEND`` is not configured in Django settings.
        """
        if self._oidc_backend is not None:
            return self._oidc_backend

        backend_path = getattr(settings, "OIDC_DRF_AUTH_BACKEND", None)
        if not backend_path:
            raise AuthenticationFailed(
                "OIDC_DRF_AUTH_BACKEND is not configured in Django settings."
            )

        backend_class = import_string(backend_path)
        return backend_class()

    def _extract_keycloak_claims(
        self, token: str, backend: Any, user: Any
    ) -> Dict[str, Any]:
        """Resolve the claims for a Keycloak-authenticated request.

        Claims are resolved in a best-effort order: the backend's
        ``verify_token`` first, then an unverified decode of the token, and
        finally the fields already present on the Django user.

        Args:
            token: The raw Keycloak token.
            backend: The OIDC backend that authenticated the token.
            user: The Django user resolved by the backend.

        Returns:
            A dictionary of claims. Never empty — it falls back to the user's
            email and username when no claims can be decoded.
        """
        claims: Dict[str, Any] = {}

        verify_token = getattr(backend, "verify_token", None)
        if callable(verify_token):
            try:
                claims = verify_token(token) or {}
            except Exception:
                claims = {}

        if not claims:
            claims = self._decode_keycloak_token_without_verification(token)

        if not claims:
            claims = {
                "email": getattr(user, "email", None),
                "preferred_username": getattr(user, "username", None),
            }

        return claims

    def _decode_keycloak_token_without_verification(self, token: str) -> Dict[str, Any]:
        """Decode a Keycloak token without verifying its signature.

        Used only to read claims after the backend has already authenticated
        the user, so signature verification is intentionally skipped.

        Args:
            token: The raw Keycloak token.

        Returns:
            The decoded claims, or an empty dictionary when the token cannot be
            parsed.
        """
        try:
            return jwt.decode(
                token,
                options={"verify_signature": False, "verify_aud": False},
                algorithms=["HS256", "RS256"],
            )
        except jwt.InvalidTokenError:
            return {}

    def _build_keycloak_auth_context(
        self, request: Request, user: Any, claims: Dict[str, Any]
    ) -> WeniAuthContext:
        """Build the auth context for a Keycloak-authenticated request.

        Tenant scope is resolved from the token claims first and, when absent,
        from the request's standardized locations (URL, query, headers, body).
        The optional ``account_id`` identity claim is resolved from the token
        claims only — never from the request — to avoid spoofing.

        Args:
            request: The incoming request, used to resolve tenant scope.
            user: The Django user resolved by the OIDC backend.
            claims: The claims resolved for the request.

        Returns:
            A :class:`~weni_commons.auth.context.WeniAuthContext` of type
            ``keycloak``. Tenant fields may be ``None`` when neither the token
            nor the request carries them.
        """
        user_email = (
            self._first_claim_value(claims, KEYCLOAK_EMAIL_CLAIMS)
            or getattr(user, "email", None)
        )
        project_uuid = (
            self._first_claim_value(claims, KEYCLOAK_PROJECT_UUID_CLAIMS)
            or resolve_project_uuid_from_request(request)
        )
        vtex_account = (
            self._first_claim_value(claims, KEYCLOAK_VTEX_ACCOUNT_CLAIMS)
            or resolve_vtex_account_from_request(request)
        )
        is_internal = self._has_internal_caller_claim(claims)

        if not is_internal and hasattr(user, "user_permissions"):
            is_internal = user.user_permissions.filter(
                codename="can_communicate_internally"
            ).exists()

        return WeniAuthContext(
            project_uuid=project_uuid,
            vtex_account=vtex_account,
            user_email=user_email,
            is_internal=is_internal,
            token_type=TOKEN_TYPE_KEYCLOAK,
            raw_payload=claims or None,
            account_id=self._first_claim_value(claims, KEYCLOAK_ACCOUNT_ID_CLAIMS),
        )

    @staticmethod
    def _first_claim_value(claims: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[str]:
        """Return the first truthy claim value among a set of candidate keys.

        Args:
            claims: The claims dictionary to search.
            keys: Candidate claim names, tried in order.

        Returns:
            The first non-empty value coerced to ``str``, or ``None`` when no
            candidate key holds a value.
        """
        for key in keys:
            value = claims.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _has_internal_caller_claim(claims: Dict[str, Any]) -> bool:
        """Report whether the claims mark a service-to-service caller.

        Args:
            claims: The claims dictionary to inspect.

        Returns:
            ``True`` when any internal-caller claim is present and truthy,
            otherwise ``False``.
        """
        return any(bool(claims.get(claim)) for claim in INTERNAL_CALLER_CLAIMS)
