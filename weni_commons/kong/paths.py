"""
Path helpers for Kong route discovery (templates, regex, rewrite modes).
"""
import re
from typing import List, Optional, Tuple

# Django path converter / named group → {name}
_ROUTE_CONVERTER_RE = re.compile(r"<(?:(?P<converter>[^>:]+):)?(?P<name>\w+)>")
_NAMED_GROUP_RE = re.compile(r"\(\?P<(?P<name>\w+)>[^)]+\)")
_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


def path_template_from_route(route: str) -> str:
    """
    Convert a Django route string to a template with ``{name}`` placeholders.

    Examples:
        ``dashboards/<pk>/list_widgets/`` → ``/dashboards/{pk}/list_widgets``
        ``dashboards/<uuid:pk>/`` → ``/dashboards/{pk}``
    """
    cleaned = route.strip("/")
    templated = _ROUTE_CONVERTER_RE.sub(r"{\g<name>}", cleaned)
    return "/" + templated if templated else "/"


def path_template_from_regex(regex: str) -> str:
    """
    Convert a Django regex pattern to a ``{name}`` template (lossy).

    Strips anchors and non-capturing groups; named groups become ``{name}``.
    """
    pattern = regex.strip("^$")
    # Drop format-suffix style groups like \\.(?P<format>...)
    pattern = re.sub(r"\\\.\(\?P<format>[^)]+\)", "", pattern)
    pattern = _NAMED_GROUP_RE.sub(r"{\g<name>}", pattern)
    # Remove remaining unnamed groups / optional markers crudely
    pattern = pattern.replace("(?:", "").replace(")?", "").replace(")", "")
    pattern = pattern.replace("\\.", ".")
    pattern = pattern.strip("/")
    return "/" + pattern if pattern else "/"


def kong_regex_path(path_template: str) -> str:
    """
    Convert ``/dashboards/{pk}/widgets`` to a Kong regex path.

    Kong regex paths are prefixed with ``~``.
    """
    regex_body = _PATH_PARAM_RE.sub(r"(?<\1>[^/]+)", path_template)
    if not regex_body.startswith("/"):
        regex_body = "/" + regex_body
    return "~" + regex_body


def path_param_names(path_template: str) -> List[str]:
    return _PATH_PARAM_RE.findall(path_template)


def has_path_params(path_template: str) -> bool:
    return bool(path_param_names(path_template))


def normalize_path(path: str) -> str:
    """Ensure a leading slash and no trailing slash (except root)."""
    cleaned = "/" + path.lstrip("/")
    if len(cleaned) > 1:
        cleaned = cleaned.rstrip("/")
    return cleaned


def join_prefix(url_prefix: str, path: str) -> str:
    """Join gateway prefix with a path (path may be a Kong regex starting with ``~``)."""
    prefix = url_prefix.rstrip("/")
    if path.startswith("~"):
        body = path[1:]
        if not body.startswith("/"):
            body = "/" + body
        return "~" + prefix + body
    return prefix + normalize_path(path)


def rewrite_mode_for(
    upstream_template: str,
    alias: Optional[str],
) -> Tuple[str, Optional[str]]:
    """
    Decide rewrite strategy and normalize alias for Kong paths.

    Returns:
        (rewrite_mode, alias_template_or_none)

    Modes:
        static_uri      — no path params; request-transformer replace.uri
        strip_prefix    — params; strip KONG_URL_PREFIX via pre-function
        alias_captures  — alias with ``{pk}``; rewrite captures via pre-function
    """
    alias_template = normalize_path(alias)[1:] if alias else None  # no leading slash stored form
    if alias:
        alias_path = normalize_path(alias)
        if has_path_params(alias_path):
            return "alias_captures", alias_path.lstrip("/")
        if has_path_params(upstream_template):
            # Flat alias without captures can't carry pk — skip flat paths.
            return "strip_prefix", None
        return "static_uri", alias_path.lstrip("/")

    if has_path_params(upstream_template):
        return "strip_prefix", None
    return "static_uri", None
