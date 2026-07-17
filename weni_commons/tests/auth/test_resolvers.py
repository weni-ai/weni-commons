"""Tests for standardized tenant resolution from the request."""

from types import SimpleNamespace

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from weni_commons.auth.resolvers import (
    resolve_project_uuid_from_request,
    resolve_vtex_account_from_request,
)

_UNSET = object()


def _fake_request(*, kwargs=None, query=None, headers=None, data=_UNSET):
    """Build a lightweight request-like object with full control per source."""
    request = SimpleNamespace()
    request.resolver_match = SimpleNamespace(kwargs=kwargs or {})
    request.query_params = query or {}
    request.headers = headers or {}
    if data is not _UNSET:
        request.data = data
    return request


class _BodyRaisingRequest:
    """Request-like object whose body access raises, to test the guard."""

    def __init__(self):
        self.resolver_match = SimpleNamespace(kwargs={})
        self.query_params = {}
        self.headers = {}

    @property
    def data(self):
        raise ValueError("cannot parse body")


class ResolveProjectUuidTestCase(TestCase):
    def test_resolves_from_url_kwargs(self):
        request = _fake_request(kwargs={"project_uuid": "proj-kwargs"})

        self.assertEqual(resolve_project_uuid_from_request(request), "proj-kwargs")

    def test_resolves_from_query_params_camel_case(self):
        request = _fake_request(query={"projectUuid": "proj-query"})

        self.assertEqual(resolve_project_uuid_from_request(request), "proj-query")

    def test_resolves_from_header_with_hyphen(self):
        request = _fake_request(headers={"Project-Uuid": "proj-header"})

        self.assertEqual(resolve_project_uuid_from_request(request), "proj-header")

    def test_resolves_from_body(self):
        request = _fake_request(data={"project": "proj-body"})

        self.assertEqual(resolve_project_uuid_from_request(request), "proj-body")

    def test_accepts_short_project_key(self):
        request = _fake_request(query={"project": "proj-short"})

        self.assertEqual(resolve_project_uuid_from_request(request), "proj-short")

    def test_precedence_kwargs_over_query_header_body(self):
        request = _fake_request(
            kwargs={"project_uuid": "from-kwargs"},
            query={"project_uuid": "from-query"},
            headers={"Project-Uuid": "from-header"},
            data={"project_uuid": "from-body"},
        )

        self.assertEqual(resolve_project_uuid_from_request(request), "from-kwargs")

    def test_precedence_query_over_header_and_body(self):
        request = _fake_request(
            query={"project_uuid": "from-query"},
            headers={"Project-Uuid": "from-header"},
            data={"project_uuid": "from-body"},
        )

        self.assertEqual(resolve_project_uuid_from_request(request), "from-query")

    def test_returns_none_when_absent(self):
        request = _fake_request(query={"unrelated": "value"})

        self.assertIsNone(resolve_project_uuid_from_request(request))

    def test_body_access_error_is_ignored(self):
        self.assertIsNone(resolve_project_uuid_from_request(_BodyRaisingRequest()))


class ResolveVtexAccountTestCase(TestCase):
    def test_resolves_from_query_params(self):
        request = _fake_request(query={"vtex_account": "store-1"})

        self.assertEqual(resolve_vtex_account_from_request(request), "store-1")

    def test_resolves_camel_case_variant(self):
        request = _fake_request(headers={"vtexAccount": "store-2"})

        self.assertEqual(resolve_vtex_account_from_request(request), "store-2")

    def test_returns_none_when_absent(self):
        request = _fake_request(query={"project_uuid": "proj-1"})

        self.assertIsNone(resolve_vtex_account_from_request(request))


class ResolveWithDjangoRequestTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_resolves_from_get_query_string(self):
        request = self.factory.get("/?projectUuid=proj-x&vtex_account=store-x")

        self.assertEqual(resolve_project_uuid_from_request(request), "proj-x")
        self.assertEqual(resolve_vtex_account_from_request(request), "store-x")
