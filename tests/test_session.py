import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from weni_commons.auth.session import (
    SessionContext,
    ValidateSessionTokenUseCase,
    build_cache_key,
    compute_redis_ttl,
)


@pytest.fixture
def mock_redis():
    return MagicMock()


def _iso_in(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def test_build_cache_key():
    assert build_cache_key("abc123") == "auth:session-token:abc123"


def test_execute_returns_session_context(mock_redis):
    payload = {
        "projeto": "project-uuid",
        "user": "user@example.com",
        "expire_at": "2026-06-10T12:00:00+00:00",
    }
    mock_redis.get.return_value = json.dumps(payload).encode("utf-8")

    use_case = ValidateSessionTokenUseCase(redis_connection=mock_redis)
    session = use_case.execute("valid-hash")

    assert session == SessionContext(
        projeto="project-uuid",
        user="user@example.com",
        expire_at="2026-06-10T12:00:00+00:00",
    )
    mock_redis.get.assert_called_once_with(build_cache_key("valid-hash"))


def test_execute_returns_none_when_redis_misses(mock_redis):
    mock_redis.get.return_value = None

    use_case = ValidateSessionTokenUseCase(redis_connection=mock_redis)
    session = use_case.execute("missing-hash")

    assert session is None


def test_execute_returns_none_for_malformed_json(mock_redis):
    mock_redis.get.return_value = b"not-json"

    use_case = ValidateSessionTokenUseCase(redis_connection=mock_redis)
    session = use_case.execute("bad-hash")

    assert session is None


def test_execute_returns_none_for_missing_required_fields(mock_redis):
    mock_redis.get.return_value = json.dumps({"projeto": "uuid"}).encode("utf-8")

    use_case = ValidateSessionTokenUseCase(redis_connection=mock_redis)
    session = use_case.execute("incomplete-hash")

    assert session is None


def test_execute_returns_none_for_empty_token(mock_redis):
    use_case = ValidateSessionTokenUseCase(redis_connection=mock_redis)
    session = use_case.execute("")

    assert session is None
    mock_redis.get.assert_not_called()


def test_redis_hit_does_not_touch_dynamodb(mock_redis):
    payload = {
        "projeto": "project-uuid",
        "user": "user@example.com",
        "expire_at": _iso_in(3600),
    }
    mock_redis.get.return_value = json.dumps(payload).encode("utf-8")
    mock_repo = MagicMock()

    use_case = ValidateSessionTokenUseCase(
        redis_connection=mock_redis, dynamodb_repository=mock_repo
    )
    session = use_case.execute("valid-hash")

    assert session.projeto == "project-uuid"
    mock_repo.get.assert_not_called()


def test_redis_miss_falls_back_to_dynamodb_and_warms_cache(mock_redis):
    mock_redis.get.return_value = None
    expire_at = _iso_in(3600)
    payload = {
        "projeto": "project-uuid",
        "user": "user@example.com",
        "expire_at": expire_at,
    }
    mock_repo = MagicMock()
    mock_repo.get.return_value = payload

    use_case = ValidateSessionTokenUseCase(
        redis_connection=mock_redis, dynamodb_repository=mock_repo
    )
    session = use_case.execute("valid-hash")

    assert session == SessionContext(
        projeto="project-uuid",
        user="user@example.com",
        expire_at=expire_at,
    )
    mock_repo.get.assert_called_once_with("valid-hash")
    mock_redis.setex.assert_called_once()
    key, ttl, raw = mock_redis.setex.call_args[0]
    assert key == build_cache_key("valid-hash")
    assert 0 < ttl <= 3600
    assert json.loads(raw) == payload


def test_redis_miss_and_dynamodb_miss_returns_none(mock_redis):
    mock_redis.get.return_value = None
    mock_repo = MagicMock()
    mock_repo.get.return_value = None

    use_case = ValidateSessionTokenUseCase(
        redis_connection=mock_redis, dynamodb_repository=mock_repo
    )
    session = use_case.execute("missing-hash")

    assert session is None
    mock_redis.setex.assert_not_called()


def test_expired_dynamodb_token_returns_none_without_warming(mock_redis):
    mock_redis.get.return_value = None
    payload = {
        "projeto": "project-uuid",
        "user": "user@example.com",
        "expire_at": _iso_in(-10),
    }
    mock_repo = MagicMock()
    mock_repo.get.return_value = payload

    use_case = ValidateSessionTokenUseCase(
        redis_connection=mock_redis, dynamodb_repository=mock_repo
    )
    session = use_case.execute("expired-hash")

    assert session is None
    mock_redis.setex.assert_not_called()


def test_compute_redis_ttl_caps_at_max():
    ttl = compute_redis_ttl(_iso_in(2 * 86400), max_ttl=86400)
    assert ttl == 86400


def test_compute_redis_ttl_uses_remaining_when_below_cap():
    ttl = compute_redis_ttl(_iso_in(3600), max_ttl=86400)
    assert 3590 <= ttl <= 3600


def test_compute_redis_ttl_returns_zero_when_expired():
    assert compute_redis_ttl(_iso_in(-5), max_ttl=86400) == 0


def test_compute_redis_ttl_returns_zero_for_invalid_value():
    assert compute_redis_ttl("not-a-date", max_ttl=86400) == 0
