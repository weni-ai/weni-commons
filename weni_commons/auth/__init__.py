from weni_commons.auth.authentication import (
    SessionTokenAuthentication,
    SessionUser,
    extract_bearer_token,
)
from weni_commons.auth.authenticators import WeniAuthentication
from weni_commons.auth.connect import ConnectAuthorizationClient
from weni_commons.auth.context import (
    TOKEN_TYPE_JWT,
    TOKEN_TYPE_KEYCLOAK,
    WeniAuthContext,
    WeniAuthUser,
)
from weni_commons.auth.dynamodb import DynamoDBSessionTokenRepository
from weni_commons.auth.helpers import (
    get_account_id,
    get_auth_context,
    get_project_uuid,
    get_user_email,
    get_vtex_account,
    is_internal_request,
)
from weni_commons.auth.interfaces import UserPermissionsServiceInterface
from weni_commons.auth.mixins import WeniAuthViewMixin
from weni_commons.auth.permissions import (
    CanCommunicateInternally,
    ConnectProjectAuthorization,
    HasProjectPermission,
    IsWeniAuthenticated,
    PermissionLevel,
)
from weni_commons.auth.resolvers import (
    resolve_from_request,
    resolve_project_uuid_from_request,
    resolve_vtex_account_from_request,
)
from weni_commons.auth.session import (
    SessionContext,
    ValidateSessionTokenUseCase,
    build_cache_key,
    compute_redis_ttl,
    evict_cache,
    warm_cache,
)
from weni_commons.auth.token import WENI_AUTH_HEADER, extract_token

__all__ = [
    "CanCommunicateInternally",
    "ConnectAuthorizationClient",
    "ConnectProjectAuthorization",
    "DynamoDBSessionTokenRepository",
    "HasProjectPermission",
    "IsWeniAuthenticated",
    "PermissionLevel",
    "SessionContext",
    "SessionTokenAuthentication",
    "SessionUser",
    "TOKEN_TYPE_JWT",
    "TOKEN_TYPE_KEYCLOAK",
    "UserPermissionsServiceInterface",
    "ValidateSessionTokenUseCase",
    "WENI_AUTH_HEADER",
    "WeniAuthContext",
    "WeniAuthUser",
    "WeniAuthentication",
    "WeniAuthViewMixin",
    "build_cache_key",
    "compute_redis_ttl",
    "evict_cache",
    "extract_bearer_token",
    "extract_token",
    "get_account_id",
    "get_auth_context",
    "get_project_uuid",
    "get_user_email",
    "get_vtex_account",
    "is_internal_request",
    "resolve_from_request",
    "resolve_project_uuid_from_request",
    "resolve_vtex_account_from_request",
    "warm_cache",
]
