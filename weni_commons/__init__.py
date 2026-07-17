from weni_commons.auth import (
    CanCommunicateInternally,
    HasProjectPermission,
    IsWeniAuthenticated,
    PermissionLevel,
    UserPermissionsServiceInterface,
    WeniAuthContext,
    WeniAuthUser,
    WeniAuthentication,
    WeniAuthViewMixin,
    WENI_AUTH_HEADER,
    extract_token,
    get_account_id,
    get_auth_context,
    get_project_uuid,
    get_user_email,
    get_vtex_account,
    is_internal_request,
)

__all__ = [
    "CanCommunicateInternally",
    "HasProjectPermission",
    "IsWeniAuthenticated",
    "PermissionLevel",
    "UserPermissionsServiceInterface",
    "WeniAuthContext",
    "WeniAuthUser",
    "WeniAuthentication",
    "WeniAuthViewMixin",
    "WENI_AUTH_HEADER",
    "extract_token",
    "get_account_id",
    "get_auth_context",
    "get_project_uuid",
    "get_user_email",
    "get_vtex_account",
    "is_internal_request",
]


def __getattr__(name: str):
    if name == "FeatureFlagsService":
        from weni.feature_flags.services import FeatureFlagsService

        return FeatureFlagsService

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
