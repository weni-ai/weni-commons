import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from django.test import override_settings

from weni_commons.auth.constants import DYNAMODB_PARTITION_KEY, MAX_REDIS_TTL_SECONDS
from weni_commons.auth.dynamodb import DynamoDBSessionTokenRepository
from weni_commons.auth.session import (
    ValidateSessionTokenUseCase,
    compute_redis_ttl,
)


def test_compute_redis_ttl_without_expire_at_uses_max_ttl():
    assert compute_redis_ttl(None, max_ttl=1800) == 1800
    assert compute_redis_ttl("", max_ttl=1800) == 1800


def test_compute_redis_ttl_without_expire_at_uses_default_max_ttl():
    assert compute_redis_ttl(None) == MAX_REDIS_TTL_SECONDS


def test_compute_redis_ttl_rejects_expired_token():
    expire_at = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    assert compute_redis_ttl(expire_at, max_ttl=3600) == 0


@override_settings(WENI_SESSION_TOKEN_DYNAMODB_TABLE="weni-session-tokens")
def test_dynamodb_put_omits_ttl_when_expire_at_is_missing():
    table = MagicMock()
    repo = DynamoDBSessionTokenRepository(table=table, table_name="weni-session-tokens")

    repo.put(token_hash="hash", project="project-uuid", user="user@example.com")

    item = table.put_item.call_args.kwargs["Item"]
    assert item[DYNAMODB_PARTITION_KEY] == "hash"
    assert item["project"] == "project-uuid"
    assert item["user"] == "user@example.com"
    assert "expire_at" not in item
    assert "ttl" not in item


@override_settings(WENI_SESSION_TOKEN_DYNAMODB_TABLE="weni-session-tokens")
def test_dynamodb_get_accepts_item_without_expire_at():
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {
            DYNAMODB_PARTITION_KEY: "hash",
            "project": "project-uuid",
            "user": "user@example.com",
        }
    }
    repo = DynamoDBSessionTokenRepository(table=table, table_name="weni-session-tokens")

    payload = repo.get("hash")

    assert payload == {
        "project": "project-uuid",
        "user": "user@example.com",
    }


def test_validate_session_token_from_redis_without_expire_at():
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(
        {"project": "project-uuid", "user": "user@example.com"}
    ).encode("utf-8")

    session = ValidateSessionTokenUseCase(redis_connection=mock_redis).execute("hash")

    assert session is not None
    assert session.project == "project-uuid"
    assert session.user == "user@example.com"
    assert session.expire_at is None


def test_validate_session_token_from_dynamodb_without_expire_at():
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    mock_repo = MagicMock()
    mock_repo.get.return_value = {
        "project": "project-uuid",
        "user": "user@example.com",
    }

    session = ValidateSessionTokenUseCase(
        redis_connection=mock_redis,
        dynamodb_repository=mock_repo,
    ).execute("hash")

    assert session is not None
    assert session.expire_at is None
    mock_redis.setex.assert_called_once()
    _, ttl, payload = mock_redis.setex.call_args[0]
    assert ttl == MAX_REDIS_TTL_SECONDS
    assert "expire_at" not in json.loads(payload)
