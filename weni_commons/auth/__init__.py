from weni_commons.auth.authenticators import WeniAuthentication
from weni_commons.auth.context import (
    TOKEN_TYPE_JWT,
    TOKEN_TYPE_KEYCLOAK,
    WeniAuthContext,
    WeniAuthUser,
)
from weni_commons.auth.interfaces import UserPermissionsServiceInterface
from weni_commons.auth.permissions import (
    CanCommunicateInternally,
    HasProjectPermission,
    IsWeniAuthenticated,
    PermissionLevel,
)

from weni_commons.auth.token import WENI_AUTH_HEADER, extract_token

from weni_commons.auth.mixins import WeniAuthViewMixin

from weni_commons.auth.helpers import (
    get_account_id,
    get_auth_context,
    get_project_uuid,
    get_user_email,
    get_vtex_account,
    is_internal_request,
)

from weni_commons.auth.resolvers import (
    resolve_from_request,
    resolve_project_uuid_from_request,
    resolve_vtex_account_from_request,
)

__all__ = [
    "CanCommunicateInternally",
    "HasProjectPermission",
    "IsWeniAuthenticated",
    "PermissionLevel",
    "TOKEN_TYPE_JWT",
    "TOKEN_TYPE_KEYCLOAK",
    "UserPermissionsServiceInterface",
    "WeniAuthContext",
    "WeniAuthUser",
    "WeniAuthentication",
    "WeniAuthViewMixin",
    "get_account_id",
    "get_auth_context",
    "get_project_uuid",
    "get_user_email",
    "get_vtex_account",
    "is_internal_request",
    "resolve_from_request",
    "resolve_project_uuid_from_request",
    "resolve_vtex_account_from_request",
    "extract_token",
    "WENI_AUTH_HEADER",
]
