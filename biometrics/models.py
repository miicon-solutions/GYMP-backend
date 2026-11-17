from django.db import models

from core.models import Entity
from members.models import MemberProfile


class FingerprintDevice(Entity):
    name = models.CharField(max_length=120)
    lan_ip = models.CharField(max_length=64)
    port = models.PositiveIntegerField(default=4370)
    serial = models.CharField(max_length=120, blank=True)
    comm_password_enc = models.TextField(blank=True)
    bridge_device_id = models.CharField(max_length=64, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)
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
