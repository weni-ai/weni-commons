import logging
from typing import Optional

from rest_framework import HTTP_HEADER_ENCODING
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from weni_commons.auth.session import ValidateSessionTokenUseCase

logger = logging.getLogger(__name__)


def extract_bearer_token(request) -> Optional[str]:
    header = get_authorization_header(request)

    if not header:
        return None

    header = header.decode(HTTP_HEADER_ENCODING)
    auth = header.split()

    if len(auth) != 2 or auth[0].lower() != "bearer":
        return None

    token_hash = auth[1].strip()
    return token_hash or None


class SessionUser:
    is_authenticated = True
    is_anonymous = False

    def __init__(self, email: str) -> None:
        self.email = email

    def __str__(self) -> str:
        return self.email


class SessionTokenAuthentication(BaseAuthentication):
    """
    DRF authentication backend for Connect session hashes stored in Redis/DynamoDB.

    Expects Authorization: Bearer <hash>. Returns None when the token is missing,
    invalid, expired, or when the store lookup fails, so other authentication
    classes can run afterward.

    On success, sets ``request.project_uuid`` from the session and returns a
    ``SessionUser``. Org/project membership checks belong in permission classes.
    """

    www_authenticate_realm = "api"

    def authenticate(self, request):
        token_hash = extract_bearer_token(request)
        if not token_hash:
            return None

        try:
            session = ValidateSessionTokenUseCase().execute(token_hash)
        except Exception:
            # DynamoDB/Redis misconfig must not take down the API with a 500.
            logger.exception("Session token validation failed for Bearer token")
            return None

        if session is None:
            return None

        if session.project:
            request.project_uuid = session.project

        return (SessionUser(email=session.user), session)

    def authenticate_header(self, request):
        return 'Bearer realm="api"'
