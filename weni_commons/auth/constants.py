"""Shared auth claim names used across JWT and Keycloak flows."""

KEYCLOAK_EMAIL_CLAIMS = ("email", "preferred_username")
KEYCLOAK_PROJECT_UUID_CLAIMS = ("project_uuid",)
KEYCLOAK_VTEX_ACCOUNT_CLAIMS = ("vtex_account", "vtexAccount")
KEYCLOAK_ACCOUNT_ID_CLAIMS = ("account_id", "accountId")

# Marks service-to-service callers. Keycloak may also grant this via Django
# permissions; App IO JWTs should omit it (defaults to False for end users).
INTERNAL_CALLER_CLAIMS = ("can_communicate_internally",)

JWT_ALGORITHMS = ("RS256",)
JWT_DECODE_OPTIONS = {"verify_aud": False}

# Standardized request keys used to resolve tenant scope for Keycloak callers
# (JWT callers read the immutable claim from the token instead). Keys are
# matched case-insensitively, ignoring "-" and "_" separators, so a single
# canonical spelling here also accepts variants such as "project-uuid",
# "projectUuid" and "PROJECT_UUID". Endpoints exposing these values under other
# names must be refactored to one of the standard keys.
PROJECT_UUID_REQUEST_KEYS = ("project_uuid", "project")
VTEX_ACCOUNT_REQUEST_KEYS = ("vtex_account",)
