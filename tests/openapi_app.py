"""Views and serializers exercised by the OpenAPI inventory tests."""
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from weni_commons.kong import api_gateway_expose


class TagSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Display name of the tag")
    weight = serializers.IntegerField(required=False, max_value=100)


class ContactReadSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(read_only=True, help_text="Contact identifier")
    name = serializers.CharField(max_length=64, allow_null=True)
    status = serializers.ChoiceField(choices=["active", "blocked"])
    created_on = serializers.DateTimeField(read_only=True)
    tags = TagSerializer(many=True, required=False)
    urns = serializers.ListField(child=serializers.CharField())
    profile = TagSerializer(required=False)
    summary = serializers.SerializerMethodField()

    def get_summary(self, obj):  # pragma: no cover - shape is intentionally opaque
        return ""


class ContactWriteSerializer(serializers.Serializer):
    name = serializers.CharField()
    # DictField also has a `child`, which used to be mistaken for a list.
    fields = serializers.DictField(child=serializers.CharField(allow_null=True))


class BrokenSerializer(serializers.Serializer):
    declared = serializers.CharField(help_text="Only reachable without instantiating")

    def __init__(self, *args, **kwargs):
        raise RuntimeError("needs context")


@api_gateway_expose(alias="contacts", methods=["GET"])
class ContactsEndpoint(APIView):
    serializer_class = ContactReadSerializer
    write_serializer_class = ContactWriteSerializer
    permission_classes = []
    authentication_classes = []
    throttle_scope = "v2"

    def get(self, request, *args, **kwargs):  # pragma: no cover
        return Response([])

    # Implemented but not allowed through the gateway — drives method_mismatch.
    def post(self, request, *args, **kwargs):  # pragma: no cover
        return Response({})

    def delete(self, request, *args, **kwargs):  # pragma: no cover
        return Response({})


@api_gateway_expose
class WorkspaceEndpoint(APIView):
    serializer_class = TagSerializer

    def get(self, request, *args, **kwargs):  # pragma: no cover
        return Response({})


@api_gateway_expose(alias="reports")
class ReportsEndpoint(APIView):
    def get(self, request, *args, **kwargs):  # pragma: no cover
        return Response({})


@api_gateway_expose(alias="things/{thing_id}", methods=["GET", "DELETE"])
class ThingEndpoint(APIView):
    serializer_class = BrokenSerializer

    def get(self, request, thing_id, *args, **kwargs):  # pragma: no cover
        return Response({})

    def delete(self, request, thing_id, *args, **kwargs):  # pragma: no cover
        return Response({})


class DashboardViewSet(viewsets.GenericViewSet):
    serializer_class = TagSerializer

    @api_gateway_expose(alias="dashboards/{pk}/widgets", service="insights-service")
    @action(detail=True, methods=["get"])
    def widgets(self, request, pk=None):  # pragma: no cover
        return Response([])
