from functools import wraps
from typing import Any, Optional, Type

from rest_framework import HTTP_HEADER_ENCODING
from rest_framework.authentication import get_authorization_header
from rest_framework.response import Response
from rest_framework.views import APIView

from weni_commons.auth.session import ValidateSessionTokenUseCase

FORBIDDEN_RESPONSE = Response(
    {"detail": "Invalid or expired session token."},
    status=403,
)


def _extract_bearer_token(request) -> Optional[str]:
    header = get_authorization_header(request)

    if not header:
        return None

    header = header.decode(HTTP_HEADER_ENCODING)
    auth = header.split()

    if len(auth) != 2 or auth[0].lower() != "bearer":
        return None

    token_hash = auth[1].strip()
    return token_hash or None


def require_session_token(view_cls: Type[APIView]) -> Type[APIView]:
    """
    Protect a DRF APIView by validating a session hash from Redis.

    Expects: Authorization: Bearer <hash>

    On success, attaches request.weni_session with projeto, user, and expire_at.
    On failure, returns 403 Forbidden before the view handler runs.
    """
    if not isinstance(view_cls, type) or not issubclass(view_cls, APIView):
        raise TypeError("require_session_token can only be applied to APIView subclasses")

    original_dispatch = view_cls.dispatch

    @wraps(original_dispatch)
    def dispatch(self, request, *args, **kwargs):
        token_hash = _extract_bearer_token(request)
        session = ValidateSessionTokenUseCase().execute(token_hash)

        if session is None:
            return FORBIDDEN_RESPONSE

        request.weni_session = session
        return original_dispatch(self, request, *args, **kwargs)

    view_cls.dispatch = dispatch
    return view_cls
