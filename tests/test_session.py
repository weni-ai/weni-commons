import json
from unittest.mock import MagicMock

import pytest

from weni_commons.auth.session import (
    SessionContext,
    ValidateSessionTokenUseCase,
    build_cache_key,
)


@pytest.fixture
def mock_redis():
    return MagicMock()


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
