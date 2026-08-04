"""HTTP token extraction for Weni authentication."""

from typing import Any, Optional

WENI_AUTH_HEADER = "X-Weni-Auth"


def extract_token(request: Any) -> Optional[str]:
    """Extract an access token from incoming request headers.

    Checks headers in this order:

    1. ``X-Weni-Auth`` — App IO / inter-module Weni JWTs.
    2. ``Authorization`` — ``Bearer <token>`` or a raw token value. Used for
       Keycloak session tokens from browser clients.

    Args:
        request: DRF or Django request exposing ``request.headers``.

    Returns:
        The raw token string, or ``None`` when no supported header is present.
    """
    weni_token = request.headers.get(WENI_AUTH_HEADER, "").strip()
    if weni_token:
        return weni_token

    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        return None

    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]
    return auth_header
