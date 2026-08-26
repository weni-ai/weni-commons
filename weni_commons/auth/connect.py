import logging
from typing import Optional

import requests
from django.conf import settings
<<<<<<< HEAD
from rest_framework.permissions import BasePermission
=======
>>>>>>> feat/weni-openapi-plugin

from weni_commons.auth.constants import CONNECT_AUTHORIZATION_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class ConnectAuthorizationClient:
    """
    Client for Connect project authorization checks.

    Calls ``GET {WENI_CONNECT_API_URL}/v2/projects/{project_uuid}/authorization``
    forwarding the caller's Authorization header (same contract as weni-cli-backend).
    """

    def __init__(
        self,
        authorization_header: str,
        project_uuid: str,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.authorization_header = authorization_header
        self.project_uuid = project_uuid
        self.base_url = (base_url or getattr(settings, "WENI_CONNECT_API_URL", "") or "").rstrip(
            "/"
        )
        self.timeout = (
            timeout
            if timeout is not None
            else getattr(
                settings,
                "WENI_CONNECT_AUTHORIZATION_TIMEOUT",
                CONNECT_AUTHORIZATION_TIMEOUT_SECONDS,
            )
        )

    def get_project_authorization(self) -> Optional[int]:
        """
        Return the project role int from Connect, or ``None`` on any failure.
        """
        if not self.base_url or not self.project_uuid or not self.authorization_header:
            return None

        url = f"{self.base_url}/v2/projects/{self.project_uuid}/authorization"
        headers = {"Authorization": self.authorization_header}

        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
        except requests.exceptions.RequestException:
            logger.exception(
                "Connect authorization request failed (project_uuid=%s)",
                self.project_uuid,
            )
            return None

        if response.status_code != 200:
            logger.warning(
                "Connect authorization returned %s (project_uuid=%s)",
                response.status_code,
                self.project_uuid,
            )
            return None

        try:
            payload = response.json()
        except ValueError:
            logger.warning(
                "Connect authorization returned invalid JSON (project_uuid=%s)",
                self.project_uuid,
            )
            return None

        if not isinstance(payload, dict) or "project_authorization" not in payload:
            return None

        role = payload["project_authorization"]
        try:
            return int(role)
        except (TypeError, ValueError):
            return None
<<<<<<< HEAD


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
=======
>>>>>>> feat/weni-openapi-plugin
