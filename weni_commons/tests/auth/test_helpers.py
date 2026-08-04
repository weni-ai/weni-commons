"""Tests for auth helper utilities."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import TestCase

from weni_commons.auth import (
    WeniAuthContext,
    get_account_id,
    get_project_uuid,
    get_user_email,
    get_vtex_account,
    is_internal_request,
)


def _request_with_auth(**auth_kwargs):
    request = MagicMock()
    request.auth = WeniAuthContext(**auth_kwargs)
    return request


class GetTenantFromContextTestCase(TestCase):
    def test_returns_project_uuid_from_context(self):
        request = _request_with_auth(project_uuid="project-123")

        self.assertEqual(get_project_uuid(request), "project-123")

    def test_returns_vtex_account_from_context(self):
        request = _request_with_auth(vtex_account="mystore", token_type="keycloak")

        self.assertEqual(get_vtex_account(request), "mystore")

    def test_returns_none_when_field_absent_without_raising(self):
        request = _request_with_auth(project_uuid="project-1", token_type="jwt")

        self.assertIsNone(get_vtex_account(request))

    def test_does_not_fall_back_to_request_attribute(self):
        request = MagicMock()
        request.auth = WeniAuthContext(project_uuid="project-1", token_type="jwt")
        request.vtex_account = "spoofed-store"

        self.assertIsNone(get_vtex_account(request))

    def test_falls_back_to_request_resolution_without_auth_context(self):
        request = MagicMock()
        request.auth = None
        request.resolver_match = None
        request.query_params = {"project_uuid": "proj-from-query"}
        request.headers = {}

        self.assertEqual(get_project_uuid(request), "proj-from-query")

    def test_vtex_account_falls_back_to_request_resolution(self):
        request = MagicMock()
        request.auth = None
        request.resolver_match = None
        request.query_params = {"vtex_account": "store-from-query"}
        request.headers = {}

        self.assertEqual(get_vtex_account(request), "store-from-query")

    def test_returns_account_id_from_context(self):
        request = _request_with_auth(project_uuid="p-1", account_id="acc-1")

        self.assertEqual(get_account_id(request), "acc-1")

    def test_account_id_returns_none_when_absent(self):
        request = _request_with_auth(project_uuid="p-1")

        self.assertIsNone(get_account_id(request))

    def test_account_id_returns_none_without_auth_context(self):
        request = MagicMock()
        request.auth = None

        self.assertIsNone(get_account_id(request))


class GetUserEmailTestCase(TestCase):
    def test_returns_email_from_auth_context(self):
        request = _request_with_auth(
            project_uuid="p-1", user_email="ctx@example.com"
        )

        self.assertEqual(get_user_email(request), "ctx@example.com")

    def test_falls_back_to_django_user_email(self):
        request = SimpleNamespace(
            auth=None,
            user=SimpleNamespace(is_authenticated=True, email="user@example.com"),
        )

        self.assertEqual(get_user_email(request), "user@example.com")

    def test_returns_none_when_user_is_anonymous(self):
        request = SimpleNamespace(
            auth=None, user=SimpleNamespace(is_authenticated=False)
        )

        self.assertIsNone(get_user_email(request))


class IsInternalRequestTestCase(TestCase):
    def test_true_from_internal_auth_context(self):
        request = _request_with_auth(
            project_uuid="p-1", is_internal=True, token_type="keycloak"
        )

        self.assertTrue(is_internal_request(request))

    def test_false_when_anonymous_user_and_no_context(self):
        request = SimpleNamespace(
            auth=None, user=SimpleNamespace(is_authenticated=False)
        )

        self.assertFalse(is_internal_request(request))

    def test_reads_django_permission_when_no_context(self):
        user = MagicMock()
        user.is_authenticated = True
        user.user_permissions.filter.return_value.exists.return_value = True
        request = SimpleNamespace(auth=None, user=user)

        self.assertTrue(is_internal_request(request))
        user.user_permissions.filter.assert_called_once_with(
            codename="can_communicate_internally"
        )
