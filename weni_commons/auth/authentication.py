from typing import Optional

from rest_framework import HTTP_HEADER_ENCODING
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from weni_commons.auth.session import ValidateSessionTokenUseCase


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
    DRF authentication backend for Connect session hashes stored in Redis.

    Expects Authorization: Bearer <hash>. Returns None when the token is missing,
    invalid, or expired so other authentication classes can run afterward.
    """

    www_authenticate_realm = "api"

    def authenticate(self, request):
        token_hash = extract_bearer_token(request)
        if not token_hash:
            return None

        session = ValidateSessionTokenUseCase().execute(token_hash)
        if session is None:
            return None

        return (SessionUser(email=session.user), session)

    def authenticate_header(self, request):
        return 'Bearer realm="api"'
