"""Tests for WeniAuthContext access semantics."""

from django.test import TestCase
from rest_framework.exceptions import PermissionDenied, ValidationError

from weni_commons.auth import WeniAuthContext


class WeniAuthContextTestCase(TestCase):
    def test_project_uuid_returns_value_when_present(self):
        context = WeniAuthContext(project_uuid="project-123")

        self.assertEqual(context.project_uuid, "project-123")
        self.assertTrue(context.has_project_uuid)

    def test_project_uuid_raises_when_absent(self):
        context = WeniAuthContext(vtex_account="mystore")

        self.assertFalse(context.has_project_uuid)
        with self.assertRaises(PermissionDenied):
            _ = context.project_uuid

    def test_vtex_account_returns_value_when_present(self):
        context = WeniAuthContext(vtex_account="mystore")

        self.assertEqual(context.vtex_account, "mystore")
        self.assertTrue(context.has_vtex_account)

    def test_vtex_account_raises_when_absent(self):
        context = WeniAuthContext(project_uuid="project-123")

        self.assertFalse(context.has_vtex_account)
        with self.assertRaises(PermissionDenied):
            _ = context.vtex_account

    def test_account_id_returns_value_when_present(self):
        context = WeniAuthContext(project_uuid="p", account_id="acc-123")

        self.assertEqual(context.account_id, "acc-123")
        self.assertTrue(context.has_account_id)

    def test_account_id_raises_validation_error_when_absent(self):
        context = WeniAuthContext(project_uuid="p")

        self.assertFalse(context.has_account_id)
        with self.assertRaises(ValidationError):
            _ = context.account_id

    def test_account_id_is_optional_and_independent_of_tenant(self):
        context = WeniAuthContext(vtex_account="mystore")

        self.assertTrue(context.has_vtex_account)
        self.assertFalse(context.has_account_id)

    def test_token_type_flags(self):
        jwt_context = WeniAuthContext(project_uuid="p", token_type="jwt")
        keycloak_context = WeniAuthContext(project_uuid="p", token_type="keycloak")

        self.assertTrue(jwt_context.is_jwt)
        self.assertFalse(jwt_context.is_keycloak)
        self.assertTrue(keycloak_context.is_keycloak)
        self.assertFalse(keycloak_context.is_jwt)

    def test_identity_only_context_has_no_tenant(self):
        context = WeniAuthContext(user_email="user@example.com", token_type="keycloak")

        self.assertFalse(context.has_project_uuid)
        self.assertFalse(context.has_vtex_account)
        self.assertEqual(context.user_email, "user@example.com")
