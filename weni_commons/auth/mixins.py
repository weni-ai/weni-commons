from typing import Optional

from rest_framework.exceptions import PermissionDenied

from weni_commons.auth.context import WeniAuthContext
from weni_commons.auth.helpers import (
    get_auth_context,
    get_user_email,
    is_internal_request,
)
from weni_commons.auth.permissions import IsWeniAuthenticated


class WeniAuthViewMixin:
    """Unified auth mixin for JWT and Keycloak callers.

    ``WeniAuthentication`` always populates ``request.auth`` with a
    ``WeniAuthContext``, resolving tenant scope (``project_uuid`` /
    ``vtex_account``) at authentication time — from the token for JWT callers,
    or from the standardized request locations for Keycloak callers.

    Views MUST read tenant scope exclusively from the context, never from the
    serializer or the raw request, so every endpoint stays consistent.
    Accessing a tenant field means it is required in that context: it returns
    the value or raises ``403`` when absent. Use the ``has_*`` flags for
    optional access::

        class MyView(WeniAuthViewMixin, APIView):
            authentication_classes = [WeniAuthentication]

            def post(self, request):
                vtex_account = self.auth.vtex_account       # 403 if missing
                if self.auth.has_project_uuid:              # optional
                    project_uuid = self.auth.project_uuid
                email = self.user_email
    """

    permission_classes = [IsWeniAuthenticated]

    @property
    def auth(self) -> WeniAuthContext:
        """Authenticated context from ``request.auth``.

        Returns:
            The :class:`~weni_commons.auth.context.WeniAuthContext` for the
            current request.

        Raises:
            PermissionDenied: When the request has no auth context (the view was
                reached without ``WeniAuthentication``).
        """
        auth = get_auth_context(self.request)
        if auth is None:
            raise PermissionDenied("Authentication context is required.")
        return auth

    @property
    def is_jwt(self) -> bool:
        """Report whether the current request was authenticated with a JWT.

        Returns:
            ``True`` for JWT callers, otherwise ``False``.
        """
        return self.auth.is_jwt

    @property
    def is_keycloak(self) -> bool:
        """Report whether the current request was authenticated with Keycloak.

        Returns:
            ``True`` for Keycloak callers, otherwise ``False``.
        """
        return self.auth.is_keycloak

    @property
    def user_email(self) -> Optional[str]:
        """Return the authenticated user's email.

        Returns:
            The email resolved from the auth context or Django user, or
            ``None`` when unavailable.
        """
        return get_user_email(self.request)

    @property
    def is_internal(self) -> bool:
        """Report whether the current request is an internal service caller.

        Returns:
            ``True`` for internal callers, otherwise ``False``.
        """
        return is_internal_request(self.request)
