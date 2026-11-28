"""App hard-delete: super-only, phone-allowlisted to +8801307482200."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.utils import timezone

from accounts.models import Challenge, User
from accounts.services import new_member
from attendance.models import CheckIn
from biometrics.crypto import encrypt_bytes, sha256_hex
from biometrics.models import BridgeDeviceJob, MemberBiometricTemplate
from members.models import MemberProfile
from members.services import ALLOWED_HARD_DELETE_PHONE
from notifications.models import StaffAnnouncement
from operations.models import Activity
from payments.models import Payment

pytestmark = pytest.mark.django_db


def _seed_template(profile: MemberProfile) -> MemberBiometricTemplate:
    raw = b"fake-zk-template-hard-delete"
    return MemberBiometricTemplate.objects.create(
        member=profile,
        finger_index=0,
        template_ciphertext=encrypt_bytes(raw),
        template_sha256=sha256_hex(raw),
    )


def test_super_deletes_allowlisted_member_and_related(
    client, super_admin, other_member, plan
):
    target = new_member(ALLOWED_HARD_DELETE_PHONE, full_name="Purge Target")
    profile = target.member_profile
    profile.device_keypad_id = "42"
    profile.save(update_fields=["device_keypad_id", "updated_at"])
    _seed_template(profile)
    Payment.objects.create(
        member=profile,
        plan=plan,
        amount_taka=1000,
        status="paid",
        channel="cash",
        kind="first_purchase",
        is_first_payment=True,
        paid_at=timezone.now(),
    )
    CheckIn.objects.create(
        member=profile,
        checked_in_at=timezone.now(),
        check_in_date=timezone.localdate(),
    )
    now = timezone.now()
    Challenge.objects.create(
        phone_e164=ALLOWED_HARD_DELETE_PHONE,
        purpose="login",
        code_hash="x",
        expires_at=now,
        resend_at=now,
    )
    StaffAnnouncement.objects.create(
        title="Hi",
        body="Body",
        scope="member",
        member_id=target.pk,
    )
    BridgeDeviceJob.objects.create(
        kind=BridgeDeviceJob.KIND_REVOKE_ACCESS,
        status=BridgeDeviceJob.STATUS_SUCCEEDED,
        payload={"user_id": "42", "display_id": profile.member_id},
        result={},
    )
    Activity.objects.create(
        admin=super_admin,
        admin_name=super_admin.full_name,
        admin_short_id=super_admin.staff_profile.short_id,
        area="member",
        action="update",
        summary_key="adminActivityMemberPhoneLinked",
        summary_params={"member_id": profile.member_id, "name": "old"},
    )
    other_id = other_member.pk

    client.force_authenticate(super_admin)
    with patch(
        "biometrics.services.revoke_member_device_access",
        return_value={"revoked": True, "result": {}},
    ) as revoke:
        response = client.delete(f"/api/v1/admin/members/{target.pk}/")

    assert response.status_code == 204
    revoke.assert_called_once()
    assert not User.objects.filter(pk=target.pk).exists()
    assert not MemberProfile.objects.filter(user_id=target.pk).exists()
    assert not Payment.objects.filter(member_id=profile.pk).exists()
    assert not CheckIn.objects.filter(member_id=profile.pk).exists()
    assert not MemberBiometricTemplate.objects.filter(member_id=profile.pk).exists()
    assert not Challenge.objects.filter(phone_e164=ALLOWED_HARD_DELETE_PHONE).exists()
    assert not StaffAnnouncement.objects.filter(member_id=target.pk).exists()
    assert not BridgeDeviceJob.objects.filter(payload__user_id="42").exists()
    assert User.objects.filter(pk=other_id).exists()
    assert Activity.objects.filter(
        summary_key="adminActivityMemberDeleted",
        admin=super_admin,
    ).exists()


def test_super_cannot_delete_other_member_phone(client, super_admin, member):
    client.force_authenticate(super_admin)
    with patch("biometrics.services.revoke_member_device_access") as revoke:
        response = client.delete(f"/api/v1/admin/members/{member.pk}/")
    assert response.status_code == 403
    revoke.assert_not_called()
    assert User.objects.filter(pk=member.pk).exists()


def test_non_super_staff_cannot_hard_delete_allowlisted(client, staff):
    target = new_member(ALLOWED_HARD_DELETE_PHONE, full_name="Purge Target")
    client.force_authenticate(staff)
    with patch("biometrics.services.revoke_member_device_access") as revoke:
        response = client.delete(f"/api/v1/admin/members/{target.pk}/")
    assert response.status_code == 403
    revoke.assert_not_called()
    assert User.objects.filter(pk=target.pk).exists()
