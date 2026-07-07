# Weni Commons

A Python library that centralizes common functionality and utilities used across Weni's Django backend applications.
This library promotes code reuse, consistency, and maintainability by providing shared components and utilities that can be easily integrated into multiple Django projects.

## Installation

### Using Poetry (Recommended for Weni projects)

```bash
poetry add weni-commons
```

### Using pip

```bash
pip install weni-commons
```

## Available Features

### Feature Flags

Weni Feature Flags is a Python Library that functions as an abstraction layer between Django projects and GrowthBook.

```python
from weni.feature_flags.services import FeatureFlagsService

# Use the feature flags service
feature_service = FeatureFlagsService()
```

You can access the complete instructions on how to use its features [here](https://github.com/weni-ai/weni-feature-flags/blob/main/README.md).

### Session Token Validation

Validate session hashes issued by Connect using a DRF authentication class that composes with existing JWT/OIDC backends.

Tokens are stored in a shared DynamoDB table (source of truth) and cached in the service's local Redis. Validation looks in Redis first; on a miss it falls back to DynamoDB and warms Redis with a TTL capped at 24h (or the remaining time until expiration, whichever is smaller).

**Requirements:** `CACHES` must point to the service's local Redis, and the DynamoDB settings below must be configured:

```python
WENI_SESSION_TOKEN_DYNAMODB_TABLE = env("WENI_SESSION_TOKEN_DYNAMODB_TABLE")
WENI_SESSION_TOKEN_DYNAMODB_REGION = env("WENI_SESSION_TOKEN_DYNAMODB_REGION")
# Optional, defaults to 86400 (24h)
WENI_SESSION_TOKEN_MAX_REDIS_TTL = env.int("WENI_SESSION_TOKEN_MAX_REDIS_TTL", default=86400)
```

The DynamoDB table is keyed by `token_hash` (String) and stores `projeto`, `user`, `expire_at` (ISO 8601) plus a numeric `ttl` (epoch seconds) used as the native DynamoDB TTL attribute. AWS credentials are resolved via the standard boto3 chain (env vars / IAM role).

The local Redis cache config:

```python
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}
```

**Usage:**

```python
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from weni_commons.auth import SessionTokenAuthentication

class ContactsView(APIView):
    authentication_classes = [
        SessionTokenAuthentication,
        WeniOIDCAuthentication,
    ]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if isinstance(request.auth, SessionContext):
            project = request.auth.projeto
            user = request.user.email
        else:
            project = request.query_params.get("project_uuid")
            user = request.user.email
        return Response({"project": project, "user": user})
```

Place `SessionTokenAuthentication` **before** JWT/OIDC classes so opaque session hashes fall through to Redis/DynamoDB first and JWT tokens are handled by the next authenticator.

When the session hash is invalid, expired, or missing, the class returns `None` and DRF tries the next authentication backend instead of blocking the request immediately.

Session data is available on `request.auth` as a `SessionContext`. The authenticated user email is on `request.user.email`.

Optional setting: `WENI_SESSION_TOKEN_REDIS_ALIAS` (default `"default"`) to select the Redis cache alias.

## Requirements

- Python >= 3.8
- Django >= 3.2.22
- Django REST Framework >= 3.12.0
- Celery >= 5.0.0
- Redis (via django-redis >= 4.0.0)

## Contributing

This library is designed to grow with Weni's needs. If you have common utilities that could benefit multiple Django projects, consider contributing them to this library.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.