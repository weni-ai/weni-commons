"""
Resolve a Django user + org from a validated SessionContext.

Host apps configure this via Django settings so weni-commons stays free of
product-specific model imports:

  WENI_SESSION_TOKEN_ORG_MODEL
      Dotted path to the organization model, e.g. ``temba.orgs.models.Org``.
      When unset, resolution is skipped and SessionUser is returned as-is.

  WENI_SESSION_TOKEN_ORG_FIELD
      Field used to look up the org from ``session.project`` (default: ``proj_uuid``).

  WENI_SESSION_TOKEN_INTERNAL_USER_EMAIL / INTERNAL_USER_EMAIL
      Fallback user email when ``session.user`` is missing or not a member of the org.
"""
import logging
from typing import Any, Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils.module_loading import import_string

from weni_commons.auth.session import SessionContext

logger = logging.getLogger(__name__)


def _get_org_model():
    model_path = getattr(settings, "WENI_SESSION_TOKEN_ORG_MODEL", None)
    if not model_path:
        return None
    return import_string(model_path)


def _lookup_org(project_uuid: str) -> Any:
    org_model = _get_org_model()
    if org_model is None:
        return None

    field = getattr(settings, "WENI_SESSION_TOKEN_ORG_FIELD", "proj_uuid")
    try:
        return org_model.objects.filter(**{field: project_uuid}).first()
    except (ValidationError, ValueError, TypeError):
        return None


def _org_has_user(org, user) -> bool:
    has_user = getattr(org, "has_user", None)
    if callable(has_user):
        return bool(has_user(user))
    return True


def _resolve_fallback_user(org):
    user_model = get_user_model()
    internal_email = getattr(settings, "WENI_SESSION_TOKEN_INTERNAL_USER_EMAIL", None) or getattr(
        settings, "INTERNAL_USER_EMAIL", ""
    )
    if internal_email:
        try:
            return user_model.objects.get(email=internal_email)
        except user_model.DoesNotExist:
            pass

    return getattr(org, "created_by", None) or getattr(org, "modified_by", None)


def _session_user(email: str):
    from weni_commons.auth.authentication import SessionUser

    return SessionUser(email=email)


def resolve_session_user(request, session: SessionContext):
    """
    Attach project/org on the request and return a Django user ready for
    permission checks (``get_org`` / ``set_org``).

    Falls back to ``SessionUser`` when org model settings are not configured
    or the project cannot be resolved.
    """
    project_uuid = session.project
    if project_uuid:
        request.project_uuid = project_uuid

    if not getattr(settings, "WENI_SESSION_TOKEN_ORG_MODEL", None):
        return _session_user(session.user)

    org = _lookup_org(project_uuid) if project_uuid else None
    if org is None:
        logger.warning(
            "Session token project could not be resolved (project=%s)",
            project_uuid,
        )
        return _session_user(session.user)

    request._org = org

    user_model = get_user_model()
    user: Optional[Any] = None
    if session.user:
        user = user_model.objects.filter(email=session.user).first()
        if user and not _org_has_user(org, user):
            user = None

    if user is None:
        user = _resolve_fallback_user(org)

    if user is None:
        return _session_user(session.user)

    set_org = getattr(user, "set_org", None)
    if callable(set_org):
        set_org(org)
    else:
        user.get_org = lambda: org  # type: ignore[attr-defined]

    user.using_token = True
    return user
