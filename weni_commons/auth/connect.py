import logging
from typing import Optional

import requests
from django.conf import settings

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
