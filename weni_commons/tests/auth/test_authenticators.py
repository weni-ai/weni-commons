"""
Tests for WeniAuthentication.
"""

import jwt
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from weni_commons.auth.authenticators import WeniAuthentication
from weni_commons.auth.context import WeniAuthContext, WeniAuthUser
from weni_commons.auth import WENI_AUTH_HEADER
from tests.backends import TestOIDCAuthenticationBackend

User = get_user_model()


class WeniAuthenticationTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.auth = WeniAuthentication()
        self.mock_public_key = b"test-public-key"
        self.user = User.objects.create_user(
            username="keycloak-user",
            email="keycloak@example.com",
            password="password",
        )
        TestOIDCAuthenticationBackend.user = self.user
        TestOIDCAuthenticationBackend.claims = {
            "email": "keycloak@example.com",
            "project_uuid": "project-from-keycloak",
            "vtex_account": "store-from-keycloak",
            "can_communicate_internally": True,
        }
        TestOIDCAuthenticationBackend.should_fail = False

    def _request_with_token(self, token: str, *, header: str = "Authorization"):
        request = self.factory.get("/")
        if header == WENI_AUTH_HEADER:
            request.headers = {WENI_AUTH_HEADER: token}
        else:
            request.headers = {"Authorization": f"Bearer {token}"}
        return request

    def test_returns_none_when_authorization_header_is_missing(self):
        request = self.factory.get("/")
        request.headers = {}

        self.assertIsNone(self.auth.authenticate(request))

    @override_settings(JWT_PUBLIC_KEY=b"test-public-key")
    @patch("weni_commons.auth.authenticators.jwt.decode")
    def test_authenticates_jwt_from_x_weni_auth_header(self, mock_jwt_decode):
        mock_jwt_decode.return_value = {
            "project_uuid": "project-123",
            "vtex_account": "mystore",
            "user_email": "user@example.com",
        }

        user, auth_context = self.auth.authenticate(
            self._request_with_token("app-io-jwt", header=WENI_AUTH_HEADER)
        )

        self.assertIsInstance(user, WeniAuthUser)
        self.assertEqual(auth_context.vtex_account, "mystore")

    @override_settings(JWT_PUBLIC_KEY=b"test-public-key")
    @patch("weni_commons.auth.authenticators.jwt.decode")
    def test_authenticates_valid_jwt_with_project_uuid(self, mock_jwt_decode):
        payload = {
            "project_uuid": "project-123",
            "user_email": "user@example.com",
            "vtex_account": "mystore",
        }
        mock_jwt_decode.return_value = payload

        user, auth_context = self.auth.authenticate(
            self._request_with_token("valid-jwt-token")
        )

        self.assertIsInstance(user, WeniAuthUser)
        self.assertEqual(user.email, "user@example.com")
        self.assertEqual(auth_context.project_uuid, "project-123")
        self.assertEqual(auth_context.vtex_account, "mystore")
        self.assertEqual(auth_context.user_email, "user@example.com")
        self.assertFalse(auth_context.is_internal)
        self.assertEqual(auth_context.token_type, "jwt")

    @override_settings(JWT_PUBLIC_KEY=b"test-public-key")
    @patch("weni_commons.auth.authenticators.jwt.decode")
    def test_authenticates_valid_jwt_with_vtex_account_only(self, mock_jwt_decode):
        mock_jwt_decode.return_value = {
            "vtex_account": "mystore",
            "email": "user@example.com",
        }

        _, auth_context = self.auth.authenticate(self._request_with_token("valid-jwt"))

        self.assertFalse(auth_context.has_project_uuid)
        self.assertEqual(auth_context.vtex_account, "mystore")
        self.assertEqual(auth_context.user_email, "user@example.com")

    @override_settings(JWT_PUBLIC_KEY=b"test-public-key")
    @patch("weni_commons.auth.authenticators.jwt.decode")
    def test_jwt_populates_account_id_when_present(self, mock_jwt_decode):
        mock_jwt_decode.return_value = {
            "vtex_account": "mystore",
            "account_id": "acc-123",
        }

        _, auth_context = self.auth.authenticate(self._request_with_token("jwt"))

        self.assertTrue(auth_context.has_account_id)
        self.assertEqual(auth_context.account_id, "acc-123")

    @override_settings(JWT_PUBLIC_KEY=b"test-public-key")
    @patch("weni_commons.auth.authenticators.jwt.decode")
    def test_jwt_without_account_id_does_not_affect_tenant_validation(
        self, mock_jwt_decode
    ):
        mock_jwt_decode.return_value = {"vtex_account": "mystore"}

        _, auth_context = self.auth.authenticate(self._request_with_token("jwt"))

        self.assertEqual(auth_context.vtex_account, "mystore")
        self.assertFalse(auth_context.has_account_id)

    @override_settings(JWT_PUBLIC_KEY=b"test-public-key")
    @patch("weni_commons.auth.authenticators.jwt.decode")
    def test_jwt_can_set_internal_caller_when_claim_is_present(self, mock_jwt_decode):
        mock_jwt_decode.return_value = {
            "project_uuid": "project-123",
            "can_communicate_internally": True,
        }

        _, auth_context = self.auth.authenticate(self._request_with_token("internal-jwt"))

        self.assertTrue(auth_context.is_internal)
        self.assertEqual(auth_context.token_type, "jwt")

    @override_settings(JWT_PUBLIC_KEY=b"test-public-key")
    @patch("weni_commons.auth.authenticators.jwt.decode")
    def test_raises_when_jwt_has_no_project_or_vtex_account(self, mock_jwt_decode):
        mock_jwt_decode.return_value = {"user_email": "user@example.com"}

        with self.assertRaises(AuthenticationFailed) as context:
            self.auth.authenticate(self._request_with_token("invalid-payload"))

        self.assertIn("project_uuid", str(context.exception))

    @override_settings(JWT_PUBLIC_KEY=b"test-public-key")
    @patch("weni_commons.auth.authenticators.jwt.decode")
    def test_raises_when_jwt_is_expired(self, mock_jwt_decode):
        mock_jwt_decode.side_effect = jwt.ExpiredSignatureError("expired")

        with self.assertRaises(AuthenticationFailed) as context:
            self.auth.authenticate(self._request_with_token("expired-jwt"))

        self.assertIn("expired", str(context.exception).lower())

    @override_settings(JWT_PUBLIC_KEY=b"test-public-key")
    @patch("weni_commons.auth.authenticators.jwt.decode")
    def test_falls_back_to_keycloak_when_jwt_signature_is_invalid(
        self, mock_jwt_decode
    ):
        mock_jwt_decode.side_effect = jwt.InvalidTokenError("invalid signature")

        user, auth_context = self.auth.authenticate(
            self._request_with_token("keycloak-token")
        )

        self.assertEqual(user, self.user)
        self.assertEqual(auth_context.token_type, "keycloak")
        self.assertEqual(auth_context.project_uuid, "project-from-keycloak")
        self.assertEqual(auth_context.vtex_account, "store-from-keycloak")
        self.assertEqual(auth_context.user_email, "keycloak@example.com")
        self.assertTrue(auth_context.is_internal)

    @override_settings(JWT_PUBLIC_KEY=None, OIDC_DRF_AUTH_BACKEND=None)
    def test_raises_when_keycloak_is_not_configured(self):
        auth = WeniAuthentication()

        with self.assertRaises(AuthenticationFailed) as context:
            auth.authenticate(self._request_with_token("opaque-token"))

        self.assertIn("OIDC_DRF_AUTH_BACKEND", str(context.exception))

    @override_settings(JWT_PUBLIC_KEY=None)
    def test_raises_when_keycloak_token_is_invalid(self):
        TestOIDCAuthenticationBackend.should_fail = True

        with self.assertRaises(AuthenticationFailed) as context:
            self.auth.authenticate(self._request_with_token("bad-keycloak-token"))

        self.assertIn("Invalid token", str(context.exception))

    @override_settings(JWT_PUBLIC_KEY=b"test-public-key")
    @patch("weni_commons.auth.authenticators.jwt.decode")
    def test_accepts_raw_token_without_bearer_prefix(self, mock_jwt_decode):
        mock_jwt_decode.return_value = {
            "project_uuid": "project-123",
            "user_email": "user@example.com",
        }

        request = self.factory.get("/")
        request.headers = {"Authorization": "raw-token"}

        _, auth_context = self.auth.authenticate(request)

        self.assertEqual(auth_context.project_uuid, "project-123")

    @override_settings(JWT_PUBLIC_KEY=None)
    def test_keycloak_resolves_tenant_from_request_when_claims_absent(self):
        TestOIDCAuthenticationBackend.claims = {"email": "keycloak@example.com"}

        request = self.factory.get(
            "/?projectUuid=proj-from-query&vtex_account=store-from-query"
        )
        request.headers = {"Authorization": "Bearer keycloak-token"}

        _, auth_context = self.auth.authenticate(request)

        self.assertEqual(auth_context.token_type, "keycloak")
        self.assertEqual(auth_context.project_uuid, "proj-from-query")
        self.assertEqual(auth_context.vtex_account, "store-from-query")

    @override_settings(JWT_PUBLIC_KEY=None)
    def test_keycloak_claims_take_precedence_over_request(self):
        TestOIDCAuthenticationBackend.claims = {
            "email": "keycloak@example.com",
            "project_uuid": "proj-from-token",
        }

        request = self.factory.get("/?project_uuid=proj-from-query")
        request.headers = {"Authorization": "Bearer keycloak-token"}

        _, auth_context = self.auth.authenticate(request)

        self.assertEqual(auth_context.project_uuid, "proj-from-token")

    @override_settings(JWT_PUBLIC_KEY=None)
    def test_keycloak_resolves_account_id_from_claims_only(self):
        TestOIDCAuthenticationBackend.claims = {
            "email": "keycloak@example.com",
            "account_id": "acc-from-token",
        }

        request = self.factory.get("/?account_id=acc-from-request")
        request.headers = {"Authorization": "Bearer keycloak-token"}

        _, auth_context = self.auth.authenticate(request)

        self.assertEqual(auth_context.account_id, "acc-from-token")

    @override_settings(JWT_PUBLIC_KEY=None)
    def test_keycloak_account_id_absent_when_not_in_claims(self):
        TestOIDCAuthenticationBackend.claims = {"email": "keycloak@example.com"}

        request = self.factory.get("/?account_id=acc-from-request")
        request.headers = {"Authorization": "Bearer keycloak-token"}

        _, auth_context = self.auth.authenticate(request)

        self.assertFalse(auth_context.has_account_id)

    @override_settings(JWT_PUBLIC_KEY=b"test-public-key")
    @patch("weni_commons.auth.authenticators.jwt.decode")
    def test_jwt_tenant_is_immutable_and_ignores_request_values(
        self, mock_jwt_decode
    ):
        mock_jwt_decode.return_value = {"project_uuid": "project-from-token"}

        request = self.factory.get("/?project_uuid=project-from-request")
        request.headers = {WENI_AUTH_HEADER: "app-io-jwt"}

        _, auth_context = self.auth.authenticate(request)

        self.assertEqual(auth_context.token_type, "jwt")
        self.assertEqual(auth_context.project_uuid, "project-from-token")

    def test_uses_injected_oidc_backend(self):
        backend = MagicMock()
        backend.get_or_create_user.return_value = self.user
        backend.verify_token.return_value = {"email": "injected@example.com"}

        auth = WeniAuthentication(oidc_backend=backend)

        with override_settings(JWT_PUBLIC_KEY=None):
            user, auth_context = auth.authenticate(
                self._request_with_token("keycloak-token")
            )

        backend.get_or_create_user.assert_called_once()
        self.assertEqual(user, self.user)
        self.assertEqual(auth_context.user_email, "injected@example.com")
