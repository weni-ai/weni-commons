from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from weni_commons.auth.dynamodb import DynamoDBSessionTokenRepository


def _repo_with_table():
    table = MagicMock()
    repo = DynamoDBSessionTokenRepository(table=table, table_name="session-tokens-test")
    return repo, table


def test_get_returns_payload():
    repo, table = _repo_with_table()
    table.get_item.return_value = {
        "Item": {
            "token_hash": "abc",
            "projeto": "project-uuid",
            "user": "user@example.com",
            "expire_at": "2026-06-10T12:00:00+00:00",
        }
    }

    payload = repo.get("abc")

    assert payload == {
        "projeto": "project-uuid",
        "user": "user@example.com",
        "expire_at": "2026-06-10T12:00:00+00:00",
    }
    table.get_item.assert_called_once_with(Key={"token_hash": "abc"})


def test_get_returns_none_when_item_missing():
    repo, table = _repo_with_table()
    table.get_item.return_value = {}

    assert repo.get("abc") is None


def test_get_returns_none_for_incomplete_item():
    repo, table = _repo_with_table()
    table.get_item.return_value = {"Item": {"token_hash": "abc", "projeto": "uuid"}}

    assert repo.get("abc") is None


@patch("weni_commons.auth.dynamodb.DEFAULT_DYNAMODB_TABLE", None)
def test_get_returns_none_without_table_name():
    repo = DynamoDBSessionTokenRepository(table_name=None)
    assert repo.get("abc") is None


def test_get_returns_none_for_empty_hash():
    repo, table = _repo_with_table()
    assert repo.get("") is None
    table.get_item.assert_not_called()


def test_put_writes_item_with_ttl():
    repo, table = _repo_with_table()
    expire_at = "2026-06-10T12:00:00+00:00"

    repo.put("abc", "project-uuid", "user@example.com", expire_at)

    table.put_item.assert_called_once()
    item = table.put_item.call_args.kwargs["Item"]
    assert item["token_hash"] == "abc"
    assert item["projeto"] == "project-uuid"
    assert item["user"] == "user@example.com"
    assert item["expire_at"] == expire_at
    expected_epoch = int(
        datetime.fromisoformat(expire_at).astimezone(timezone.utc).timestamp()
    )
    assert item["ttl"] == expected_epoch


@patch("weni_commons.auth.dynamodb.DEFAULT_DYNAMODB_TABLE", None)
def test_put_skips_without_table_name():
    table = MagicMock()
    repo = DynamoDBSessionTokenRepository(table=table, table_name=None)

    repo.put("abc", "p", "u", "2026-06-10T12:00:00+00:00")

    table.put_item.assert_not_called()


def test_delete_removes_item():
    repo, table = _repo_with_table()

    repo.delete("abc")

    table.delete_item.assert_called_once_with(Key={"token_hash": "abc"})


@patch("weni_commons.auth.dynamodb.DEFAULT_DYNAMODB_TABLE", None)
def test_delete_skips_without_table_name():
    table = MagicMock()
    repo = DynamoDBSessionTokenRepository(table=table, table_name=None)

    repo.delete("abc")

    table.delete_item.assert_not_called()


def test_delete_skips_for_empty_hash():
    repo, table = _repo_with_table()

    repo.delete("")

    table.delete_item.assert_not_called()
