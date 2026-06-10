import json
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django_redis import get_redis_connection

from weni_commons.auth.constants import CACHE_KEY_TEMPLATE


def build_cache_key(token_hash: str) -> str:
    return CACHE_KEY_TEMPLATE.format(hash=token_hash)


@dataclass(frozen=True)
class SessionContext:
    projeto: str
    user: str
    expire_at: str


class ValidateSessionTokenUseCase:
    def __init__(self, redis_connection=None, redis_alias: Optional[str] = None) -> None:
        self._redis = redis_connection
        self._redis_alias = redis_alias or getattr(
            settings, "WENI_SESSION_TOKEN_REDIS_ALIAS", "default"
        )

    def execute(self, token_hash: str) -> Optional[SessionContext]:
        if not token_hash:
            return None

        redis_connection = self._redis or get_redis_connection(self._redis_alias)
        raw_payload = redis_connection.get(build_cache_key(token_hash))

        if raw_payload is None:
            return None

        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode("utf-8")

        try:
            payload = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError):
            return None

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
