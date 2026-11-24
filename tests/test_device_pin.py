from __future__ import annotations

import base64
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from attendance.services import record_checkin
from biometrics.crypto import encrypt_bytes, sha256_hex
from biometrics.models import BridgeDeviceJob, MemberBiometricTemplate
from biometrics.pins import (
    ensure_device_keypad_id,
    ensure_device_pin,
    generate_device_pin,
)
from biometrics.services import restore_member_device_access
from members.models import MemberProfile
from members.services import admin_member_data

pytestmark = pytest.mark.django_db


def _seed_template(profile: MemberProfile, finger_index: int = 0) -> MemberBiometricTemplate:
    raw = b"fake-zk-template-pin"
    return MemberBiometricTemplate.objects.create(
        member=profile,
        finger_index=finger_index,
        template_ciphertext=encrypt_bytes(raw),
        template_sha256=sha256_hex(raw),
    )


def test_generate_device_pin_is_four_digits():
    pin = generate_device_pin()
    assert len(pin) == 4
    assert pin.isdigit()
    assert not pin.startswith("0")


def test_ensure_device_keypad_id_digits_only_from_display(member):
    profile = member.member_profile
    profile.member_id = "PF-0007"
    profile.device_keypad_id = ""
    profile.save(update_fields=["member_id", "device_keypad_id", "updated_at"])

    keypad = ensure_device_keypad_id(profile)
    assert keypad == "7"
    profile.refresh_from_db()
    assert profile.device_keypad_id == "7"


def test_ensure_device_keypad_id_migrates_leading_zeros(member):
    profile = member.member_profile
    profile.member_id = "PF-0003"
    profile.device_keypad_id = "0003"
    profile.save(update_fields=["member_id", "device_keypad_id", "updated_at"])

    keypad = ensure_device_keypad_id(profile)
    assert keypad == "3"
    profile.refresh_from_db()
    assert profile.device_keypad_id == "3"


def test_ensure_device_keypad_id_rejects_zero_alone(member):
    profile = member.member_profile
    profile.member_id = "PF-0000"
    profile.device_keypad_id = ""
    profile.save(update_fields=["member_id", "device_keypad_id", "updated_at"])

    keypad = ensure_device_keypad_id(profile)
    assert keypad != "0"
    assert keypad.isdigit()
    assert int(keypad) > 0
    assert not keypad.startswith("0")


def test_ensure_device_keypad_id_prefers_display_digits_when_free(member, other_member):
    a = member.member_profile
    b = other_member.member_profile
    a.member_id = "PF-0009"
    a.device_keypad_id = "9"
    a.save(update_fields=["member_id", "device_keypad_id", "updated_at"])
    b.member_id = "PF-1009"
    b.device_keypad_id = ""
    b.save(update_fields=["member_id", "device_keypad_id", "updated_at"])

    keypad = ensure_device_keypad_id(b)
    assert keypad == "1009"


def test_enroll_pushes_keypad_id_not_display(client, staff, member, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    profile = member.member_profile
    profile.member_id = "PF-0042"
    profile.device_keypad_id = ""
    profile.save(update_fields=["member_id", "device_keypad_id", "updated_at"])

    template_b64 = base64.b64encode(b"captured-template").decode()
    client.force_authenticate(staff)
    with (
        patch("biometrics.bridge.require_device_online", return_value=None),
        patch(
            "biometrics.bridge.enroll_session",
            return_value={"ok": True, "finger_id": 1, "templates": {"1": template_b64}},
        ) as enroll,
    ):
        resp = client.post(
            f"/api/v1/admin/members/{member.pk}/fingerprint/enroll/",
            {"finger_id": 1},
            format="json",
        )
    assert resp.status_code == 200
    kwargs = enroll.call_args.kwargs
    assert kwargs["user_id"] == "42"
    assert kwargs["pin"] and kwargs["pin"].isdigit()
    profile.refresh_from_db()
    assert profile.device_keypad_id == "42"
    assert profile.device_pin_enc


def test_record_checkin_by_keypad_id(member, plan):
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.expires_on = timezone.localdate() + timedelta(days=5)
    profile.device_keypad_id = "4242"
    profile.save()

    out = record_checkin({"member_id": "4242"})
    assert out["member_id"] == profile.member_id
    assert out["subject"] == "member"


def test_record_checkin_matches_legacy_zero_padded_keypad(member, plan):
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.expires_on = timezone.localdate() + timedelta(days=5)
    profile.device_keypad_id = "0003"
    profile.save()

    # User types "3" (cannot start with 0 on the panel).
    out = record_checkin({"member_id": "3"})
    assert out["member_id"] == profile.member_id


def test_record_checkin_legacy_member_id_still_works(member, plan):
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.expires_on = timezone.localdate() + timedelta(days=5)
    profile.device_keypad_id = "4242"
    profile.save()

    out = record_checkin({"member_id": profile.member_id})
    assert out["member_id"] == profile.member_id


def test_member_self_device_pin_regenerate_forbidden(client, member, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    profile = member.member_profile
    ensure_device_keypad_id(profile)
    ensure_device_pin(profile)
    client.force_authenticate(member)
    with patch("biometrics.bridge.push_user", return_value={"ok": True}) as push:
        resp = client.post("/api/v1/member/device-pin/regenerate/")
    assert resp.status_code == 403
    push.assert_not_called()


def test_admin_regenerate_member_device_pin(client, staff, member, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    profile = member.member_profile
    ensure_device_keypad_id(profile)
    first = ensure_device_pin(profile)
    client.force_authenticate(staff)
    with patch("biometrics.bridge.push_user", return_value={"ok": True}) as push:
        resp = client.post(f"/api/v1/admin/members/{member.pk}/device-pin/regenerate/")
    assert resp.status_code == 200
    assert resp.data["device_keypad_id"] == profile.device_keypad_id
    assert resp.data["device_pin"] != first
    assert push.call_args.kwargs["user_id"] == profile.device_keypad_id
    assert push.call_args.kwargs["pin"] == resp.data["device_pin"]


def test_regenerate_staff_device_pin(client, staff, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    sp = staff.staff_profile
    ensure_device_keypad_id(sp)
    first = ensure_device_pin(sp)
    client.force_authenticate(staff)
    with patch("biometrics.bridge.push_user", return_value={"ok": True}) as push:
        resp = client.post("/api/v1/admin/me/device-pin/regenerate/")
    assert resp.status_code == 200
    assert resp.data["device_keypad_id"] == sp.device_keypad_id
    assert resp.data["device_pin"] != first
    assert push.call_args.kwargs["user_id"] == sp.device_keypad_id


def test_own_profile_hides_device_credentials(client, member):
    profile = member.member_profile
    ensure_device_keypad_id(profile)
    ensure_device_pin(profile)
    client.force_authenticate(member)
    resp = client.get("/api/v1/member/profile/")
    assert resp.status_code == 200
    assert "device_keypad_id" not in resp.data
    assert "device_pin" not in resp.data
    profile.refresh_from_db()
    assert profile.device_pin_enc


def test_admin_member_view_includes_device_credentials(member):
    profile = member.member_profile
    profile.fingerprint_status = "ready"
    profile.save(update_fields=["fingerprint_status", "updated_at"])
    ensure_device_keypad_id(profile)
    pin = ensure_device_pin(profile)
    data = admin_member_data(profile)
    assert data["device_keypad_id"] == profile.device_keypad_id
    assert data["device_pin"] == pin


def test_staff_password_checkin_rotates_pin_once(
    staff, settings, django_capture_on_commit_callbacks
):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    sp = staff.staff_profile
    ensure_device_keypad_id(sp)
    first = ensure_device_pin(sp)
    with (
        patch("biometrics.bridge.push_user", return_value={"ok": True}) as push,
        django_capture_on_commit_callbacks(execute=True),
    ):
        out = record_checkin(
            {
                "member_id": sp.device_keypad_id,
                "source": "device",
                "verify_method": 0,
            }
        )
    assert out["subject"] == "staff"
    sp.refresh_from_db()
    from biometrics.pins import decrypt_device_pin

    assert decrypt_device_pin(sp) != first
    assert push.called
    # Fingerprint unlock must not rotate again.
    second = decrypt_device_pin(sp)
    with (
        patch("biometrics.bridge.push_user", return_value={"ok": True}) as push2,
        django_capture_on_commit_callbacks(execute=True),
    ):
        record_checkin(
            {
                "member_id": sp.device_keypad_id,
                "source": "device",
                "verify_method": 1,
                "checked_in_at": timezone.now() + timedelta(minutes=1),
            }
        )
    push2.assert_not_called()
    sp.refresh_from_db()
    assert decrypt_device_pin(sp) == second


def test_member_password_checkin_rotates_pin_once(
    member, plan, settings, django_capture_on_commit_callbacks
):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.expires_on = timezone.localdate() + timedelta(days=5)
    profile.save()
    ensure_device_keypad_id(profile)
    first = ensure_device_pin(profile)
    with (
        patch("biometrics.bridge.push_user", return_value={"ok": True}) as push,
        django_capture_on_commit_callbacks(execute=True),
    ):
        out = record_checkin(
            {
                "member_id": profile.device_keypad_id,
                "source": "device",
                "verify_method": 0,
            }
        )
    assert out["subject"] == "member"
    profile.refresh_from_db()
    from biometrics.pins import decrypt_device_pin

    assert decrypt_device_pin(profile) != first
    assert push.called


def test_restore_push_uses_keypad_id(member, plan):
    profile = member.member_profile
    _seed_template(profile)
    profile.membership_status = "active"
    profile.plan = plan
    profile.fingerprint_status = "ready"
    profile.device_keypad_id = ""
    profile.device_pin_enc = ""
    profile.save()

    result = restore_member_device_access(profile, wait=False)
    assert result.get("restored") is True
    profile.refresh_from_db()
    assert profile.device_keypad_id.isdigit()
    assert BridgeDeviceJob.objects.filter(
        kind=BridgeDeviceJob.KIND_PUSH_USER,
        payload__user_id=profile.device_keypad_id,
    ).exists()
