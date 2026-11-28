from django.conf import settings
from django.db import models

from core.models import Entity

NOTIFICATION_KINDS = [
    ("membership", "membership"),
    ("payment", "payment"),
    ("attendance", "attendance"),
    ("general", "general"),
]

NOTIFICATION_CODES = [
    ("payment_received", "payment_received"),
    ("cash_request", "cash_request"),
    ("cash_request_rejected", "cash_request_rejected"),
    ("cash_request_accepted", "cash_request_accepted"),
    ("cash_request_staff_rejected", "cash_request_staff_rejected"),
    ("membership_activated", "membership_activated"),
    ("fingerprint_ready", "fingerprint_ready"),
    ("membership_expiring", "membership_expiring"),
    ("membership_expired", "membership_expired"),
    ("announcement", "announcement"),
    ("admin_enrollment", "admin_enrollment"),
    ("admin_daily_enrollments", "admin_daily_enrollments"),
    ("music_request", "music_request"),
    ("music_request_approved", "music_request_approved"),
    ("music_request_rejected", "music_request_rejected"),
    ("music_request_staff_approved", "music_request_staff_approved"),
    ("music_request_staff_rejected", "music_request_staff_rejected"),
]

ANNOUNCEMENT_SCOPES = [
    ("member", "member"),
    ("active", "active"),
]

DEVICE_PLATFORMS = [
    ("ios", "ios"),
    ("android", "android"),
]


class StaffAnnouncement(Entity):
    """Staff-facing announcement campaign; fans out to MemberNotification rows."""

    title = models.CharField(max_length=120)
    body = models.TextField()
    scope = models.CharField(max_length=16, choices=ANNOUNCEMENT_SCOPES)
    member_id = models.UUIDField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_announcements",
    )
    send_push_requested = models.BooleanField(default=True)
    send_sms_requested = models.BooleanField(default=False)

    class Meta(Entity.Meta):
        indexes = [
            models.Index(fields=["-created_at"], name="staff_announce_created_idx"),
        ]


class MemberNotification(Entity):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField(max_length=16, choices=NOTIFICATION_KINDS)
    code = models.CharField(max_length=40, choices=NOTIFICATION_CODES, db_index=True)
    title_key = models.CharField(max_length=80, blank=True, default="")
    body_key = models.CharField(max_length=80, blank=True, default="")
    title_params = models.JSONField(default=dict, blank=True)
    body_params = models.JSONField(default=dict, blank=True)
    title = models.CharField(max_length=120, blank=True, default="")
    body = models.TextField(blank=True, default="")
    is_unread = models.BooleanField(default=True, db_index=True)
    related_object_id = models.CharField(max_length=64, blank=True, default="")
    dedupe_key = models.CharField(max_length=64, blank=True, default="")
    send_push = models.BooleanField(default=False)
    send_sms = models.BooleanField(default=False)

    class Meta(Entity.Meta):
        indexes = [
            models.Index(fields=["user", "is_unread"], name="notif_user_unread_idx"),
            models.Index(fields=["user", "-created_at"], name="notif_user_created_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "code", "related_object_id"],
                condition=~models.Q(related_object_id=""),
                name="notif_user_code_related_uniq",
            ),
            models.UniqueConstraint(
                fields=["user", "code", "dedupe_key"],
                condition=~models.Q(dedupe_key=""),
                name="notif_user_code_dedupe_uniq",
            ),
        ]


class MemberDeviceToken(Entity):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_devices",
    )
    token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(max_length=16, choices=DEVICE_PLATFORMS)

    class Meta(Entity.Meta):
        indexes = [
            models.Index(fields=["user"], name="notif_device_user_idx"),
        ]


class AdminOpsAlertSettings(Entity):
    """Singleton toggles for cron-driven admin ops alerts."""

    enrollment_live_enabled = models.BooleanField(default=True)
    daily_digest_enabled = models.BooleanField(default=True)

    @classmethod
    def load(cls) -> "AdminOpsAlertSettings":
        obj = cls.objects.order_by("created_at").first()
        if obj is None:
            obj = cls.objects.create()
        return obj


class AdminOpsAlertRecipient(Entity):
    """Staff user selected to receive ops-alert fan-out (super configures)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ops_alert_recipient",
    )

    class Meta(Entity.Meta):
        indexes = [
            models.Index(fields=["user"], name="ops_alert_recipient_user_idx"),
        ]
