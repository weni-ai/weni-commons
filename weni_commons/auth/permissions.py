from enum import IntEnum
from typing import Optional

from rest_framework import permissions
from rest_framework.request import Request

from weni_commons.auth.connect import ConnectAuthorizationClient
from weni_commons.auth.context import WeniAuthContext
from weni_commons.auth.interfaces import UserPermissionsServiceInterface
from weni_commons.auth.token import extract_token


class PermissionLevel(IntEnum):
    """Project authorization levels returned by the permissions service."""

    not_configured = 0
    viewer = 1
    contributor = 2
    moderator = 3
    support = 4
    chat_user = 5


class IsWeniAuthenticated(permissions.BasePermission):
    """Grants access when ``WeniAuthentication`` populated ``request.auth``."""

    def has_permission(self, request: Request, view) -> bool:
        """Check that the request carries a Weni auth context.

        Args:
            request: The DRF request.
            view: The view being accessed (unused).

        Returns:
            ``True`` when ``request.auth`` is a ``WeniAuthContext``.
        """
        return isinstance(request.auth, WeniAuthContext)


class CanCommunicateInternally(permissions.BasePermission):
    """Grants access to internal service-to-service callers."""

    def has_permission(self, request: Request, view) -> bool:
        """Check that the caller is an internal service.

        JWT callers are represented by
        :class:`~weni_commons.auth.context.WeniAuthUser`, a lightweight
        principal with no Django permissions, so for them the decision relies
        solely on the internal claim carried by the token.

        Args:
            request: The DRF request.
            view: The view being accessed (unused).

        Returns:
            ``True`` when the auth context is internal or the Django user holds
            the ``can_communicate_internally`` permission, otherwise ``False``.
        """
        auth = request.auth
        if isinstance(auth, WeniAuthContext) and auth.is_internal:
            return True

        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False

        if not hasattr(user, "user_permissions"):
            return False

        return user.user_permissions.filter(
            codename="can_communicate_internally"
        ).exists()


class HasProjectPermission(permissions.BasePermission):
    """
    Verifies contributor or moderator access to the project in ``request.auth``.

    Internal callers must provide ``user_email`` via query string.
    Regular callers are validated against the injected permissions service.
    """

    ALLOWED_LEVELS = (
        PermissionLevel.contributor,
        PermissionLevel.moderator,
    )

    def __init__(
        self,
        permissions_service: Optional[UserPermissionsServiceInterface] = None,
    ):
        """Initialize the permission with an optional permissions service.

        Args:
            permissions_service: Service used to resolve project-level
                permissions. When ``None``, access is always denied.
        """
        self.permissions_service = permissions_service

    def has_permission(self, request: Request, view) -> bool:
        """Check that the caller has contributor or moderator access.

        Args:
            request: The DRF request.
            view: The view being accessed (unused).

        Returns:
            ``True`` when the caller's authorization level is allowed for the
            resolved project, otherwise ``False``.
        """
        auth = request.auth
        if not isinstance(auth, WeniAuthContext):
            return False

        if not auth.has_project_uuid:
            return False
        project_uuid = auth.project_uuid

        if self.permissions_service is None:
            return False

        if auth.is_internal:
            return self._has_internal_permission(request, project_uuid)

        return self._has_user_permission(request, auth, project_uuid)

    def _has_internal_permission(self, request: Request, project_uuid: str) -> bool:
        """Check permission for an internal caller impersonating a user.

        Args:
            request: The DRF request; ``user_email`` is read from the query
                string.
            project_uuid: The project being accessed.

        Returns:
            ``True`` when the impersonated user's level is allowed, otherwise
            ``False``.
        """
        user_email = request.query_params.get("user_email")
        if not user_email:
            return False

        status_code, response = self.permissions_service.get_user_permissions(
            project_uuid,
            user_email,
        )
        return self._is_allowed_response(status_code, response)

    def _has_user_permission(
        self,
        request: Request,
        auth: WeniAuthContext,
        project_uuid: str,
    ) -> bool:
        """Check permission for a regular authenticated user.

        Args:
            request: The DRF request.
            auth: The authenticated context for the request.
            project_uuid: The project being accessed.

        Returns:
            ``True`` when the user's level is allowed for the project, otherwise
            ``False``.
        """
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False

        user_email = auth.user_email or getattr(user, "email", None)
        if not user_email:
            return False

        user_token = extract_token(request)
        if not user_token:
            return False

        status_code, response = self.permissions_service.get_user_permissions(
            project_uuid,
            user_email,
            user_token,
        )
        return self._is_allowed_response(status_code, response)

    def _is_allowed_response(self, status_code: int, response: dict) -> bool:
        """Evaluate the permissions service response against allowed levels.

        Args:
            status_code: HTTP status returned by the permissions service.
            response: Parsed response body; ``project_authorization`` holds the
                level.

        Returns:
            ``True`` when the status is ``200`` and the authorization level is
            in :attr:`ALLOWED_LEVELS`, otherwise ``False``.
        """
        if status_code != 200:
            return False

        project_authorization = response.get("project_authorization")
        return project_authorization in self.ALLOWED_LEVELS


class ConnectProjectAuthorization(permissions.BasePermission):
    """
    Abstract DRF permission that resolves the caller's project role via Connect.

    Host apps subclass and implement ``has_required_role`` to decide access.
    Expects ``request.project_uuid`` (from SessionTokenAuthentication) and an
    ``Authorization`` header to forward to Connect.
    """

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False

        project_uuid = getattr(request, "project_uuid", None)
        authorization_header = self._get_authorization_header(request)

        if not project_uuid or not authorization_header:
            return False

        role = self.fetch_project_role(authorization_header, project_uuid)
        if role is None:
            return False

        request.project_authorization = role
        return self.has_required_role(request, view, role)

    def fetch_project_role(
        self, authorization_header: str, project_uuid: str
    ) -> Optional[int]:
        return ConnectAuthorizationClient(
            authorization_header, project_uuid
        ).get_project_authorization()

    def has_required_role(self, request, view, role: int) -> bool:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement has_required_role()"
        )

    @staticmethod
    def _get_authorization_header(request) -> Optional[str]:
        header = request.META.get("HTTP_AUTHORIZATION")
        if not header:
            return None
        if isinstance(header, bytes):
            header = header.decode("iso-8859-1")
        header = header.strip()
        return header or None
