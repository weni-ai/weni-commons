import logging
from typing import Optional

from rest_framework.permissions import BasePermission

from weni_commons.auth.connect import ConnectAuthorizationClient

logger = logging.getLogger(__name__)


class ConnectProjectAuthorization(BasePermission):
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
