"""URL conf used by the OpenAPI inventory tests."""
from django.urls import path
from rest_framework.routers import SimpleRouter
from rest_framework.urlpatterns import format_suffix_patterns

from tests.openapi_app import (
    ContactsEndpoint,
    DashboardViewSet,
    ReportsEndpoint,
    ThingEndpoint,
    WorkspaceEndpoint,
)

router = SimpleRouter()
router.register("dashboards", DashboardViewSet, basename="dashboard")

# format_suffix_patterns registers each view twice, with and without .json —
# the same shape real projects have, so the inventory is exercised against it.
urlpatterns = format_suffix_patterns(
    [
        path("api/v2/contacts", ContactsEndpoint.as_view(), name="contacts"),
        path("api/v2/workspace", WorkspaceEndpoint.as_view(), name="workspace"),
        path("api/v2/reports", ReportsEndpoint.as_view(), name="reports"),
        path("api/v2/things/<uuid:thing_id>", ThingEndpoint.as_view(), name="thing"),
    ]
) + router.urls
