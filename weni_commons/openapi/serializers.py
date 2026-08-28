"""
Best-effort introspection of DRF serializers into OpenAPI-shaped descriptors.

The point is to remove guesswork from documentation: field names, types and
nullability come from the serializer that actually renders the payload, so a
generator never has to invent the shape of a response. What introspection
cannot know — what a field *means*, and a realistic value for it — is left to
whoever writes the prose, with ``help_text`` surfaced as a starting point.

Nothing here may raise: a serializer that cannot be instantiated degrades to
its declared fields, and a field that cannot be classified is reported with
``"unresolved": true`` instead of a wrong type.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_DEPTH = 4

# DRF field class name → (OpenAPI type, OpenAPI format). Resolved along the
# MRO, so project-specific subclasses inherit their base mapping.
_FIELD_TYPES = {
    "BooleanField": ("boolean", None),
    "NullBooleanField": ("boolean", None),
    "IntegerField": ("integer", None),
    "FloatField": ("number", "float"),
    # DRF renders Decimal as a string unless COERCE_DECIMAL_TO_STRING is off.
    "DecimalField": ("string", None),
    "EmailField": ("string", "email"),
    "URLField": ("string", "uri"),
    "UUIDField": ("string", "uuid"),
    "IPAddressField": ("string", "ipv4"),
    "DateTimeField": ("string", "date-time"),
    "DateField": ("string", "date"),
    "TimeField": ("string", "time"),
    "DurationField": ("string", None),
    "FileField": ("string", "binary"),
    "ImageField": ("string", "binary"),
    "MultipleChoiceField": ("array", None),
    "ChoiceField": ("string", None),
    "SlugField": ("string", None),
    "RegexField": ("string", None),
    "FilePathField": ("string", None),
    "CharField": ("string", None),
    "ListField": ("array", None),
    "DictField": ("object", None),
    "HStoreField": ("object", None),
    "JSONField": ("object", None),
    "HyperlinkedIdentityField": ("string", "uri"),
    "HyperlinkedRelatedField": ("string", "uri"),
    "SlugRelatedField": ("string", None),
    "StringRelatedField": ("string", None),
    "PrimaryKeyRelatedField": ("string", None),
}

_NUMERIC_META = ("max_value", "min_value", "max_digits", "decimal_places")
_STRING_META = ("max_length", "min_length")


def dotted_path(obj: Any) -> Optional[str]:
    """Return ``module.QualName`` for a class, or None when not a class."""
    if obj is None:
        return None
    module = getattr(obj, "__module__", None)
    name = getattr(obj, "__qualname__", None) or getattr(obj, "__name__", None)
    if not name:
        return None
    return f"{module}.{name}" if module else name


def jsonable(value: Any) -> Any:
    """Coerce a value into something json.dump can handle."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return str(value)


def _source_file(cls: Any) -> Optional[str]:
    import inspect

    try:
        return inspect.getsourcefile(cls)
    except (TypeError, OSError):  # pragma: no cover - C extensions / exec'd code
        return None


def openapi_type_for(field: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    Map a DRF field to (type, format) by walking its MRO.

    Returns (None, None) when no base class is recognized, which the caller
    reports as unresolved rather than guessing ``string``.
    """
    for klass in type(field).__mro__:
        mapped = _FIELD_TYPES.get(klass.__name__)
        if mapped:
            return mapped
    return None, None


def _is_serializer(obj: Any) -> bool:
    return hasattr(obj, "fields") and hasattr(obj, "_declared_fields")


def _auto_label(field_name: Optional[str]) -> Optional[str]:
    """Reproduce the label DRF generates in Field.bind when none is declared."""
    if not field_name:
        return None
    return field_name.replace("_", " ").capitalize()


def _is_choice_field(field: Any) -> bool:
    return any(klass.__name__ == "ChoiceField" for klass in type(field).__mro__)


def _bound_fields(serializer_class: Any) -> Tuple[Dict[str, Any], str, Optional[str]]:
    """
    Return (fields, how, error) for a serializer class.

    ``how`` is ``bound`` when instantiation worked (ModelSerializer fields
    included) or ``declared`` when only class-level declarations are available.
    """
    try:
        instance = serializer_class()
        return dict(instance.fields), "bound", None
    except Exception as exc:  # noqa: BLE001 - introspection must never fail the run
        declared = dict(getattr(serializer_class, "_declared_fields", {}) or {})
        logger.debug(
            "describe_serializer: %s could not be instantiated (%s) — using declared fields",
            dotted_path(serializer_class),
            exc,
        )
        return declared, "declared", f"{type(exc).__name__}: {exc}"


def _describe_meta(serializer_class: Any) -> Optional[Dict[str, Any]]:
    meta = getattr(serializer_class, "Meta", None)
    if meta is None:
        return None
    described = {
        "model": dotted_path(getattr(meta, "model", None)),
        "fields": jsonable(getattr(meta, "fields", None)),
        "exclude": jsonable(getattr(meta, "exclude", None)),
        "read_only_fields": jsonable(getattr(meta, "read_only_fields", None)),
    }
    return {key: value for key, value in described.items() if value is not None}


def describe_field(
    name: Optional[str],
    field: Any,
    depth: int = 0,
    seen: Tuple[Any, ...] = (),
) -> Dict[str, Any]:
    """Describe a single DRF field, recursing into nested serializers."""
    described: Dict[str, Any] = {}
    if name is not None:
        described["name"] = name
    described["field_class"] = type(field).__name__

    for attr, key in (
        ("required", "required"),
        ("read_only", "read_only"),
        ("write_only", "write_only"),
        ("allow_null", "allow_null"),
    ):
        value = getattr(field, attr, None)
        if isinstance(value, bool):
            described[key] = value

    help_text = getattr(field, "help_text", None)
    if help_text:
        described["help_text"] = str(help_text)

    # DRF derives a label from the field name when none is given ("Uuid" for
    # ``uuid``). Keeping it would pass noise off as authored documentation.
    label = getattr(field, "label", None)
    if label and str(label) != _auto_label(name or getattr(field, "field_name", None)):
        described["label"] = str(label)

    # DRF's "no default" sentinel is the ``empty`` class, so it is callable and
    # filtered out here along with callable defaults, which have no fixed value.
    default = getattr(field, "default", None)
    if default is not None and not callable(default):
        described["default"] = jsonable(default)

    # A method field is computed in Python; only its author knows the shape.
    if type(field).__name__ == "SerializerMethodField":
        described["type"] = None
        described["unresolved"] = True
        described["unresolved_reason"] = (
            "SerializerMethodField — read the method body to determine the shape"
        )
        return described

    if _is_serializer(field):
        return _describe_nested_serializer(described, field, depth, seen)

    field_type, field_format = openapi_type_for(field)

    # DictField also carries a ``child`` (the value field), so the mapped type
    # has to win: without this a DictField would be described as an array.
    child = getattr(field, "child", None)
    if child is not None and field_type == "object":
        described["type"] = "object"
        described["additional_properties"] = describe_field(None, child, depth + 1, seen)
        return described

    child_relation = getattr(field, "child_relation", None)
    container = child if child is not None else child_relation
    if container is not None:
        described["type"] = "array"
        described["items"] = describe_field(None, container, depth + 1, seen)
        return described

    if field_type is None:
        described["type"] = None
        described["unresolved"] = True
        described["unresolved_reason"] = (
            f"unmapped field class {type(field).__name__} — read the field definition"
        )
        return described

    described["type"] = field_type
    if field_format:
        described["format"] = field_format

    # Only ChoiceField exposes a static option list. RelatedField.choices would
    # evaluate the queryset, hitting the database during introspection.
    if _is_choice_field(field):
        choices = getattr(field, "choices", None)
        if choices:
            described["enum"] = [jsonable(key) for key in choices]

    constraints = _STRING_META if field_type == "string" else _NUMERIC_META
    for attr in constraints:
        value = getattr(field, attr, None)
        if value is not None:
            described[attr] = jsonable(value)

    related_model = getattr(getattr(field, "queryset", None), "model", None)
    if related_model is not None:
        described["related_model"] = dotted_path(related_model)

    return described


def _describe_nested_serializer(
    described: Dict[str, Any],
    field: Any,
    depth: int,
    seen: Tuple[Any, ...],
) -> Dict[str, Any]:
    """
    Expand a nested serializer instance in place.

    ``many=True`` arrives here as ListSerializer, which has no ``fields``, so
    describe_field routes it through its ``child`` and this only ever sees a
    concrete Serializer.
    """
    serializer_class = type(field)
    described["type"] = "object"
    described["serializer"] = dotted_path(serializer_class)

    if serializer_class in seen:
        described["truncated"] = True
        described["truncated_reason"] = "recursive serializer"
        return described

    if depth >= MAX_DEPTH:
        described["truncated"] = True
        described["truncated_reason"] = f"nesting deeper than {MAX_DEPTH} levels"
        return described

    try:
        nested_fields = dict(field.fields)
    except Exception as exc:  # noqa: BLE001
        described["unresolved"] = True
        described["unresolved_reason"] = f"{type(exc).__name__}: {exc}"
        return described

    described["properties"] = [
        describe_field(nested_name, nested, depth + 1, seen + (serializer_class,))
        for nested_name, nested in nested_fields.items()
    ]
    return described


def describe_serializer(serializer_class: Any) -> Optional[Dict[str, Any]]:
    """
    Describe a serializer class as a list of field descriptors.

    Returns None when the argument is not a serializer class.
    """
    if serializer_class is None:
        return None
    if not (isinstance(serializer_class, type) and hasattr(serializer_class, "_declared_fields")):
        return None

    fields, how, error = _bound_fields(serializer_class)
    described: Dict[str, Any] = {
        "class": dotted_path(serializer_class),
        "file": _source_file(serializer_class),
        "introspection": how,
        "fields": [
            describe_field(name, field, 0, (serializer_class,))
            for name, field in fields.items()
        ],
    }
    if error:
        described["introspection_error"] = error
    meta = _describe_meta(serializer_class)
    if meta:
        described["meta"] = meta
    return described


def unresolved_field_names(described: Optional[Dict[str, Any]]) -> List[str]:
    """Collect dotted names of fields whose shape introspection could not infer."""
    if not described:
        return []

    found: List[str] = []

    def walk(fields: List[Dict[str, Any]], prefix: str) -> None:
        for field in fields:
            name = field.get("name")
            path = f"{prefix}{name}" if name else prefix.rstrip(".")
            if field.get("unresolved"):
                found.append(path)
            nested = field.get("properties")
            if nested:
                walk(nested, f"{path}.")
            items = field.get("items")
            if items:
                walk([items], f"{path}[].")
            values = field.get("additional_properties")
            if values:
                walk([values], f"{path}{{}}.")

    walk(described.get("fields", []), "")
    return found
