"""Expire → revoke scanner access; renew → restore; check-in rejects expired."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from attendance.services import record_checkin
from biometrics.crypto import encrypt_bytes, sha256_hex
from biometrics.models import BridgeDeviceJob, MemberBiometricTemplate
from biometrics.services import (
    reconcile_device_access,
    restore_member_device_access,
    revoke_member_device_access,
)
from members.models import MemberProfile
from notifications.services import notify_membership_expiry_batch
from payments.services import activate

pytestmark = pytest.mark.django_db


def _seed_template(profile: MemberProfile, finger_index: int = 0) -> MemberBiometricTemplate:
    raw = b"fake-zk-template-expire"
    return MemberBiometricTemplate.objects.create(
        member=profile,
        finger_index=finger_index,
        template_ciphertext=encrypt_bytes(raw),
        template_sha256=sha256_hex(raw),
    )


def test_revoke_member_device_access_enqueues_job(member):
    profile = member.member_profile
    _seed_template(profile)
    profile.fingerprint_status = "ready"
    profile.save(update_fields=["fingerprint_status", "updated_at"])

    out = revoke_member_device_access(profile, wait=False)
    assert out["revoked"] is True
    assert out["queued"] is True
    profile.refresh_from_db()
    job = BridgeDeviceJob.objects.get(pk=out["job_id"])
    assert job.kind == BridgeDeviceJob.KIND_REVOKE_ACCESS
    assert job.payload["user_id"] == profile.device_keypad_id
    assert str(job.payload["user_id"]).isdigit()
    assert not str(job.payload["user_id"]).startswith("0")
    assert job.status == BridgeDeviceJob.STATUS_PENDING


def test_restore_member_device_access_enqueues_push(member):
    profile = member.member_profile
    _seed_template(profile)
    profile.membership_status = "active"
    profile.fingerprint_status = "ready"
    profile.save(update_fields=["membership_status", "fingerprint_status", "updated_at"])

    out = restore_member_device_access(profile, wait=False)
    assert out["restored"] is True
    assert out["queued"] is True
    profile.refresh_from_db()
    job = BridgeDeviceJob.objects.get(pk=out["job_id"])
    assert job.kind == BridgeDeviceJob.KIND_PUSH_USER
    assert job.payload["user_id"] == profile.device_keypad_id
    assert str(job.payload["user_id"]).isdigit()
    assert "0" in (job.payload.get("templates") or {})


def test_expiry_batch_enqueues_revoke(member, plan):
    profile = member.member_profile
    today = timezone.localdate()
    expired_day = today - timedelta(days=1)
    profile.membership_status = "active"
    profile.plan = plan
    profile.expires_on = expired_day
    profile.fingerprint_status = "ready"
    profile.save()
    _seed_template(profile)

    with patch(
        "biometrics.services.revoke_member_device_access",
        return_value={"revoked": True, "queued": True, "job_id": "x"},
    ) as revoke:
        result = notify_membership_expiry_batch(today=today)

    profile.refresh_from_db()
    assert profile.membership_status == "expired"
    assert result["device_revoked"] == 1
    revoke.assert_called_once()
    assert revoke.call_args.args[0].member_id == profile.member_id


def test_expiry_batch_catchup_past_due_not_only_yesterday(member, plan):
    """Active with expires_on days ago still flips + revokes (cron lag)."""
    profile = member.member_profile
    today = timezone.localdate()
    expired_on = today - timedelta(days=5)
    profile.membership_status = "active"
    profile.plan = plan
    profile.expires_on = expired_on
    profile.fingerprint_status = "ready"
    profile.save()
    _seed_template(profile)

    with patch(
        "biometrics.services.revoke_member_device_access",
        return_value={"revoked": True, "queued": True, "job_id": "x"},
    ) as revoke:
        result = notify_membership_expiry_batch(today=today)

    profile.refresh_from_db()
    assert profile.membership_status == "expired"
    assert result["device_revoked"] == 1
    revoke.assert_called_once()


def test_reconcile_flips_past_due_then_revokes(member, plan):
    profile = member.member_profile
    today = timezone.localdate()
    profile.membership_status = "active"
    profile.plan = plan
    profile.expires_on = today - timedelta(days=3)
    profile.fingerprint_status = "ready"
    profile.save()
    _seed_template(profile)

    result = reconcile_device_access(today=today)
    profile.refresh_from_db()
    assert profile.membership_status == "expired"
    assert result["flipped"] == 1
    assert result["revoked"] == 1
    assert BridgeDeviceJob.objects.filter(
        kind=BridgeDeviceJob.KIND_REVOKE_ACCESS,
        payload__user_id=profile.device_keypad_id,
    ).exists()


def test_revoke_skips_duplicate_open_job(member):
    profile = member.member_profile
    _seed_template(profile)
    first = revoke_member_device_access(profile, wait=False)
    second = revoke_member_device_access(profile, wait=False)
    assert first["revoked"] is True
    assert second["revoked"] is True
    assert second.get("already_pending") is True
    profile.refresh_from_db()
    assert (
        BridgeDeviceJob.objects.filter(
            kind=BridgeDeviceJob.KIND_REVOKE_ACCESS,
            payload__user_id=profile.device_keypad_id,
            status=BridgeDeviceJob.STATUS_PENDING,
        ).count()
        == 1
    )


def test_activate_enqueues_restore(member, plan):
    profile = member.member_profile
    profile.membership_status = "expired"
    profile.fingerprint_status = "ready"
    profile.save()
    _seed_template(profile)
    expires = timezone.localdate() + timedelta(days=30)

    with patch(
        "biometrics.services.restore_member_device_access",
        return_value={"restored": True, "queued": True},
    ) as restore:
        activate(profile, plan, expires)

    profile.refresh_from_db()
    assert profile.membership_status == "active"
    restore.assert_called_once()


def test_reconcile_revokes_expired_and_restores_active(member, plan):
    profile = member.member_profile
    _seed_template(profile)
    profile.membership_status = "expired"
    profile.plan = plan
    profile.fingerprint_status = "ready"
    profile.save()

    result = reconcile_device_access()
    assert result["revoked"] == 1
    profile.refresh_from_db()
    assert BridgeDeviceJob.objects.filter(
        kind=BridgeDeviceJob.KIND_REVOKE_ACCESS,
        payload__user_id=profile.device_keypad_id,
    ).exists()

    # Flip to active with cleared sync → restore (ZK user_id = digits keypad id).
    BridgeDeviceJob.objects.all().delete()
    profile.membership_status = "active"
    profile.save(update_fields=["membership_status", "updated_at"])
    result2 = reconcile_device_access()
    assert result2["restored"] == 1
    profile.refresh_from_db()
    assert profile.device_keypad_id.isdigit()
    assert BridgeDeviceJob.objects.filter(
        kind=BridgeDeviceJob.KIND_PUSH_USER,
        payload__user_id=profile.device_keypad_id,
    ).exists()


def test_record_checkin_rejects_expired(member, plan):
    profile = member.member_profile
    profile.membership_status = "expired"
    profile.plan = plan
    profile.expires_on = timezone.localdate() - timedelta(days=1)
    profile.save()

    with pytest.raises(PermissionDenied, match="expired"):
        record_checkin({"member_id": profile.member_id})


def test_record_checkin_rejects_active_past_expires_on(member, plan):
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.expires_on = timezone.localdate() - timedelta(days=2)
    profile.save()

    with pytest.raises(PermissionDenied, match="expired"):
        record_checkin({"member_id": profile.member_id})


def test_record_checkin_allows_active(member, plan):
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.expires_on = timezone.localdate() + timedelta(days=5)
    profile.save()

    out = record_checkin({"member_id": profile.member_id})
    assert out["member_id"] == profile.member_id
    assert out["subject"] == "member"
