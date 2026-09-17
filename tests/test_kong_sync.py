from io import StringIO
from unittest.mock import patch

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from weni_commons.kong import api_gateway_expose
from weni_commons.kong.sync import (
    PruneLimitExceeded,
    discover_routes,
    prune_routes,
    sync_to_kong,
)

ADMIN = "http://kong:8001"
PREFIX = "/flows"
SERVICE = "flows-service"
SERVICE_ID = "svc-flows"

EVENTS_PATHS = ["/events", "/flows/events", "/flows/api/v2/events.json"]
EVENTS_UPSTREAM = "/api/v2/events.json"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}", response=self)


class FakeKong:
    """Minimal Admin API double recording every call it receives."""

    def __init__(self, route_pages=None, plugin_pages=None, services=None):
        self.route_pages = route_pages if route_pages is not None else [[]]
        self.plugin_pages = plugin_pages if plugin_pages is not None else [[]]
        self.services = services if services is not None else {SERVICE: SERVICE_ID}
        self.calls = []

    def _collection(self, path, pages):
        offset = int(path.split("offset=")[1]) if "offset=" in path else 0
        base = path.split("?")[0]
        has_next = offset + 1 < len(pages)
        return {
            "data": pages[offset],
            "next": f"{base}?offset={offset + 1}" if has_next else None,
        }

    def get(self, url, timeout=None):
        self.calls.append(("GET", url))
        path = url[len(ADMIN):]

        if path.startswith("/routes?"):
            return FakeResponse(200, self._collection(path, self.route_pages))
        if path.startswith("/plugins?"):
            return FakeResponse(200, self._collection(path, self.plugin_pages))
        if path.startswith("/services/"):
            key = path[len("/services/"):]
            if key in self.services:
                return FakeResponse(200, {"id": self.services[key]})
            by_id = {v: k for k, v in self.services.items()}
            if key in by_id:
                return FakeResponse(200, {"name": by_id[key]})
            return FakeResponse(404)

        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        return FakeResponse(201, {"id": "new-route"})

    def patch(self, url, json=None, timeout=None):
        self.calls.append(("PATCH", url, json))
        return FakeResponse(200, {})

    def delete(self, url, timeout=None):
        self.calls.append(("DELETE", url))
        return FakeResponse(204)

    def methods(self, verb):
        return [call for call in self.calls if call[0] == verb]

    def writes(self):
        return [call for call in self.calls if call[0] in {"POST", "PATCH", "DELETE"}]


def discovered_route(**overrides):
    route = {
        "name": "allow-events",
        "paths": list(EVENTS_PATHS),
        "methods": ["GET"],
        "service": SERVICE,
        "strip_path": False,
        "upstream_uri": EVENTS_UPSTREAM,
        "rewrite_mode": "static_uri",
    }
    route.update(overrides)
    return route


def kong_route(**overrides):
    route = {
        "id": "route-events",
        "name": "allow-events",
        "paths": list(EVENTS_PATHS),
        "methods": ["GET"],
        "strip_path": False,
        "service": {"id": SERVICE_ID},
        "tags": ["kong-sync", "prefix-flows"],
    }
    route.update(overrides)
    return route


def kong_plugin(**overrides):
    plugin = {
        "id": "plugin-events",
        "name": "request-transformer",
        "config": {"replace": {"uri": EVENTS_UPSTREAM}},
        "route": {"id": "route-events"},
    }
    plugin.update(overrides)
    return plugin


@pytest.fixture(autouse=True)
def url_prefix(monkeypatch):
    monkeypatch.setenv("KONG_URL_PREFIX", PREFIX)


def run_sync(kong, routes, **kwargs):
    with patch("weni_commons.kong.sync.http", kong):
        return sync_to_kong(
            admin_url=ADMIN, service=SERVICE, routes=routes, **kwargs
        )


def test_paginates_routes_and_plugins():
    kong = FakeKong(
        route_pages=[[kong_route(name="allow-other", id="route-other")], [kong_route()]],
        plugin_pages=[[], [kong_plugin()]],
    )

    created, updated, skipped, deleted = run_sync(
        kong, [discovered_route()], prune=False
    )

    assert (created, updated, skipped, deleted) == ([], [], ["allow-events"], [])
    assert ("GET", f"{ADMIN}/routes?offset=1") in kong.calls
    assert ("GET", f"{ADMIN}/plugins?offset=1") in kong.calls


def test_route_in_sync_is_skipped():
    kong = FakeKong(route_pages=[[kong_route()]], plugin_pages=[[kong_plugin()]])

    created, updated, skipped, _ = run_sync(kong, [discovered_route()], prune=False)

    assert skipped == ["allow-events"]
    assert (created, updated) == ([], [])
    assert kong.writes() == []


def test_missing_route_is_created():
    kong = FakeKong()

    created, _, _, _ = run_sync(kong, [discovered_route()], prune=False)

    assert created == ["allow-events"]
    post_urls = [call[1] for call in kong.methods("POST")]
    assert f"{ADMIN}/services/{SERVICE}/routes" in post_urls
    assert f"{ADMIN}/routes/allow-events/plugins" in post_urls

    create_payload = kong.methods("POST")[0][2]
    assert create_payload["tags"] == ["kong-sync", "prefix-flows"]
    assert "service" not in create_payload


def test_methods_change_triggers_patch():
    kong = FakeKong(route_pages=[[kong_route()]], plugin_pages=[[kong_plugin()]])

    _, updated, _, _ = run_sync(
        kong, [discovered_route(methods=["GET", "POST"])], prune=False
    )

    assert updated == ["allow-events"]
    patched = kong.methods("PATCH")
    assert patched[0][1] == f"{ADMIN}/routes/allow-events"
    assert patched[0][2]["methods"] == ["GET", "POST"]


def test_paths_change_triggers_patch():
    kong = FakeKong(
        route_pages=[[kong_route(paths=["/events", "/flows/api/v1/events.json"])]],
        plugin_pages=[[kong_plugin()]],
    )

    _, updated, _, _ = run_sync(kong, [discovered_route()], prune=False)

    assert updated == ["allow-events"]
    assert kong.methods("PATCH")[0][2]["paths"] == EVENTS_PATHS


def test_missing_tags_trigger_patch():
    kong = FakeKong(
        route_pages=[[kong_route(tags=[])]], plugin_pages=[[kong_plugin()]]
    )

    _, updated, _, _ = run_sync(kong, [discovered_route()], prune=False)

    assert updated == ["allow-events"]
    assert kong.methods("PATCH")[0][2]["tags"] == ["kong-sync", "prefix-flows"]


def test_service_change_triggers_patch():
    kong = FakeKong(
        route_pages=[[kong_route(service={"id": "svc-nexus"})]],
        plugin_pages=[[kong_plugin()]],
        services={SERVICE: SERVICE_ID, "nexus-service": "svc-nexus"},
    )

    _, updated, _, _ = run_sync(kong, [discovered_route()], prune=False)

    assert updated == ["allow-events"]
    assert kong.methods("PATCH")[0][2]["service"] == {"name": SERVICE}


def test_divergent_plugin_is_patched_without_touching_route():
    stale = kong_plugin(config={"replace": {"uri": "/api/v1/events.json"}})
    kong = FakeKong(route_pages=[[kong_route()]], plugin_pages=[[stale]])

    _, updated, _, _ = run_sync(kong, [discovered_route()], prune=False)

    assert updated == ["allow-events"]
    patched = kong.methods("PATCH")
    assert len(patched) == 1
    assert patched[0][1] == f"{ADMIN}/plugins/plugin-events"
    assert patched[0][2]["config"]["replace"]["uri"] == EVENTS_UPSTREAM


def test_obsolete_plugin_is_removed_before_writing():
    obsolete = kong_plugin(
        id="plugin-pre",
        name="pre-function",
        config={"access": ["-- stale"]},
    )
    kong = FakeKong(
        route_pages=[[kong_route()]], plugin_pages=[[obsolete, kong_plugin()]]
    )

    _, updated, _, _ = run_sync(kong, [discovered_route()], prune=False)

    assert updated == ["allow-events"]
    assert ("DELETE", f"{ADMIN}/plugins/plugin-pre") in kong.calls
    # request-transformer already matched, so only the obsolete plugin is written.
    assert kong.methods("PATCH") == []


def test_dry_run_reports_plan_without_writing():
    kong = FakeKong()

    created, _, _, _ = run_sync(
        kong, [discovered_route()], prune=False, dry_run=True
    )

    assert created == ["allow-events"]
    assert kong.writes() == []


def test_prune_deletes_orphan_route():
    orphan = kong_route(name="allow-contacts", id="route-contacts")
    kong = FakeKong(
        route_pages=[[kong_route(), orphan]], plugin_pages=[[kong_plugin()]]
    )

    _, _, _, deleted = run_sync(kong, [discovered_route()])

    assert deleted == ["allow-contacts"]
    assert ("DELETE", f"{ADMIN}/routes/allow-contacts") in kong.calls


def test_prune_keeps_protected_routes():
    existing = [
        kong_route(name="allow-events"),
        kong_route(name="flows-default-block", id="route-block", tags=[]),
        kong_route(name="custom-manual", id="route-manual", tags=[]),
        kong_route(
            name="allow-foreign",
            id="route-foreign",
            paths=["/nexus/api/v2/foreign.json"],
            tags=[],
        ),
        # A route from another prefix that landed on this service already tagged.
        kong_route(
            name="allow-foreign-tagged",
            id="route-foreign-tagged",
            paths=["/nexus/api/v2/tagged.json"],
            tags=["kong-sync", "prefix-nexus"],
        ),
        kong_route(name="allow-moved", id="route-moved"),
    ]

    deleted = prune_routes(
        ADMIN,
        SERVICE_ID,
        PREFIX,
        {"allow-events", "allow-moved"},
        existing,
    )

    assert deleted == []


def test_prune_ignores_routes_of_another_service():
    existing = [kong_route(name="allow-contacts", service={"id": "svc-nexus"})]

    deleted = prune_routes(ADMIN, SERVICE_ID, PREFIX, {"allow-events"}, existing)

    assert deleted == []


def test_prune_skips_when_discovery_is_empty():
    existing = [kong_route(name="allow-contacts")]

    deleted = prune_routes(ADMIN, SERVICE_ID, PREFIX, set(), existing)

    assert deleted == []


def test_prune_above_threshold_requires_force():
    existing = [
        kong_route(name=f"allow-{index}", id=f"route-{index}") for index in range(4)
    ]

    with pytest.raises(PruneLimitExceeded) as excinfo:
        prune_routes(ADMIN, SERVICE_ID, PREFIX, {"allow-events"}, existing)

    assert "--force-prune" in str(excinfo.value)


def test_prune_above_threshold_runs_with_force():
    existing = [
        kong_route(name=f"allow-{index}", id=f"route-{index}") for index in range(4)
    ]
    kong = FakeKong()

    with patch("weni_commons.kong.sync.http", kong):
        deleted = prune_routes(
            ADMIN, SERVICE_ID, PREFIX, {"allow-events"}, existing, force=True
        )

    assert len(deleted) == 4
    assert len(kong.methods("DELETE")) == 4


@override_settings(ROOT_URLCONF="tests.urls")
def test_command_derives_service_from_prefix(monkeypatch):
    monkeypatch.delenv("KONG_SERVICE", raising=False)
    captured = {}

    def fake_discover(**kwargs):
        captured["default_service"] = kwargs.get("default_service")
        return []

    with patch(
        "weni_commons.management.commands.kong_sync.discover_routes", fake_discover
    ):
        stdout = StringIO()
        call_command(
            "kong_sync",
            "--url-prefix",
            PREFIX,
            "--kong-addr",
            ADMIN,
            stdout=stdout,
        )

    assert captured["default_service"] == "flows-service"
    assert "No @api_gateway_expose routes found" in stdout.getvalue()


@override_settings(ROOT_URLCONF="tests.urls")
def test_command_explicit_service_overrides_derived_name(monkeypatch):
    monkeypatch.delenv("KONG_SERVICE", raising=False)
    captured = {}

    def fake_discover(**kwargs):
        captured["default_service"] = kwargs.get("default_service")
        return []

    with patch(
        "weni_commons.management.commands.kong_sync.discover_routes", fake_discover
    ):
        call_command(
            "kong_sync",
            "--url-prefix",
            PREFIX,
            "--service",
            "custom-service",
            "--kong-addr",
            ADMIN,
            stdout=StringIO(),
        )

    assert captured["default_service"] == "custom-service"


def test_command_rejects_multi_segment_prefix_when_deriving_service(monkeypatch):
    monkeypatch.delenv("KONG_SERVICE", raising=False)

    with pytest.raises(CommandError) as excinfo:
        call_command(
            "kong_sync", "--url-prefix", "/foo/bar", "--kong-addr", ADMIN
        )

    assert "single path segment" in str(excinfo.value)


def test_command_requires_url_prefix(monkeypatch):
    monkeypatch.delenv("KONG_URL_PREFIX", raising=False)

    with pytest.raises(CommandError) as excinfo:
        call_command("kong_sync", "--service", SERVICE)

    assert "KONG_URL_PREFIX" in str(excinfo.value)


@override_settings(
    KONG_URL_PREFIX=PREFIX,
    KONG_SERVICE=SERVICE,
    KONG_ADMIN_URL=ADMIN,
    ROOT_URLCONF="tests.urls",
)
def test_command_runs_with_configuration_from_settings(monkeypatch):
    for name in ("KONG_URL_PREFIX", "KONG_SERVICE", "KONG_ADMIN_URL"):
        monkeypatch.delenv(name, raising=False)

    stdout = StringIO()
    call_command("kong_sync", stdout=stdout)

    assert "No @api_gateway_expose routes found" in stdout.getvalue()


def test_decorator_defaults_service_to_none():
    @api_gateway_expose
    class Endpoint:
        pass

    assert Endpoint._kong_service is None


def test_decorator_keeps_explicit_service():
    @api_gateway_expose(service="insights-service")
    class Endpoint:
        pass

    assert Endpoint._kong_service == "insights-service"


@override_settings(ROOT_URLCONF="tests.openapi_urls")
def test_discover_routes_fills_none_service_from_prefix(monkeypatch):
    monkeypatch.setenv("KONG_URL_PREFIX", PREFIX)
    routes = {route["name"]: route for route in discover_routes()}

    assert routes["allow-contacts"]["service"] == "flows-service"
    assert routes["allow-dashboards-pk-widgets"]["service"] == "insights-service"


@override_settings(ROOT_URLCONF="tests.openapi_urls")
def test_discover_routes_uses_command_service_for_none(monkeypatch):
    monkeypatch.setenv("KONG_URL_PREFIX", PREFIX)
    routes = {
        route["name"]: route
        for route in discover_routes(default_service="billing-service")
    }

    assert routes["allow-contacts"]["service"] == "billing-service"
    assert routes["allow-dashboards-pk-widgets"]["service"] == "insights-service"


def test_ensure_service_derives_service_from_prefix(monkeypatch):
    monkeypatch.delenv("KONG_SERVICE", raising=False)
    stdout = StringIO()

    call_command(
        "kong_ensure_service",
        "--url-prefix",
        "/billing",
        "--url",
        "https://billing.example.com",
        "--dry-run",
        stdout=stdout,
    )

    assert "billing-service" in stdout.getvalue()


def test_ensure_service_explicit_service_overrides_derived_name(monkeypatch):
    monkeypatch.delenv("KONG_SERVICE", raising=False)
    stdout = StringIO()

    call_command(
        "kong_ensure_service",
        "--url-prefix",
        "/billing",
        "--service",
        "custom-billing",
        "--url",
        "https://billing.example.com",
        "--dry-run",
        stdout=stdout,
    )

    assert "custom-billing" in stdout.getvalue()
    assert "billing-service" not in stdout.getvalue()
