from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.crypto import digest
from accounts.models import StaffProfile, User
from accounts.seed_super import (
    SEED_OPERATOR_PASSWORD,
    SEED_OPERATOR_USERNAME,
    SEED_SUPER_PHONE,
    SEED_SUPER_SHORT_ID,
    ensure_seed_super_admin,
)
from accounts.services import begin_mfa, new_member
from payments.models import Payment

pytestmark = pytest.mark.django_db
BASE = "/api/v1/auth/"


def test_seed_dev_creates_seed_super_and_resolve_phone_staff(client):
    stream = StringIO()
    call_command("seed_dev", stdout=stream)
    user = User.objects.get(phone_e164=SEED_SUPER_PHONE)
    assert user.role == "admin"
    assert user.is_superuser is True
    assert user.is_staff is True
    assert user.check_password(SEED_OPERATOR_PASSWORD)
    assert user.staff_profile.short_id == SEED_SUPER_SHORT_ID
    assert user.staff_profile.mfa_enrolled_at is None
    assert digest(stream.getvalue().splitlines()[-1]) == user.staff_profile.setup_token_hash
    assert SEED_OPERATOR_USERNAME in stream.getvalue()

    response = client.post(BASE + "resolve-phone/", {"phone_e164": SEED_SUPER_PHONE}, format="json")
    assert response.status_code == 200
    assert response.data["kind"] == "staff"
    assert response.data["staff_short_id"] == SEED_SUPER_SHORT_ID
    assert response.data["mfa_enrolled"] is False

    otp = client.post(
        BASE + "otp/send/",
        {"phone_e164": SEED_SUPER_PHONE, "purpose": "onboarding"},
        format="json",
    )
    assert otp.status_code == 409

    assert client.login(username=SEED_OPERATOR_USERNAME, password=SEED_OPERATOR_PASSWORD)
    assert client.get("/admin/").status_code == 200


def test_seed_dev_reclaims_bare_member_at_seed_phone(client):
    new_member(SEED_SUPER_PHONE, full_name="Accidental Member")
    assert User.objects.get(phone_e164=SEED_SUPER_PHONE).role == "member"

    stream = StringIO()
    call_command("seed_dev", stdout=stream)
    from members.models import MemberProfile

    user = User.objects.get(phone_e164=SEED_SUPER_PHONE)
    assert user.role == "admin"
    assert user.is_superuser is True
    assert user.staff_profile.short_id == SEED_SUPER_SHORT_ID
    assert not MemberProfile.objects.filter(user=user).exists()
    assert "reclaimed" in stream.getvalue().lower()
    assert (
        client.post(BASE + "resolve-phone/", {"phone_e164": SEED_SUPER_PHONE}, format="json").data[
            "kind"
        ]
        == "staff"
    )


def test_seed_dev_refuses_reclaim_when_member_has_payments(plan):
    user = new_member(SEED_SUPER_PHONE)
    Payment.objects.create(
        member=user.member_profile,
        plan=plan,
        channel="cash",
        kind="first_payment",
        is_first_payment=True,
        amount_taka=3000,
        status="paid",
        paid_at=timezone.now(),
        line_items=[],
    )
    with pytest.raises(CommandError, match="payment/attendance history"):
        call_command("seed_dev", stdout=StringIO())
    assert User.objects.get(phone_e164=SEED_SUPER_PHONE).role == "member"


def test_seed_dev_prod_guard(settings):
    settings.APP_ENV = "prod"
    with pytest.raises(CommandError, match="disabled in production"):
        call_command("seed_dev", stdout=StringIO())
    assert not User.objects.filter(phone_e164=SEED_SUPER_PHONE).exists()


def test_seed_dev_catalog_only_skips_users(settings):
    from plans.models import Plan

    settings.APP_ENV = "prod"
    call_command("seed_dev", "--catalog-only", stdout=StringIO())
    assert not User.objects.exists()
    assert not StaffProfile.objects.exists()
    assert set(Plan.objects.values_list("duration_months", flat=True)) == {1, 3, 12}


def test_seed_dev_idempotent_preserves_enrolled_mfa():
    call_command("seed_dev", stdout=StringIO())
    user = User.objects.get(phone_e164=SEED_SUPER_PHONE)
    begin_mfa(user)
    profile = user.staff_profile
    # Simulate enrolled authenticator.
    profile.mfa_enrolled_at = timezone.now()
    profile.setup_token_hash = ""
    profile.setup_expires_at = None
    profile.totp_secret_encrypted = "enc"
    profile.save()
    enrolled_at = profile.mfa_enrolled_at

    stream = StringIO()
    call_command("seed_dev", stdout=stream)
    profile.refresh_from_db()
    assert profile.mfa_enrolled_at == enrolled_at
    assert profile.totp_secret_encrypted == "enc"
    assert "setup token" not in stream.getvalue().lower() or "ready" in stream.getvalue().lower()
    assert User.objects.filter(phone_e164=SEED_SUPER_PHONE).count() == 1


def test_ensure_seed_super_refreshes_expired_setup_token():
    result = ensure_seed_super_admin()
    assert result.status == "created"
    profile = result.user.staff_profile
    profile.setup_expires_at = timezone.now() - timedelta(seconds=1)
    profile.save(update_fields=["setup_expires_at"])
    old_hash = profile.setup_token_hash

    refreshed = ensure_seed_super_admin()
    assert refreshed.status == "refreshed"
    assert refreshed.setup_token
    profile.refresh_from_db()
    assert profile.setup_token_hash != old_hash
    assert profile.setup_token_hash == digest(refreshed.setup_token)


def test_ensure_seed_super_conflict_on_short_id():
    other = User.objects.create_user(
        "+8801911111111", role="admin", full_name="Other", is_superuser=True
    )
    StaffProfile.objects.create(user=other, short_id=SEED_SUPER_SHORT_ID)
    with pytest.raises(CommandError, match=SEED_SUPER_SHORT_ID):
        ensure_seed_super_admin()
