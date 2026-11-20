from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower

from core.models import Entity


class UserManager(BaseUserManager):
    def create_user(self, phone_e164, password=None, **extra):
        from accounts.crypto import normalize_phone

        user = self.model(phone_e164=normalize_phone(phone_e164), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_e164, password=None, **extra):
        extra.update(role="admin", is_staff=True, is_superuser=True, is_active=True)
        from django.db import transaction

        from accounts.identifiers import next_display

        with transaction.atomic():
            user = self.create_user(phone_e164, password, **extra)
            StaffProfile.objects.create(user=user, short_id=next_display("staff"))
            return user


class User(Entity, AbstractBaseUser, PermissionsMixin):
    phone_e164 = models.CharField(max_length=14, unique=True)
    role = models.CharField(max_length=8, choices=[("member", "Member"), ("admin", "Admin")])
    full_name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    firebase_uid = models.CharField(max_length=128, null=True, blank=True, unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Browser operator access is explicit.
    USERNAME_FIELD = "phone_e164"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta(Entity.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["member", "admin"]), name="valid_user_role"
            ),
            models.UniqueConstraint(
                Lower("email"), condition=~models.Q(email=""), name="unique_user_email"
            ),
            models.CheckConstraint(
                condition=models.Q(phone_e164__regex=r"^\+8801[3-9][0-9]{8}$"),
                name="valid_bd_phone",
            ),
            models.CheckConstraint(
                condition=models.Q(role="admin") | models.Q(is_staff=False, is_superuser=False),
                name="operator_requires_admin",
            ),
        ]

    def __str__(self):
        if self.full_name and self.phone_e164:
            return f"{self.full_name} ({self.phone_e164})"
        return self.full_name or self.phone_e164 or str(self.pk)


class StaffProfile(Entity):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    short_id = models.CharField(max_length=24, unique=True)
    totp_secret_encrypted = models.TextField(blank=True)
    mfa_enrolled_at = models.DateTimeField(null=True, blank=True)
    setup_token_hash = models.CharField(max_length=64, blank=True)
    setup_expires_at = models.DateTimeField(null=True, blank=True)
    totp_last_step = models.BigIntegerField(null=True, blank=True)
    fingerprint_status = models.CharField(
        max_length=16,
        default="pending",
        choices=[(x, x) for x in ("not_required", "pending", "ready", "failed")],
    )
    # When True, bridge ensure/push uses ZK USER_ADMIN so staff can open device settings.
    device_admin = models.BooleanField(default=False)
    # Grantable admin-app feature.action codes (see accounts.staff_permissions).
    # Superuser ignores this and always has the full catalog.
    permissions = models.JSONField(default=list, blank=True)


class Challenge(Entity):
    phone_e164 = models.CharField(max_length=14, db_index=True)
    purpose = models.CharField(max_length=32)
    code_hash = models.CharField(max_length=64)
    actor = models.ForeignKey(User, null=True, on_delete=models.CASCADE, related_name="challenges")
    target = models.ForeignKey(
        User, null=True, on_delete=models.CASCADE, related_name="target_challenges"
    )
    expires_at = models.DateTimeField()
    resend_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True)


class GoogleLinkSession(Entity):
    firebase_uid = models.CharField(max_length=128)
    email = models.EmailField()
    full_name = models.CharField(max_length=200, blank=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)


class RefreshSession(Entity):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True)


class RateBucket(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    starts_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)


class DisplaySequence(models.Model):
    name = models.CharField(max_length=16, primary_key=True)
    value = models.PositiveBigIntegerField(default=0)
