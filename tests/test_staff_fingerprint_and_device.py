from __future__ import annotations

import base64
from unittest.mock import patch

import pytest
from django.utils import timezone

from accounts.models import StaffProfile, User
from attendance.models import StaffCheckIn
from biometrics.crypto import encrypt_bytes, sha256_hex
from biometrics.models import StaffBiometricTemplate

pytestmark = pytest.mark.django_db


def _seed_staff_template(staff: StaffProfile, finger_index: int = 0) -> StaffBiometricTemplate:
    raw = b"fake-staff-zk-template"
    return StaffBiometricTemplate.objects.create(
        staff=staff,
        finger_index=finger_index,
        template_ciphertext=encrypt_bytes(raw),
        template_sha256=sha256_hex(raw),
    )


def test_list_staff_templates_empty(client, staff):
    profile = staff.staff_profile
    client.force_authenticate(staff)
    resp = client.get(f"/api/v1/admin/staff/{staff.pk}/fingerprint/templates/")
    assert resp.status_code == 200
    assert resp.data["finger_indexes"] == []
    assert resp.data["fingerprint_status"] == profile.fingerprint_status


def test_enroll_staff_interactive_sets_ready(client, staff, super_admin, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    profile = staff.staff_profile
    template_b64 = base64.b64encode(b"captured-staff-template").decode()

    client.force_authenticate(super_admin)
    with (
        patch("biometrics.bridge.require_device_online", return_value=None),
        patch(
            "biometrics.bridge.enroll_session",
            return_value={"ok": True, "finger_id": 2, "templates": {"2": template_b64}},
        ) as enroll_session,
    ):
        resp = client.post(
            f"/api/v1/admin/staff/{staff.pk}/fingerprint/enroll/",
            {"finger_id": 2},
            format="json",
        )
    assert resp.status_code == 200
    assert resp.data["enrolled"] is True
    assert resp.data["finger_id"] == 2
    assert resp.data["fingerprint_status"] == "ready"
    assert resp.data["finger_indexes"] == [2]
    profile.refresh_from_db()
    assert profile.fingerprint_status == "ready"
    assert StaffBiometricTemplate.objects.filter(staff=profile, finger_index=2).exists()
    enroll_session.assert_called()
    assert enroll_session.call_args.kwargs["user_id"] == profile.short_id
    assert enroll_session.call_args.kwargs["privilege"] == 0


def test_delete_staff_template_sets_pending(client, staff, super_admin, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    profile = staff.staff_profile
    profile.fingerprint_status = "ready"
    profile.save(update_fields=["fingerprint_status", "updated_at"])
    _seed_staff_template(profile, 0)

    client.force_authenticate(super_admin)
    with (
        patch("biometrics.bridge.require_device_online", return_value=None),
        patch("biometrics.bridge.delete_fingerprint", return_value={"ok": True}),
    ):
        resp = client.delete(f"/api/v1/admin/staff/{staff.pk}/fingerprint/templates/0/")
    assert resp.status_code == 200
    assert resp.data["finger_indexes"] == []
    assert resp.data["fingerprint_status"] == "pending"


def test_device_checkin_resolves_staff_short_id(client, staff):
    short_id = staff.staff_profile.short_id
    at = timezone.now()
    resp = client.post(
        "/api/v1/internal/attendance/check-in/",
        {"member_id": short_id, "checked_in_at": at.isoformat(), "source": "device"},
        format="json",
        HTTP_X_DEVICE_KEY="test-device-key",
    )
    assert resp.status_code == 200
    assert resp.data["member_id"] == short_id
    assert resp.data["subject"] == "staff"
    assert StaffCheckIn.objects.filter(staff=staff.staff_profile).exists()


def test_device_controllers_permission_gated(client, staff, super_admin, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"

    limited = User.objects.create_user("+8801511111111", role="admin", full_name="Limited")
    StaffProfile.objects.create(user=limited, short_id="ADM-LIM", permissions=["members.view"])

    client.force_authenticate(limited)
    denied = client.get("/api/v1/admin/device/controllers/")
    assert denied.status_code == 403

    client.force_authenticate(staff)
    empty = client.get("/api/v1/admin/device/controllers/")
    assert empty.status_code == 200
    assert empty.data["count"] == 0

    with (
        patch(
            "biometrics.bridge.require_device_online",
            return_value=None,
        ),
        patch("biometrics.bridge.ensure_user", return_value={"ok": True}) as ensure,
    ):
        added = client.post(
            "/api/v1/admin/device/controllers/",
            {"staff_id": str(staff.pk)},
            format="json",
        )
    assert added.status_code == 200
    assert added.data["device_admin"] is True
    assert added.data["short_id"] == staff.staff_profile.short_id
    ensure.assert_called()
    assert ensure.call_args.kwargs["privilege"] == 14

    staff.staff_profile.refresh_from_db()
    assert staff.staff_profile.device_admin is True

    listed = client.get("/api/v1/admin/device/controllers/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1

    with patch("biometrics.bridge.ensure_user", return_value={"ok": True}) as demote:
        removed = client.delete(f"/api/v1/admin/device/controllers/{staff.pk}/")
    assert removed.status_code == 200
    assert removed.data["removed"] is True
    demote.assert_called()
    assert demote.call_args.kwargs["privilege"] == 0
    staff.staff_profile.refresh_from_db()
    assert staff.staff_profile.device_admin is False
