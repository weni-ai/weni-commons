"""
Tests for Weni auth permission classes.
"""

from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from weni_commons.auth.context import WeniAuthContext
from weni_commons.auth.permissions import (
    CanCommunicateInternally,
    HasProjectPermission,
    IsWeniAuthenticated,
    PermissionLevel,
)

User = get_user_model()


class AuthPermissionTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password",
        )

        content_type = ContentType.objects.get_for_model(User)
        self.internal_permission, _ = Permission.objects.get_or_create(
            codename="can_communicate_internally",
            name="can communicate internally",
            content_type=content_type,
        )

    def _make_request(self, django_request, user=None, auth_context=None):
        if user is not None:
            force_authenticate(django_request, user=user)
        request = Request(django_request)
        request.auth = auth_context
        return request

    def test_is_weni_authenticated_requires_auth_context(self):
        django_request = self.factory.get("/")
        request = self._make_request(django_request)

        self.assertFalse(IsWeniAuthenticated().has_permission(request, None))

    def test_is_weni_authenticated_accepts_auth_context(self):
        auth_context = WeniAuthContext(project_uuid="project-123")
        django_request = self.factory.get("/")
        request = self._make_request(django_request, auth_context=auth_context)

        self.assertTrue(IsWeniAuthenticated().has_permission(request, None))

    def test_can_communicate_internally_from_auth_context(self):
        auth_context = WeniAuthContext(is_internal=True)
        django_request = self.factory.get("/")
        request = self._make_request(django_request, auth_context=auth_context)

        self.assertTrue(CanCommunicateInternally().has_permission(request, None))

    def test_can_communicate_internally_from_user_permission(self):
        self.user.user_permissions.add(self.internal_permission)
        auth_context = WeniAuthContext(is_internal=False)
        django_request = self.factory.get("/")
        request = self._make_request(
            django_request,
            user=self.user,
            auth_context=auth_context,
        )

        self.assertTrue(CanCommunicateInternally().has_permission(request, None))

    def test_has_project_permission_requires_permissions_service(self):
        auth_context = WeniAuthContext(project_uuid="project-123")
        django_request = self.factory.get("/")
        request = self._make_request(
            django_request,
            user=self.user,
            auth_context=auth_context,
        )

        self.assertFalse(HasProjectPermission().has_permission(request, None))

    def test_has_project_permission_internal_user_requires_user_email(self):
        auth_context = WeniAuthContext(
            project_uuid="project-123",
            is_internal=True,
        )
        django_request = self.factory.get("/", HTTP_PROJECT_UUID="project-123")
        request = self._make_request(django_request, auth_context=auth_context)
        permissions_service = Mock()

        permission = HasProjectPermission(permissions_service=permissions_service)
        self.assertFalse(permission.has_permission(request, None))
        permissions_service.get_user_permissions.assert_not_called()

    def test_has_project_permission_internal_user_success(self):
        auth_context = WeniAuthContext(
            project_uuid="project-123",
            is_internal=True,
        )
        django_request = self.factory.get(
            "/?user_email=other@example.com",
            HTTP_PROJECT_UUID="project-123",
        )
        request = self._make_request(django_request, auth_context=auth_context)

        permissions_service = Mock()
        permissions_service.get_user_permissions.return_value = (
            200,
            {"project_authorization": PermissionLevel.contributor},
        )
        permission = HasProjectPermission(permissions_service=permissions_service)

        self.assertTrue(permission.has_permission(request, None))
        permissions_service.get_user_permissions.assert_called_once_with(
            "project-123",
            "other@example.com",
        )

    def test_has_project_permission_regular_user_success(self):
        auth_context = WeniAuthContext(
            project_uuid="project-123",
            user_email="test@example.com",
        )
        django_request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION="Bearer user-token",
        )
        request = self._make_request(
            django_request,
            user=self.user,
            auth_context=auth_context,
        )

        permissions_service = Mock()
        permissions_service.get_user_permissions.return_value = (
            200,
            {"project_authorization": PermissionLevel.moderator},
        )
        permission = HasProjectPermission(permissions_service=permissions_service)

        self.assertTrue(permission.has_permission(request, None))
        permissions_service.get_user_permissions.assert_called_once_with(
            "project-123",
            "test@example.com",
            "user-token",
        )

    def test_has_project_permission_regular_user_success_with_x_weni_auth(self):
        auth_context = WeniAuthContext(
            project_uuid="project-123",
            user_email="test@example.com",
        )
        django_request = self.factory.get(
            "/",
            HTTP_X_WENI_AUTH="user-token",
        )
        request = self._make_request(
            django_request,
            user=self.user,
            auth_context=auth_context,
        )

        permissions_service = Mock()
        permissions_service.get_user_permissions.return_value = (
            200,
            {"project_authorization": PermissionLevel.moderator},
        )
        permission = HasProjectPermission(permissions_service=permissions_service)

        self.assertTrue(permission.has_permission(request, None))
        permissions_service.get_user_permissions.assert_called_once_with(
            "project-123",
            "test@example.com",
            "user-token",
        )

    def test_has_project_permission_denies_insufficient_level(self):
        auth_context = WeniAuthContext(
            project_uuid="project-123",
            user_email="test@example.com",
        )
        django_request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION="Bearer user-token",
        )
        request = self._make_request(
            django_request,
            user=self.user,
            auth_context=auth_context,
        )

        permissions_service = Mock()
        permissions_service.get_user_permissions.return_value = (
            200,
            {"project_authorization": PermissionLevel.viewer},
        )
        permission = HasProjectPermission(permissions_service=permissions_service)

        self.assertFalse(permission.has_permission(request, None))
