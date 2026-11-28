from django.urls import path
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import StaffOrMember
from core.endpoints import endpoint
from notifications import services
from notifications.serializers import (
    FcmDeviceDeletedOutput,
    FcmDeviceDeleteInput,
    FcmDeviceInput,
    FcmDeviceRegisteredOutput,
    MemberNotificationSerializer,
    NotificationsReadAllOutput,
)
from notifications.views import (
    AnnouncementDetail,
    AnnouncementList,
    AnnouncementResendPush,
    AnnouncementResendSms,
    OpsAlertSettingsView,
)


def _list_notifications(request, data):
    return MemberNotificationSerializer(services.list_for_member(request.user), many=True).data


def _mark_read(request, data, pk):
    return MemberNotificationSerializer(services.mark_read(request.user, pk)).data


def _mark_all_read(request, data):
    return services.mark_all_read(request.user)


class FcmDeviceView(APIView):
    """Register or remove an FCM device token for the signed-in member or staff."""

    permission_classes = [StaffOrMember]

    @extend_schema(
        request=FcmDeviceInput,
        responses={200: FcmDeviceRegisteredOutput},
        tags=["notifications"],
        operation_id="member_devices_fcm_register",
    )
    def post(self, request):
        serializer = FcmDeviceInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        device = services.register_device(
            request.user,
            data["token"],
            data["platform"],
            language=data.get("language"),
        )
        return Response({"id": str(device.pk), "platform": device.platform})

    @extend_schema(
        request=FcmDeviceDeleteInput,
        responses={200: FcmDeviceDeletedOutput},
        tags=["notifications"],
        operation_id="member_devices_fcm_unregister",
    )
    def delete(self, request):
        serializer = FcmDeviceDeleteInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(services.unregister_device(request.user, serializer.validated_data["token"]))


urlpatterns = [
    path(
        "member/notifications/",
        endpoint(
            "member_notifications_list",
            handler=_list_notifications,
            method="get",
            response=MemberNotificationSerializer(many=True),
            permission=StaffOrMember,
            tags=["notifications"],
        ),
    ),
    path(
        "member/notifications/read-all/",
        endpoint(
            "member_notifications_read_all",
            handler=_mark_all_read,
            response=NotificationsReadAllOutput,
            permission=StaffOrMember,
            tags=["notifications"],
        ),
    ),
    path(
        "member/notifications/<uuid:pk>/read/",
        endpoint(
            "member_notifications_read",
            handler=_mark_read,
            response=MemberNotificationSerializer,
            permission=StaffOrMember,
            tags=["notifications"],
        ),
    ),
    path("member/devices/fcm/", FcmDeviceView.as_view()),
    path("admin/notifications/", AnnouncementList.as_view()),
    path("admin/notifications/<uuid:pk>/", AnnouncementDetail.as_view()),
    path(
        "admin/notifications/<uuid:pk>/resend-push/",
        AnnouncementResendPush.as_view(),
    ),
    path(
        "admin/notifications/<uuid:pk>/resend-sms/",
        AnnouncementResendSms.as_view(),
    ),
    path("admin/ops-alerts/settings/", OpsAlertSettingsView.as_view()),
]
