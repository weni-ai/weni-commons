SECRET_KEY = "test-secret-key"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "weni.feature_flags",
]

REST_FRAMEWORK = {
    "UNAUTHENTICATED_USER": None,
}
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
ROOT_URLCONF = []
USE_TZ = True

GROWTHBOOK_CLIENT_KEY = "test-client-key"
GROWTHBOOK_HOST_BASE_URL = "https://growthbook.test"
