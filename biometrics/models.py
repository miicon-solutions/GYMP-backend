from django.db import models

from core.models import Entity
from members.models import MemberProfile


class FingerprintDevice(Entity):
    name = models.CharField(max_length=120)
    lan_ip = models.CharField(max_length=64)
    port = models.PositiveIntegerField(default=4370)
    serial = models.CharField(max_length=120, blank=True)
    firmware = models.CharField(max_length=120, blank=True)
    user_count = models.PositiveIntegerField(default=0)
    comm_password_enc = models.TextField(blank=True)
    bridge_device_id = models.CharField(max_length=64, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)
    scanner_online = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta(Entity.Meta):
        constraints = [
            models.UniqueConstraint(fields=["lan_ip", "port"], name="fingerprint_device_lan_port"),
        ]

    def __str__(self):
        return f"{self.name} ({self.lan_ip}:{self.port})"


class MemberBiometricTemplate(Entity):
    member = models.ForeignKey(
        MemberProfile, on_delete=models.CASCADE, related_name="biometric_templates"
    )
    finger_index = models.PositiveSmallIntegerField()
    algorithm = models.CharField(max_length=32, default="zk")
    template_format = models.CharField(max_length=32, default="zk")
    template_ciphertext = models.TextField()
    template_sha256 = models.CharField(max_length=64)
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta(Entity.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["member", "finger_index"], name="member_biometric_finger"
            ),
            models.CheckConstraint(
                condition=models.Q(finger_index__gte=0, finger_index__lte=9),
                name="member_biometric_finger_range",
            ),
        ]


class StaffBiometricTemplate(Entity):
    staff = models.ForeignKey(
        "accounts.StaffProfile",
        on_delete=models.CASCADE,
        related_name="biometric_templates",
    )
    finger_index = models.PositiveSmallIntegerField()
    algorithm = models.CharField(max_length=32, default="zk")
    template_format = models.CharField(max_length=32, default="zk")
    template_ciphertext = models.TextField()
    template_sha256 = models.CharField(max_length=64)
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta(Entity.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "finger_index"], name="staff_biometric_finger"
            ),
            models.CheckConstraint(
                condition=models.Q(finger_index__gte=0, finger_index__lte=9),
                name="staff_biometric_finger_range",
            ),
        ]


class FingerprintDeviceSyncState(models.Model):
    device = models.ForeignKey(
        FingerprintDevice, on_delete=models.CASCADE, related_name="sync_states"
    )
    member = models.ForeignKey(
        MemberProfile, on_delete=models.CASCADE, related_name="device_sync_states"
    )
    templates_synced_at = models.DateTimeField(null=True, blank=True)
    pin_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device", "member"], name="fingerprint_device_member_sync"
            ),
        ]


class FingerprintDeviceStaffSyncState(models.Model):
    device = models.ForeignKey(
        FingerprintDevice, on_delete=models.CASCADE, related_name="staff_sync_states"
    )
    staff = models.ForeignKey(
        "accounts.StaffProfile",
        on_delete=models.CASCADE,
        related_name="device_sync_states",
    )
    templates_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device", "staff"], name="fingerprint_device_staff_sync"
            ),
        ]


class BridgeDeviceJob(Entity):
    """Outbound command for the LAN bridge worker (bridge polls and completes)."""

    KIND_DEVICE_STATUS = "device_status"
    KIND_ENSURE_USER = "ensure_user"
    KIND_ENROLL = "enroll"
    KIND_ENROLL_SESSION = "enroll_session"
    KIND_GET_TEMPLATES = "get_templates"
    KIND_PUSH_USER = "push_user"
    KIND_DELETE_FINGERPRINT = "delete_fingerprint"
    KIND_CHOICES = (
        (KIND_DEVICE_STATUS, KIND_DEVICE_STATUS),
        (KIND_ENSURE_USER, KIND_ENSURE_USER),
        (KIND_ENROLL, KIND_ENROLL),
        (KIND_ENROLL_SESSION, KIND_ENROLL_SESSION),
        (KIND_GET_TEMPLATES, KIND_GET_TEMPLATES),
        (KIND_PUSH_USER, KIND_PUSH_USER),
        (KIND_DELETE_FINGERPRINT, KIND_DELETE_FINGERPRINT),
    )

    STATUS_PENDING = "pending"
    STATUS_CLAIMED = "claimed"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = (
        (STATUS_PENDING, STATUS_PENDING),
        (STATUS_CLAIMED, STATUS_CLAIMED),
        (STATUS_SUCCEEDED, STATUS_SUCCEEDED),
        (STATUS_FAILED, STATUS_FAILED),
        (STATUS_EXPIRED, STATUS_EXPIRED),
    )

    kind = models.CharField(max_length=40, choices=KIND_CHOICES, db_index=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    bridge_device_id = models.CharField(max_length=64, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=120, blank=True, db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta(Entity.Meta):
        indexes = [
            models.Index(fields=["status", "created_at"], name="bridge_job_status_created"),
        ]
