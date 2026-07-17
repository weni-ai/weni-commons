import json
from unittest.mock import MagicMock, patch

import pytest
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from weni_commons.auth import (
    SessionContext,
    SessionTokenAuthentication,
    SessionUser,
    extract_bearer_token,
)


class ProtectedView(APIView):
    authentication_classes = [SessionTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "projeto": request.auth.projeto,
                "user": request.user.email,
            }
        )


class FallbackView(APIView):
    class DummyJWTAuthentication:
        def authenticate(self, request):
            header = request.META.get("HTTP_AUTHORIZATION", "")
            if header == "Bearer jwt-token":
                return (SessionUser(email="jwt@example.com"), "jwt-auth")
            return None

    authentication_classes = [SessionTokenAuthentication, DummyJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"user": request.user.email, "auth": request.auth})


@pytest.fixture
def factory():
    return APIRequestFactory()


@pytest.fixture
def valid_payload():
    return {
        "projeto": "project-uuid",
        "user": "user@example.com",
        "expire_at": "2026-06-10T12:00:00+00:00",
    }


def test_extract_bearer_token():
    request = APIRequestFactory().get(
        "/",
        HTTP_AUTHORIZATION="Bearer session-hash",
    )
    assert extract_bearer_token(request) == "session-hash"


def test_extract_bearer_token_returns_none_for_other_schemes():
    request = APIRequestFactory().get(
        "/",
        HTTP_AUTHORIZATION="ExternalAuth token",
    )
    assert extract_bearer_token(request) is None


@patch("weni_commons.auth.authentication.ValidateSessionTokenUseCase")
def test_authenticate_returns_none_when_token_is_invalid(mock_use_case_cls):
    mock_use_case_cls.return_value.execute.return_value = None
    request = APIRequestFactory().get(
        "/",
        HTTP_AUTHORIZATION="Bearer invalid-hash",
    )

    result = SessionTokenAuthentication().authenticate(request)

    assert result is None


@patch("weni_commons.auth.authentication.ValidateSessionTokenUseCase")
def test_authenticate_returns_user_and_session(mock_use_case_cls, valid_payload):
    session = SessionContext(**valid_payload)
    mock_use_case_cls.return_value.execute.return_value = session
    request = APIRequestFactory().get(
        "/",
        HTTP_AUTHORIZATION="Bearer valid-hash",
    )

    user, auth = SessionTokenAuthentication().authenticate(request)

    assert isinstance(user, SessionUser)
    assert user.email == "user@example.com"
    assert auth == session


@patch("weni_commons.auth.authentication.ValidateSessionTokenUseCase")
def test_valid_session_token_authenticates_view(mock_use_case_cls, factory, valid_payload):
    mock_use_case_cls.return_value.execute.return_value = SessionContext(**valid_payload)

    request = factory.get(
        "/contacts",
        HTTP_AUTHORIZATION="Bearer valid-hash",
    )
    response = ProtectedView.as_view()(request)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["projeto"] == "project-uuid"
    assert response.data["user"] == "user@example.com"


def test_missing_authorization_is_not_authenticated(factory):
    request = factory.get("/contacts")
    response = ProtectedView.as_view()(request)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@patch("weni_commons.auth.authentication.ValidateSessionTokenUseCase")
def test_invalid_hash_falls_back_to_next_authenticator(
    mock_use_case_cls, factory
):
    mock_use_case_cls.return_value.execute.return_value = None

    request = factory.get(
        "/contacts",
        HTTP_AUTHORIZATION="Bearer jwt-token",
    )
    response = FallbackView.as_view()(request)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["user"] == "jwt@example.com"
    assert response.data["auth"] == "jwt-auth"


@patch("weni_commons.auth.session.get_redis_connection")
def test_end_to_end_with_redis_payload(mock_get_redis, factory, valid_payload):
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(valid_payload).encode("utf-8")
    mock_get_redis.return_value = mock_redis

    request = factory.get(
        "/contacts",
        HTTP_AUTHORIZATION="Bearer valid-hash",
    )
    response = ProtectedView.as_view()(request)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["user"] == "user@example.com"
