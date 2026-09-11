import pytest
from django.test import override_settings

from weni_commons.kong.config import kong_service_name, resolve_config, resolved_kong_service


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("KONG_ADMIN_URL", raising=False)


def test_returns_default_when_unset():
    assert resolve_config("KONG_ADMIN_URL", "http://localhost:8001") == (
        "http://localhost:8001"
    )


def test_returns_none_when_unset_without_default():
    assert resolve_config("KONG_ADMIN_URL") is None


def test_reads_from_environment(monkeypatch):
    monkeypatch.setenv("KONG_ADMIN_URL", "http://from-env:8001")

    assert resolve_config("KONG_ADMIN_URL", "http://default:8001") == (
        "http://from-env:8001"
    )


@override_settings(KONG_ADMIN_URL="http://from-settings:8001")
def test_reads_from_settings():
    assert resolve_config("KONG_ADMIN_URL", "http://default:8001") == (
        "http://from-settings:8001"
    )


@override_settings(KONG_ADMIN_URL="http://from-settings:8001")
def test_settings_win_over_environment(monkeypatch):
    monkeypatch.setenv("KONG_ADMIN_URL", "http://from-env:8001")

    assert resolve_config("KONG_ADMIN_URL") == "http://from-settings:8001"


@override_settings(KONG_ADMIN_URL="   ")
def test_blank_setting_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("KONG_ADMIN_URL", "http://from-env:8001")

    assert resolve_config("KONG_ADMIN_URL") == "http://from-env:8001"


@override_settings(KONG_ADMIN_URL="")
def test_blank_setting_and_environment_fall_back_to_default(monkeypatch):
    monkeypatch.setenv("KONG_ADMIN_URL", "  ")

    assert resolve_config("KONG_ADMIN_URL", "http://default:8001") == (
        "http://default:8001"
    )


def test_strips_surrounding_whitespace(monkeypatch):
    monkeypatch.setenv("KONG_ADMIN_URL", "  http://from-env:8001\n")

    assert resolve_config("KONG_ADMIN_URL") == "http://from-env:8001"


def test_kong_service_name_from_slash_prefix():
    assert kong_service_name("/flows") == "flows-service"


def test_kong_service_name_strips_surrounding_slashes():
    assert kong_service_name("  /billing/  ") == "billing-service"


def test_kong_service_name_rejects_empty_prefix():
    with pytest.raises(ValueError, match="empty"):
        kong_service_name("  /  ")


def test_kong_service_name_rejects_multi_segment_prefix():
    with pytest.raises(ValueError, match="single path segment"):
        kong_service_name("/foo/bar")


def test_resolved_kong_service_prefers_explicit_name():
    assert resolved_kong_service("custom-service", "/flows") == "custom-service"


def test_resolved_kong_service_derives_when_empty():
    assert resolved_kong_service(None, "/flows") == "flows-service"
    assert resolved_kong_service("  ", "/billing") == "billing-service"
