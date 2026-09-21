from datetime import datetime, timezone
from typing import Optional

import boto3
from django.conf import settings

from weni_commons.auth.constants import (
    DEFAULT_DYNAMODB_REGION,
    DEFAULT_DYNAMODB_TABLE,
    DYNAMODB_PARTITION_KEY,
)


def _to_epoch(expire_at_iso: str) -> Optional[int]:
    try:
        parsed = datetime.fromisoformat(expire_at_iso)
    except (TypeError, ValueError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return int(parsed.timestamp())


class DynamoDBSessionTokenRepository:
    """
    Repository for session tokens stored in a shared DynamoDB table.

    The table is keyed by ``token_hash`` and stores ``project``, ``user`` and,
    when the token expires, ``expire_at`` (ISO 8601). A numeric ``ttl``
    attribute (epoch seconds) is written so DynamoDB can expire stale items
    natively. Tokens without ``expire_at`` have no TTL and remain until
    deleted.
    """

    def __init__(self, table=None, table_name: Optional[str] = None, region_name: Optional[str] = None) -> None:
        self._table = table
        self._table_name = table_name or getattr(
            settings, "WENI_SESSION_TOKEN_DYNAMODB_TABLE", DEFAULT_DYNAMODB_TABLE
        )
        self._region_name = region_name or getattr(
            settings, "WENI_SESSION_TOKEN_DYNAMODB_REGION", DEFAULT_DYNAMODB_REGION
        )

    def _get_table(self):
        if self._table is not None:
            return self._table

        resource = boto3.resource("dynamodb", region_name=self._region_name)
        self._table = resource.Table(self._table_name)
        return self._table

    def get(self, token_hash: str) -> Optional[dict]:
        if not token_hash or not self._table_name:
            return None

        response = self._get_table().get_item(
            Key={DYNAMODB_PARTITION_KEY: token_hash}
        )
        item = response.get("Item")

        if not item:
            return None

        project = item.get("project")
        user = item.get("user")
        expire_at = item.get("expire_at")

        if not project or not user:
            return None

        payload = {
            "project": str(project),
            "user": str(user),
        }
        if expire_at:
            payload["expire_at"] = str(expire_at)
        return payload

    def put(
        self,
        token_hash: str,
        project: str,
        user: str,
        expire_at: Optional[str] = None,
    ) -> None:
        if not token_hash or not self._table_name:
            return

        item = {
            DYNAMODB_PARTITION_KEY: token_hash,
            "project": str(project),
            "user": str(user),
        }

        if expire_at:
            item["expire_at"] = str(expire_at)
            epoch = _to_epoch(expire_at)
            if epoch is not None:
                item["ttl"] = epoch

        self._get_table().put_item(Item=item)

    def delete(self, token_hash: str) -> None:
        if not token_hash or not self._table_name:
            return

        self._get_table().delete_item(Key={DYNAMODB_PARTITION_KEY: token_hash})
