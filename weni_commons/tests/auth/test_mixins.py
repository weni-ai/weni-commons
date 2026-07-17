"""Tests for WeniAuthViewMixin."""

from uuid import uuid4

from django.test import TestCase
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from weni_commons.auth import WeniAuthContext, WeniAuthViewMixin


class _ExampleView(WeniAuthViewMixin, APIView):
    authentication_classes = []
    permission_classes = []


class WeniAuthViewMixinTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = _ExampleView()

    def _bind(self, *, token_type="jwt", **auth_kwargs):
        request = self.factory.get("/")
        request.auth = WeniAuthContext(
            user_email="user@example.com",
            token_type=token_type,
            **auth_kwargs,
        )
        self.view.request = request

    def test_auth_exposes_context(self):
        self._bind(vtex_account="mystore")

        self.assertEqual(self.view.auth.vtex_account, "mystore")
        self.assertTrue(self.view.is_jwt)
        self.assertFalse(self.view.is_keycloak)

    def test_keycloak_flags(self):
        self._bind(token_type="keycloak")

        self.assertTrue(self.view.is_keycloak)
        self.assertFalse(self.view.is_jwt)

    def test_user_email_and_internal(self):
        self._bind(is_internal=True, vtex_account="mystore")

        self.assertEqual(self.view.user_email, "user@example.com")
        self.assertTrue(self.view.is_internal)

    def test_auth_project_uuid_from_jwt(self):
        project_uuid = str(uuid4())
        self._bind(project_uuid=project_uuid, vtex_account="mystore")

        self.assertEqual(self.view.auth.project_uuid, project_uuid)

    def test_auth_project_uuid_from_keycloak(self):
        project_uuid = str(uuid4())
        self._bind(token_type="keycloak", project_uuid=project_uuid)

        self.assertEqual(self.view.auth.project_uuid, project_uuid)

    def test_accessing_missing_tenant_raises(self):
        self._bind(project_uuid="project-1")

        with self.assertRaises(PermissionDenied):
            _ = self.view.auth.vtex_account

    def test_has_flag_allows_optional_access(self):
        self._bind(project_uuid="project-1")

        self.assertTrue(self.view.auth.has_project_uuid)
        self.assertFalse(self.view.auth.has_vtex_account)

    def test_auth_raises_without_context(self):
        self.view.request = self.factory.get("/")
        self.view.request.auth = None

        with self.assertRaises(PermissionDenied):
            _ = self.view.auth
