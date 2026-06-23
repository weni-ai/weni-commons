import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from django.conf import settings
from django_redis import get_redis_connection

from weni_commons.auth.constants import CACHE_KEY_TEMPLATE, MAX_REDIS_TTL_SECONDS
from weni_commons.auth.dynamodb import DynamoDBSessionTokenRepository


def build_cache_key(token_hash: str) -> str:
    return CACHE_KEY_TEMPLATE.format(hash=token_hash)


def compute_redis_ttl(expire_at_iso: str, max_ttl: Optional[int] = None) -> int:
    """
    Return the TTL (seconds) for caching a token in Redis.

    The value is capped at ``max_ttl`` (default 24h). A value <= 0 means the
    token is already expired and should not be cached.
    """
    if max_ttl is None:
        max_ttl = getattr(
            settings, "WENI_SESSION_TOKEN_MAX_REDIS_TTL", MAX_REDIS_TTL_SECONDS
        )

    try:
        parsed = datetime.fromisoformat(expire_at_iso)
    except (TypeError, ValueError):
        return 0

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    remaining = int((parsed - datetime.now(timezone.utc)).total_seconds())

    if remaining <= 0:
        return 0

    return min(remaining, max_ttl)


def warm_cache(redis_connection, token_hash: str, payload: dict, ttl: int) -> None:
    if ttl <= 0:
        return

    redis_connection.setex(
        build_cache_key(token_hash),
        ttl,
        json.dumps(payload),
    )


@dataclass(frozen=True)
class SessionContext:
    projeto: str
    user: str
    expire_at: str


def _build_session_context(payload: dict) -> Optional[SessionContext]:
    if not isinstance(payload, dict):
        return None

    projeto = payload.get("projeto")
    user = payload.get("user")
    expire_at = payload.get("expire_at")

    if not projeto or not user or not expire_at:
        return None

    return SessionContext(
        projeto=str(projeto),
        user=str(user),
        expire_at=str(expire_at),
    )


class ValidateSessionTokenUseCase:
    def __init__(
        self,
        redis_connection=None,
        redis_alias: Optional[str] = None,
        dynamodb_repository: Optional[DynamoDBSessionTokenRepository] = None,
    ) -> None:
        self._redis = redis_connection
        self._redis_alias = redis_alias or getattr(
            settings, "WENI_SESSION_TOKEN_REDIS_ALIAS", "default"
        )
        self._dynamodb_repository = dynamodb_repository

    def _get_dynamodb_repository(self) -> DynamoDBSessionTokenRepository:
        if self._dynamodb_repository is None:
            self._dynamodb_repository = DynamoDBSessionTokenRepository()
        return self._dynamodb_repository

    def execute(self, token_hash: str) -> Optional[SessionContext]:
        if not token_hash:
            return None

        redis_connection = self._redis or get_redis_connection(self._redis_alias)

        cached = self._from_redis(redis_connection, token_hash)
        if cached is not None:
            return cached

        return self._from_dynamodb(redis_connection, token_hash)

    def _from_redis(
        self, redis_connection, token_hash: str
    ) -> Optional[SessionContext]:
        raw_payload = redis_connection.get(build_cache_key(token_hash))

        if raw_payload is None:
            return None

        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode("utf-8")

        try:
            payload = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError):
            return None

        return _build_session_context(payload)

    def _from_dynamodb(
        self, redis_connection, token_hash: str
    ) -> Optional[SessionContext]:
        payload = self._get_dynamodb_repository().get(token_hash)

        if payload is None:
            return None

        session = _build_session_context(payload)
        if session is None:
            return None

        ttl = compute_redis_ttl(session.expire_at)
        if ttl <= 0:
            return None

        warm_cache(redis_connection, token_hash, payload, ttl)

        return session
