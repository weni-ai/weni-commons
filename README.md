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

Validate session hashes issued by Connect against centralized Redis. Apply the decorator to any DRF `APIView` — no per-project validation code required.

**Requirements:** `CACHES` must point to the same Redis instance Connect writes to:

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
from rest_framework.response import Response
from rest_framework.views import APIView
from weni_commons.auth import require_session_token

@require_session_token
class ContactsView(APIView):
    def get(self, request):
        project = request.weni_session.projeto
        user = request.weni_session.user
        return Response({"project": project, "user": user})
```

Clients must send the hash via `Authorization: Bearer <hash>`. Invalid or expired tokens receive `403 Forbidden` before the view handler runs.

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