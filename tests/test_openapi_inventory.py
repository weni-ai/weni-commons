import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from weni_commons.openapi.inventory import build_inventory

PREFIX = "/flows"


@pytest.fixture(autouse=True)
def gateway_urlconf(settings, monkeypatch):
    settings.ROOT_URLCONF = "tests.openapi_urls"
    monkeypatch.setenv("KONG_URL_PREFIX", PREFIX)


def inventory(**kwargs):
    return build_inventory(url_prefix=PREFIX, **kwargs)


def route(built, name):
    for entry in built["routes"]:
        if entry["route_name"] == name:
            return entry
    raise AssertionError(f"{name} not in {[r['route_name'] for r in built['routes']]}")


def codes(built, code):
    return [warning for warning in built["warnings"] if warning["code"] == code]


def fields_by_name(described):
    return {field["name"]: field for field in described["fields"]}


def test_alias_route_is_documented_at_its_flat_public_path():
    contacts = route(inventory(), "allow-contacts")

    assert contacts["public_path"] == "/contacts"
    assert contacts["upstream_path"] == "/api/v2/contacts.json"
    assert contacts["gateway_methods"] == ["GET"]
    assert contacts["compat_paths"] == ["/flows/contacts", "/flows/api/v2/contacts.json"]
    assert contacts["service"] == "flows-service"
    assert contacts["view"]["class"].endswith("ContactsEndpoint")
    assert contacts["view"]["line"] > 0
    assert contacts["throttle"] == {"scope": "v2"}


def test_format_suffix_twin_is_not_reported_as_a_duplicate():
    built = inventory()

    assert codes(built, "duplicate_route_name") == []
    assert built["route_count"] == 5


def test_route_without_alias_keeps_the_prefix_and_is_flagged():
    built = inventory()
    workspace = route(built, "allow-api-v2-workspace-json")

    assert workspace["public_path"] == "/flows/api/v2/workspace.json"
    assert workspace["compat_paths"] == []
    assert workspace["alias"] is None

    warning = codes(built, "missing_alias")[0]
    assert warning["route"] == "allow-api-v2-workspace-json"
    assert "no customer-facing URL yet" in warning["message"]


def test_methods_the_gateway_blocks_are_reported_not_documented():
    built = inventory()
    contacts = route(built, "allow-contacts")

    assert contacts["view_methods"] == ["DELETE", "GET", "POST"]
    assert contacts["gateway_methods"] == ["GET"]

    warning = codes(built, "method_mismatch")[0]
    assert warning["route"] == "allow-contacts"
    assert "implements DELETE, POST" in warning["message"]


def test_viewset_action_resolves_alias_captures_and_service():
    widgets = route(inventory(), "allow-dashboards-pk-widgets")

    assert widgets["public_path"] == "/dashboards/{pk}/widgets"
    assert widgets["rewrite_mode"] == "alias_captures"
    assert widgets["service"] == "insights-service"
    assert widgets["path_params"] == [{"name": "pk", "type": "string"}]


def test_uuid_path_param_is_typed_from_the_django_converter():
    thing = route(inventory(), "allow-things-thing_id")

    assert thing["public_path"] == "/things/{thing_id}"
    assert thing["path_params"] == [
        {
            "name": "thing_id",
            "type": "string",
            "format": "uuid",
            "converter": "UUIDConverter",
        }
    ]


def test_serializer_fields_carry_types_and_metadata():
    contacts = route(inventory(), "allow-contacts")
    read = contacts["serializers"]["read"]

    assert read["attribute"] == "serializer_class"
    assert read["introspection"] == "bound"

    fields = fields_by_name(read)
    assert fields["uuid"] == {
        "name": "uuid",
        "field_class": "UUIDField",
        "required": False,
        "read_only": True,
        "write_only": False,
        "allow_null": False,
        "help_text": "Contact identifier",
        "type": "string",
        "format": "uuid",
    }
    assert fields["name"]["allow_null"] is True
    assert fields["name"]["max_length"] == 64
    assert fields["status"]["enum"] == ["active", "blocked"]
    assert fields["created_on"]["format"] == "date-time"


def test_nested_and_list_fields_are_expanded():
    contacts = route(inventory(), "allow-contacts")
    fields = fields_by_name(contacts["serializers"]["read"])

    tags = fields["tags"]
    assert tags["type"] == "array"
    nested = {field["name"]: field for field in tags["items"]["properties"]}
    assert tags["items"]["type"] == "object"
    assert nested["name"]["type"] == "string"
    assert nested["name"]["help_text"] == "Display name of the tag"
    assert nested["weight"]["max_value"] == 100

    assert fields["urns"]["type"] == "array"
    assert fields["urns"]["items"]["type"] == "string"

    assert fields["profile"]["type"] == "object"
    assert fields["profile"]["serializer"].endswith("TagSerializer")


def test_method_field_is_reported_as_unresolved():
    built = inventory()
    fields = fields_by_name(route(built, "allow-contacts")["serializers"]["read"])

    assert fields["summary"]["type"] is None
    assert fields["summary"]["unresolved"] is True

    warning = codes(built, "unresolved_fields")[0]
    assert "summary" in warning["message"]


def test_write_serializer_is_described_separately():
    contacts = route(inventory(), "allow-contacts")

    write = contacts["serializers"]["write"]
    assert write["attribute"] == "write_serializer_class"
    assert list(fields_by_name(write)) == ["name", "fields"]


def test_dict_field_is_an_object_keyed_by_its_child():
    contacts = route(inventory(), "allow-contacts")
    dict_field = fields_by_name(contacts["serializers"]["write"])["fields"]

    assert dict_field["type"] == "object"
    assert dict_field["additional_properties"]["type"] == "string"
    assert dict_field["additional_properties"]["allow_null"] is True
    assert "items" not in dict_field


def test_serializer_that_cannot_be_instantiated_falls_back_to_declared_fields():
    built = inventory()
    read = route(built, "allow-things-thing_id")["serializers"]["read"]

    assert read["introspection"] == "declared"
    assert "needs context" in read["introspection_error"]
    assert list(fields_by_name(read)) == ["declared"]

    warning = codes(built, "serializer_declared_only")[0]
    assert "model fields are missing" in warning["message"]


def test_view_without_serializer_is_reported():
    built = inventory()
    reports = route(built, "allow-reports")

    assert reports["serializers"] == {}
    warning = codes(built, "no_serializer")[0]
    assert warning["route"] == "allow-reports"


def test_service_filter_keeps_only_that_services_routes():
    built = inventory(service="insights-service")

    assert built["service_filter"] == "insights-service"
    assert [entry["route_name"] for entry in built["routes"]] == [
        "allow-dashboards-pk-widgets"
    ]


def test_warnings_are_attached_to_their_route_and_to_the_summary():
    built = inventory()
    contacts = route(built, "allow-contacts")

    assert [warning["code"] for warning in contacts["warnings"]] == [
        "method_mismatch",
        "unresolved_fields",
    ]
    assert all(warning in built["warnings"] for warning in contacts["warnings"])


def test_command_writes_the_inventory_to_a_file(tmp_path, settings):
    settings.ROOT_URLCONF = "tests.openapi_urls"
    out = tmp_path / "nested" / "inventory.json"

    call_command("api_gateway_inventory", "--out", str(out), "--url-prefix", PREFIX)

    written = json.loads(out.read_text())
    assert written["url_prefix"] == PREFIX
    assert written["route_count"] == 5
    assert written["inventory_version"] == 1


def test_command_prints_json_to_stdout():
    stdout = StringIO()

    call_command("api_gateway_inventory", "--url-prefix", PREFIX, stdout=stdout)

    assert json.loads(stdout.getvalue())["route_count"] == 5


def test_command_requires_url_prefix(monkeypatch):
    monkeypatch.delenv("KONG_URL_PREFIX", raising=False)

    with pytest.raises(CommandError) as excinfo:
        call_command("api_gateway_inventory")

    assert "KONG_URL_PREFIX" in str(excinfo.value)


def test_command_can_fail_on_warnings():
    with pytest.raises(CommandError) as excinfo:
        call_command(
            "api_gateway_inventory",
            "--url-prefix",
            PREFIX,
            "--fail-on-warnings",
            stdout=StringIO(),
        )

    assert "warning(s) reported" in str(excinfo.value)
