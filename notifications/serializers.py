from rest_framework import serializers

from notifications.models import DEVICE_PLATFORMS, MemberNotification, StaffAnnouncement


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
    language = serializers.ChoiceField(
        choices=[("bn", "bn"), ("en", "en")], required=False
    )


class FcmDeviceDeleteInput(serializers.Serializer):
    token = serializers.CharField(max_length=512)


class FcmDeviceRegisteredOutput(serializers.Serializer):
    id = serializers.CharField()
    platform = serializers.CharField()


class FcmDeviceDeletedOutput(serializers.Serializer):
    deleted = serializers.IntegerField()


class NotificationsReadAllOutput(serializers.Serializer):
    updated = serializers.IntegerField()


class AdminAnnouncementCreatedBy(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    short_id = serializers.CharField(allow_blank=True)


class AdminAnnouncementSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    body = serializers.CharField()
    scope = serializers.CharField()
    member_id = serializers.UUIDField(allow_null=True)
    recipient_count = serializers.IntegerField()
    send_push_requested = serializers.BooleanField()
    send_sms_requested = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    created_by = AdminAnnouncementCreatedBy(allow_null=True)


class AdminAnnouncementInput(serializers.Serializer):
    scope = serializers.ChoiceField(choices=["member", "active"])
    member_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=120)
    body = serializers.CharField(max_length=500)
    send_push = serializers.BooleanField(default=True)
    send_sms = serializers.BooleanField(default=False)

    def validate(self, attrs):
        if attrs["scope"] == "member" and not attrs.get("member_id"):
            raise serializers.ValidationError(
                {"member_id": "Required when scope is member."}
            )
        return attrs


class AdminAnnouncementUpdateInput(serializers.Serializer):
    title = serializers.CharField(max_length=120, required=False)
    body = serializers.CharField(max_length=500, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide title and/or body.")
        return attrs


class AdminAnnouncementCreateOutput(AdminAnnouncementSerializer):
    """Campaign fields plus push/SMS delivery summary and legacy `created` alias."""

    created = serializers.IntegerField()
    push_requested = serializers.BooleanField()
    push_sent = serializers.IntegerField()
    push_failed = serializers.IntegerField()
    push_skipped_no_device = serializers.IntegerField()
    push_skipped_disabled = serializers.IntegerField()
    sms_requested = serializers.BooleanField()
    sms_sent = serializers.IntegerField()
    sms_failed = serializers.IntegerField()
    sms_skipped_disabled = serializers.IntegerField()
    sms_skipped_no_phone = serializers.IntegerField()


class AdminAnnouncementResendOutput(serializers.Serializer):
    push_sent = serializers.IntegerField()
    push_failed = serializers.IntegerField()
    push_skipped_no_device = serializers.IntegerField()
    push_skipped_disabled = serializers.IntegerField()


class AdminAnnouncementResendSmsOutput(serializers.Serializer):
    sms_sent = serializers.IntegerField()
    sms_failed = serializers.IntegerField()
    sms_skipped_disabled = serializers.IntegerField()
    sms_skipped_no_phone = serializers.IntegerField()


class OpsAlertRecipientSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    short_id = serializers.CharField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True)


class OpsAlertSettingsSerializer(serializers.Serializer):
    enrollment_live_enabled = serializers.BooleanField()
    daily_digest_enabled = serializers.BooleanField()
    recipients = OpsAlertRecipientSerializer(many=True)


class OpsAlertSettingsUpdateInput(serializers.Serializer):
    enrollment_live_enabled = serializers.BooleanField(required=False)
    daily_digest_enabled = serializers.BooleanField(required=False)
    recipient_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
    )


def announcement_payload(campaign: StaffAnnouncement, *, recipient_count: int | None = None) -> dict:
    if recipient_count is None:
        recipient_count = MemberNotification.objects.filter(
            code="announcement",
            related_object_id=str(campaign.pk),
        ).count()
    created_by = None
    actor = campaign.created_by
    if actor is not None:
        profile = getattr(actor, "staff_profile", None)
        created_by = {
            "id": actor.pk,
            "name": actor.full_name or "",
            "short_id": getattr(profile, "short_id", "") or "",
        }
    return {
        "id": campaign.pk,
        "title": campaign.title,
        "body": campaign.body,
        "scope": campaign.scope,
        "member_id": campaign.member_id,
        "recipient_count": recipient_count,
        "send_push_requested": campaign.send_push_requested,
        "send_sms_requested": campaign.send_sms_requested,
        "created_at": campaign.created_at,
        "created_by": created_by,
    }
