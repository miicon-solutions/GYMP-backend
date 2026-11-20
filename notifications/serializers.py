from rest_framework import serializers

from notifications.models import DEVICE_PLATFORMS, MemberNotification


class MemberNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = MemberNotification
        fields = (
            "id",
            "kind",
            "code",
            "title_key",
            "body_key",
            "title_params",
            "body_params",
            "title",
            "body",
            "is_unread",
            "created_at",
            "related_object_id",
        )
        read_only_fields = fields


class FcmDeviceInput(serializers.Serializer):
    token = serializers.CharField(max_length=512)
    platform = serializers.ChoiceField(choices=DEVICE_PLATFORMS)


class FcmDeviceDeleteInput(serializers.Serializer):
    token = serializers.CharField(max_length=512)


class FcmDeviceRegisteredOutput(serializers.Serializer):
    id = serializers.CharField()
    platform = serializers.CharField()


class FcmDeviceDeletedOutput(serializers.Serializer):
    deleted = serializers.IntegerField()


class NotificationsReadAllOutput(serializers.Serializer):
    updated = serializers.IntegerField()


class AdminAnnouncementInput(serializers.Serializer):
    scope = serializers.ChoiceField(choices=["member", "active"])
    member_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=120)
    body = serializers.CharField(max_length=500)
    send_push = serializers.BooleanField(default=True)

    def validate(self, attrs):
        if attrs["scope"] == "member" and not attrs.get("member_id"):
            raise serializers.ValidationError(
                {"member_id": "Required when scope is member."}
            )
        return attrs


class AdminAnnouncementOutput(serializers.Serializer):
    created = serializers.IntegerField()
    push_requested = serializers.BooleanField()
    push_sent = serializers.IntegerField(required=False, default=0)
    push_failed = serializers.IntegerField(required=False, default=0)
    push_skipped_no_device = serializers.IntegerField(required=False, default=0)
    push_skipped_disabled = serializers.IntegerField(required=False, default=0)
