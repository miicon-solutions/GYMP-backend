from django.conf import settings
from django.db import models

from core.models import Entity


class MemberProfile(Entity):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="member_profile"
    )
    # PFT-#### until the first paid online or cash payment, then PF-####.
    member_id = models.CharField(max_length=10, unique=True)
    emergency_name = models.CharField(max_length=200, blank=True)
    emergency_relationship = models.CharField(max_length=12, blank=True)
    emergency_phone_e164 = models.CharField(max_length=14, blank=True)
    blood_group = models.CharField(max_length=8, default="Unknown")
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    sex = models.CharField(
        max_length=12,
        blank=True,
        default="",
        choices=[(x, x) for x in ("", "male", "female", "other")],
    )
    photo = models.FileField(blank=True)
    profile_complete = models.BooleanField(default=False)
    membership_status = models.CharField(
        max_length=20,
        default="none",
        choices=[(x, x) for x in ("none", "pending_payment", "active", "expired")],
    )
    plan = models.ForeignKey("plans.Plan", on_delete=models.PROTECT, null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    fingerprint_status = models.CharField(
        max_length=16,
        default="not_required",
        choices=[(x, x) for x in ("not_required", "pending", "ready", "failed")],
    )
    device_pin_enc = models.TextField(blank=True)
    device_pin_updated_at = models.DateTimeField(null=True, blank=True)
    # Optional digits-only ZK user id (keypad); display member_id stays PF-/PFT-.
    device_keypad_id = models.CharField(max_length=16, blank=True, db_index=True)
    recovery_sent_at = models.DateTimeField(null=True, blank=True)
    push_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=True)

    class Meta(Entity.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    membership_status__in=["none", "pending_payment", "active", "expired"]
                ),
                name="member_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    fingerprint_status__in=["not_required", "pending", "ready", "failed"]
                ),
                name="member_valid_fingerprint",
            ),
        ]

    def __str__(self):
        return self.member_id
