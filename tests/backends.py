from typing import Any, Dict, Optional


class TestOIDCAuthenticationBackend:
    """Minimal OIDC backend used by the weni-commons test suite."""

    claims: Dict[str, Any] = {}
    user: Any = None
    should_fail: bool = False

    def get_or_create_user(
        self,
        access_token: str,
        id_token: Optional[str],
        payload: Optional[dict],
    ):
        if self.should_fail:
            raise ValueError("invalid keycloak token")

        return self.user

    def verify_token(self, token: str) -> Dict[str, Any]:
        return self.claims
