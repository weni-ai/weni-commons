from unittest.mock import MagicMock, patch

import pytest
import requests
from rest_framework.test import APIRequestFactory

from weni_commons.auth import ConnectAuthorizationClient, ConnectProjectAuthorization
from weni_commons.auth.authentication import SessionUser


class AllowRoles(ConnectProjectAuthorization):
    allowed_roles = {2, 3, 4}

    def has_required_role(self, request, view, role):
        return role in self.allowed_roles


@pytest.fixture
def factory():
    return APIRequestFactory()


@pytest.fixture
def authenticated_request(factory):
    request = factory.get("/", HTTP_AUTHORIZATION="Bearer session-hash")
    request.user = SessionUser(email="user@example.com")
    request.project_uuid = "project-uuid"
    return request


@patch.object(ConnectAuthorizationClient, "get_project_authorization", return_value=3)
def test_permission_allows_when_role_is_accepted(mock_get_role, authenticated_request):
    permission = AllowRoles()

    assert permission.has_permission(authenticated_request, view=None) is True
    assert authenticated_request.project_authorization == 3
    mock_get_role.assert_called_once()


@patch.object(ConnectAuthorizationClient, "get_project_authorization", return_value=1)
def test_permission_denies_when_role_is_not_accepted(mock_get_role, authenticated_request):
    permission = AllowRoles()

    assert permission.has_permission(authenticated_request, view=None) is False
    assert authenticated_request.project_authorization == 1
    mock_get_role.assert_called_once()


@patch.object(ConnectAuthorizationClient, "get_project_authorization")
def test_permission_denies_without_project_uuid(mock_get_role, factory):
    request = factory.get("/", HTTP_AUTHORIZATION="Bearer session-hash")
    request.user = SessionUser(email="user@example.com")

    assert AllowRoles().has_permission(request, view=None) is False
    mock_get_role.assert_not_called()


@patch.object(ConnectAuthorizationClient, "get_project_authorization")
def test_permission_denies_without_authorization_header(mock_get_role, factory):
    request = factory.get("/")
    request.user = SessionUser(email="user@example.com")
    request.project_uuid = "project-uuid"

    assert AllowRoles().has_permission(request, view=None) is False
    mock_get_role.assert_not_called()


@patch.object(ConnectAuthorizationClient, "get_project_authorization")
def test_permission_denies_unauthenticated_user(mock_get_role, factory):
    request = factory.get("/", HTTP_AUTHORIZATION="Bearer session-hash")
    request.user = MagicMock(is_authenticated=False)
    request.project_uuid = "project-uuid"

    assert AllowRoles().has_permission(request, view=None) is False
    mock_get_role.assert_not_called()


@patch.object(ConnectAuthorizationClient, "get_project_authorization", return_value=None)
def test_permission_denies_when_connect_returns_none(mock_get_role, authenticated_request):
    assert AllowRoles().has_permission(authenticated_request, view=None) is False
    mock_get_role.assert_called_once()
    assert not hasattr(authenticated_request, "project_authorization")


def test_abstract_has_required_role_raises(authenticated_request):
    with patch.object(
        ConnectAuthorizationClient, "get_project_authorization", return_value=2
    ):
        with pytest.raises(NotImplementedError):
            ConnectProjectAuthorization().has_permission(
                authenticated_request, view=None
            )


@patch("weni_commons.auth.connect.requests.get")
def test_client_returns_role_on_success(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"project_authorization": 2}
    mock_get.return_value = mock_response

    client = ConnectAuthorizationClient(
        "Bearer session-hash",
        "project-uuid",
        base_url="https://connect.example.com",
    )

    assert client.get_project_authorization() == 2
    mock_get.assert_called_once_with(
        "https://connect.example.com/v2/projects/project-uuid/authorization",
        headers={"Authorization": "Bearer session-hash"},
        timeout=5,
    )


@patch("weni_commons.auth.connect.requests.get")
def test_client_returns_none_on_non_200(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_get.return_value = mock_response

    client = ConnectAuthorizationClient(
        "Bearer session-hash",
        "project-uuid",
        base_url="https://connect.example.com",
    )

    assert client.get_project_authorization() is None


@patch("weni_commons.auth.connect.requests.get")
def test_client_returns_none_on_network_error(mock_get):
    mock_get.side_effect = requests.exceptions.ConnectionError("down")

    client = ConnectAuthorizationClient(
        "Bearer session-hash",
        "project-uuid",
        base_url="https://connect.example.com",
    )

    assert client.get_project_authorization() is None


@patch("weni_commons.auth.connect.requests.get")
def test_client_returns_none_when_role_key_missing(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"valid": True}
    mock_get.return_value = mock_response

    client = ConnectAuthorizationClient(
        "Bearer session-hash",
        "project-uuid",
        base_url="https://connect.example.com",
    )

    assert client.get_project_authorization() is None


def test_client_returns_none_without_base_url():
    client = ConnectAuthorizationClient(
        "Bearer session-hash",
        "project-uuid",
        base_url="",
    )

    assert client.get_project_authorization() is None
