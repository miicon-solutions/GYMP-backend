import logging

from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from rest_framework import serializers
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import BasePermission
from rest_framework.views import exception_handler as drf_exception_handler


class Conflict(APIException):
    status_code = 409
    default_detail = "This change conflicts with an existing record."


class BadGateway(APIException):
    status_code = 502
    default_detail = "The service is unavailable. Try again."


class Pagination(CursorPagination):
    page_size = 50
    page_size_query_param = "limit"
    max_page_size = 100
    ordering = ("-created_at", "-id")


class MemberOnly(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_active and request.user.role == "member")


class AdminOnly(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_active and request.user.role == "admin")


class SuperOnly(AdminOnly):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.is_superuser


def require_admin(user, super_only=False):
    if (
        not user
        or not user.is_active
        or user.role != "admin"
        or (super_only and not user.is_superuser)
    ):
        raise PermissionDenied("Only authorized staff can do that.")


def exception_handler(exc, context):
    if isinstance(exc, (IntegrityError, ProtectedError)):
        exc = Conflict()
    elif isinstance(exc, ModelValidationError):
        exc = serializers.ValidationError(getattr(exc, "message_dict", exc.messages))
    if isinstance(exc, serializers.ValidationError) and isinstance(exc.detail, dict):
        exc.detail = {
            key: value if isinstance(value, (dict, list)) else [value]
            for key, value in exc.detail.items()
        }
    result = drf_exception_handler(exc, context)
    if result is None:
        logging.getLogger(__name__).error(
            {"event": "Unhandled API failure", "exception_type": type(exc).__name__}
        )
        from rest_framework.response import Response

        result = Response({"detail": "Something went wrong. Please try again."}, status=500)
    return result
