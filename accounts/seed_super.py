"""Go-parity local/dev seed super admin (+8801700000000 / S-ADM-7400)."""

from dataclasses import dataclass

from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Challenge, GoogleLinkSession, RefreshSession, StaffProfile, User
from accounts.services import begin_mfa
from members.models import MemberProfile

SEED_SUPER_PHONE = "+8801700000000"
SEED_SUPER_SHORT_ID = "S-ADM-7400"
SEED_SUPER_NAME = "Seed Super"


@dataclass(frozen=True)
class SeedSuperResult:
    status: str  # created | reclaimed | refreshed | unchanged
    user: User
    setup_token: str | None = None


def _short_id_owner():
    return StaffProfile.objects.filter(short_id=SEED_SUPER_SHORT_ID).select_related("user").first()


def _assert_short_id_free_or_owned_by(user: User | None):
    owner = _short_id_owner()
    if owner and (user is None or owner.user_id != user.pk):
        raise CommandError(
            f"Short id {SEED_SUPER_SHORT_ID} belongs to another staff account; "
            "cannot ensure the seed super admin."
        )


def _member_has_history(profile: MemberProfile) -> bool:
    if profile.payments.exists() or profile.check_ins.exists():
        return True
    if hasattr(profile, "biometric_templates") and profile.biometric_templates.exists():
        return True
    if hasattr(profile, "device_sync_states") and profile.device_sync_states.exists():
        return True
    from payments.models import PaymentSession

    return PaymentSession.objects.filter(member=profile).exists()


def _clear_auth_rows(user: User):
    RefreshSession.objects.filter(user=user).delete()
    Challenge.objects.filter(actor=user).delete()
    Challenge.objects.filter(target=user).delete()
    Challenge.objects.filter(phone_e164=user.phone_e164).delete()
    if user.firebase_uid:
        GoogleLinkSession.objects.filter(firebase_uid=user.firebase_uid).delete()


def _refresh_setup_if_needed(user: User) -> SeedSuperResult:
    profile = user.staff_profile
    if profile.mfa_enrolled_at:
        return SeedSuperResult(status="unchanged", user=user)
    now = timezone.now()
    needs_refresh = (
        not profile.setup_token_hash
        or not profile.setup_expires_at
        or now >= profile.setup_expires_at
    )
    if not needs_refresh:
        return SeedSuperResult(status="unchanged", user=user)
    setup = begin_mfa(user)
    return SeedSuperResult(status="refreshed", user=user, setup_token=setup["setup_token"])


def _create_staff_profile(user: User) -> SeedSuperResult:
    _assert_short_id_free_or_owned_by(user)
    user.role = "admin"
    user.is_superuser = True
    user.is_staff = False
    user.is_active = True
    if not user.full_name:
        user.full_name = SEED_SUPER_NAME
    user.firebase_uid = None
    user.set_unusable_password()
    user.save()
    StaffProfile.objects.create(user=user, short_id=SEED_SUPER_SHORT_ID)
    setup = begin_mfa(user)
    return SeedSuperResult(status="reclaimed", user=user, setup_token=setup["setup_token"])


@transaction.atomic
def ensure_seed_super_admin() -> SeedSuperResult:
    """Ensure the Go-era seed super admin exists. Local/dev only."""
    if settings.APP_ENV == "prod":
        raise CommandError("Seed super admin is disabled in production.")

    user = User.objects.select_for_update().filter(phone_e164=SEED_SUPER_PHONE).first()
    if user is None:
        _assert_short_id_free_or_owned_by(None)
        user = User.objects.create_user(
            SEED_SUPER_PHONE,
            full_name=SEED_SUPER_NAME,
            role="admin",
            is_superuser=True,
            is_staff=False,
        )
        StaffProfile.objects.create(user=user, short_id=SEED_SUPER_SHORT_ID)
        setup = begin_mfa(user)
        return SeedSuperResult(status="created", user=user, setup_token=setup["setup_token"])

    if user.role == "admin":
        if not StaffProfile.objects.filter(user=user).exists():
            return _create_staff_profile(user)
        profile = user.staff_profile
        if profile.short_id == SEED_SUPER_SHORT_ID:
            if not user.is_superuser or not user.is_active:
                user.is_superuser = True
                user.is_active = True
                user.save(update_fields=["is_superuser", "is_active"])
            return _refresh_setup_if_needed(user)
        # Different short id: leave it; keep staff auth path working.
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])
        return _refresh_setup_if_needed(user)

    if user.role != "member":
        raise CommandError(f"Unexpected role for seed phone: {user.role}")

    profile = MemberProfile.objects.filter(user=user).first()
    if profile is None:
        _clear_auth_rows(user)
        return _create_staff_profile(user)

    if _member_has_history(profile):
        raise CommandError(
            f"{SEED_SUPER_PHONE} is a member with payment/attendance history; "
            "reclaim it manually before running seed_dev."
        )
    _clear_auth_rows(user)
    profile.delete()
    return _create_staff_profile(user)
