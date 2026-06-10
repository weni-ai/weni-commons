import json
from unittest.mock import MagicMock, patch

import pytest
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from weni_commons.auth import require_session_token


class SampleView(APIView):
    def get(self, request):
        return Response(
            {
                "projeto": request.weni_session.projeto,
                "user": request.weni_session.user,
            }
        )


@require_session_token
class ProtectedView(SampleView):
    pass


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


@patch("weni_commons.auth.decorators.ValidateSessionTokenUseCase")
def test_valid_bearer_token_returns_200(mock_use_case_cls, factory, valid_payload):
    mock_use_case_cls.return_value.execute.return_value = type(
        "SessionContext",
        (),
        valid_payload,
    )()

    request = factory.get(
        "/contacts",
        HTTP_AUTHORIZATION="Bearer valid-hash",
    )
    response = ProtectedView.as_view()(request)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["projeto"] == "project-uuid"
    assert response.data["user"] == "user@example.com"
    mock_use_case_cls.return_value.execute.assert_called_once_with("valid-hash")


def test_missing_authorization_header_returns_403(factory):
    request = factory.get("/contacts")
    response = ProtectedView.as_view()(request)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["detail"] == "Invalid or expired session token."


@patch("weni_commons.auth.decorators.ValidateSessionTokenUseCase")
def test_invalid_hash_returns_403(mock_use_case_cls, factory):
    mock_use_case_cls.return_value.execute.return_value = None

    request = factory.get(
        "/contacts",
        HTTP_AUTHORIZATION="Bearer invalid-hash",
    )
    response = ProtectedView.as_view()(request)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_wrong_auth_scheme_returns_403(factory):
    request = factory.get(
        "/contacts",
        HTTP_AUTHORIZATION="ExternalAuth some-token",
    )
    response = ProtectedView.as_view()(request)

    assert response.status_code == status.HTTP_403_FORBIDDEN


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
