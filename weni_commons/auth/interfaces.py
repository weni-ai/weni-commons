from typing import Dict, Optional, Protocol, Tuple


class UserPermissionsServiceInterface(Protocol):
    """Contract for services that resolve project-level user permissions."""

    def get_user_permissions(
        self,
        project_uuid: str,
        user_email: str,
        user_token: Optional[str] = None,
    ) -> Tuple[int, Dict]:
        """Resolve a user's authorization level for a project.

        Args:
            project_uuid: The project to check permissions against.
            user_email: The email of the user whose permissions are resolved.
            user_token: Optional user token, forwarded when the caller is the
                user itself rather than an internal service.

        Returns:
            A ``(status_code, body)`` tuple, where ``body`` holds
            ``project_authorization`` with the user's level.
        """
        ...
