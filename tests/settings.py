SECRET_KEY = "test-secret-key"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "rest_framework",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

USE_TZ = True

JWT_PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAuPublicKeyForTestsOnly
-----END PUBLIC KEY-----"""

OIDC_DRF_AUTH_BACKEND = "tests.backends.TestOIDCAuthenticationBackend"

GROWTHBOOK_CLIENT_KEY = "test-client-key"
GROWTHBOOK_HOST_BASE_URL = "https://growthbook.test"
