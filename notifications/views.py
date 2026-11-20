from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.response import Response

from core.api import StaffPermission
from notifications import services
from notifications.models import StaffAnnouncement
from notifications.serializers import (
    AdminAnnouncementCreateOutput,
    AdminAnnouncementInput,
    AdminAnnouncementResendOutput,
    AdminAnnouncementSerializer,
    AdminAnnouncementUpdateInput,
    announcement_payload,
)


def _method_permissions(mapping):
    def get_permissions(self):
        code = mapping.get(self.request.method)
        if code is None:
            return [StaffPermission("notifications.view")()]
        return [StaffPermission(code)()]

    return get_permissions


class AnnouncementList(generics.ListCreateAPIView):
    serializer_class = AdminAnnouncementSerializer
    get_permissions = _method_permissions(
        {"GET": "notifications.view", "POST": "notifications.create"}
    )

    def get_queryset(self):
        return services.list_announcements()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = page if page is not None else queryset
        data = [announcement_payload(c) for c in rows]
        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)

    @extend_schema(
        request=AdminAnnouncementInput,
        responses={201: AdminAnnouncementCreateOutput},
    )
    def post(self, request, *args, **kwargs):
        serializer = AdminAnnouncementInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = services.send_announcement(request.user, serializer.validated_data)
        return Response(payload, status=201)


class AnnouncementDetail(generics.GenericAPIView):
    serializer_class = AdminAnnouncementSerializer
    queryset = StaffAnnouncement.objects.all()
    get_permissions = _method_permissions(
        {
            "GET": "notifications.view",
            "PATCH": "notifications.update",
            "DELETE": "notifications.delete",
        }
    )

    def get_object(self):
        return services.get_announcement(self.kwargs["pk"])

    def get(self, request, *args, **kwargs):
        return Response(announcement_payload(self.get_object()))

    @extend_schema(request=AdminAnnouncementUpdateInput, responses=AdminAnnouncementSerializer)
    def patch(self, request, *args, **kwargs):
        data = AdminAnnouncementUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return Response(
            services.update_announcement(request.user, self.kwargs["pk"], data.validated_data)
        )

    def delete(self, request, *args, **kwargs):
        services.delete_announcement(request.user, self.kwargs["pk"])
        return Response(status=204)


class AnnouncementResendPush(generics.GenericAPIView):
    serializer_class = AdminAnnouncementResendOutput
    permission_classes = [StaffPermission("notifications.create")]

    @extend_schema(request=None, responses=AdminAnnouncementResendOutput)
    def post(self, request, *args, **kwargs):
        return Response(services.resend_announcement_push(request.user, self.kwargs["pk"]))
