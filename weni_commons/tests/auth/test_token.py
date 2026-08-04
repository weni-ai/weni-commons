"""Tests for HTTP token extraction."""

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from weni_commons.auth import WENI_AUTH_HEADER, extract_token


class ExtractTokenTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_returns_token_from_x_weni_auth_header(self):
        request = self.factory.get("/")
        request.headers = {WENI_AUTH_HEADER: "app-io-jwt-token"}

        self.assertEqual(extract_token(request), "app-io-jwt-token")

    def test_prefers_x_weni_auth_over_authorization(self):
        request = self.factory.get("/")
        request.headers = {
            WENI_AUTH_HEADER: "app-io-jwt-token",
            "Authorization": "Bearer keycloak-token",
        }

        self.assertEqual(extract_token(request), "app-io-jwt-token")

    def test_returns_bearer_token_from_authorization_header(self):
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer keycloak-token"}

        self.assertEqual(extract_token(request), "keycloak-token")

    def test_returns_none_when_no_supported_header_is_present(self):
        request = self.factory.get("/")
        request.headers = {}

        self.assertIsNone(extract_token(request))
