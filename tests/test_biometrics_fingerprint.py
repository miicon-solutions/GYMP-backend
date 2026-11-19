from __future__ import annotations

import base64
from unittest.mock import patch

import pytest

from biometrics.bridge import BridgeUnavailable, DeviceStatus
from biometrics.crypto import encrypt_bytes, sha256_hex
from biometrics.models import MemberBiometricTemplate
from members.models import MemberProfile

pytestmark = pytest.mark.django_db


def _seed_template(profile: MemberProfile, finger_index: int = 0) -> MemberBiometricTemplate:
    raw = b"fake-zk-template"
    return MemberBiometricTemplate.objects.create(
        member=profile,
        finger_index=finger_index,
        template_ciphertext=encrypt_bytes(raw),
        template_sha256=sha256_hex(raw),
    )


def test_list_member_templates_empty(client, staff, member):
    profile = member.member_profile
    client.force_authenticate(staff)
    resp = client.get(f"/api/v1/admin/members/{member.pk}/fingerprint/templates/")
    assert resp.status_code == 200
    assert resp.data["finger_indexes"] == []
    assert resp.data["fingerprint_status"] == profile.fingerprint_status


def test_list_member_templates_populated(client, staff, member):
    profile = member.member_profile
    _seed_template(profile, 0)
    _seed_template(profile, 3)
    client.force_authenticate(staff)
    resp = client.get(f"/api/v1/admin/members/{member.pk}/fingerprint/templates/")
    assert resp.status_code == 200
    assert resp.data["finger_indexes"] == [0, 3]


def test_enroll_interactive_sets_ready(client, staff, member, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    profile = member.member_profile
    template_b64 = base64.b64encode(b"captured-template").decode()

    client.force_authenticate(staff)
    with (
        patch("biometrics.bridge.require_device_online", return_value=None),
        patch("biometrics.bridge.ensure_user", return_value={"ok": True}),
        patch("biometrics.bridge.enroll_fingerprint", return_value={"ok": True, "finger_id": 1}),
        patch(
            "biometrics.bridge.get_templates",
            return_value={"templates": {"1": template_b64}},
        ),
    ):
        resp = client.post(
            f"/api/v1/admin/members/{member.pk}/fingerprint/enroll/",
            {"finger_id": 1},
            format="json",
        )
    assert resp.status_code == 200
    assert resp.data["enrolled"] is True
    assert resp.data["finger_id"] == 1
    assert resp.data["stored"] == 1
    assert resp.data["fingerprint_status"] == "ready"
    assert resp.data["finger_indexes"] == [1]
    profile.refresh_from_db()
    assert profile.fingerprint_status == "ready"
    assert MemberBiometricTemplate.objects.filter(member=profile, finger_index=1).exists()


def test_enroll_interactive_requires_finger_id(client, staff, member):
    client.force_authenticate(staff)
    resp = client.post(
        f"/api/v1/admin/members/{member.pk}/fingerprint/enroll/",
        {},
        format="json",
    )
    assert resp.status_code == 400


def test_enroll_blocked_when_device_unreachable(client, staff, member, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    client.force_authenticate(staff)
    with patch(
        "biometrics.bridge.require_device_online",
        side_effect=BridgeUnavailable(
            "Fingerprint device is offline. Try again when the scanner is connected."
        ),
    ):
        resp = client.post(
            f"/api/v1/admin/members/{member.pk}/fingerprint/enroll/",
            {"finger_id": 1},
            format="json",
        )
    assert resp.status_code == 503


def test_delete_blocked_when_device_unreachable(client, staff, member, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    _seed_template(member.member_profile, 0)
    client.force_authenticate(staff)
    with patch(
        "biometrics.bridge.require_device_online",
        side_effect=BridgeUnavailable(
            "Fingerprint device is offline. Try again when the scanner is connected."
        ),
    ):
        resp = client.delete(
            f"/api/v1/admin/members/{member.pk}/fingerprint/templates/0/"
        )
    assert resp.status_code == 503
    assert MemberBiometricTemplate.objects.filter(
        member=member.member_profile, finger_index=0
    ).exists()


def test_device_status_available_to_any_staff(client, staff, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    client.force_authenticate(staff)
    offline = DeviceStatus(
        online=False,
        bridge_ok=True,
        message="Fingerprint device is offline. Try again when the scanner is connected.",
    )
    with patch("biometrics.bridge.device_status", return_value=offline):
        resp = client.get("/api/v1/admin/device/status/")
    assert resp.status_code == 200
    assert resp.data["online"] is False
    assert resp.data["bridge_ok"] is True
    assert "offline" in resp.data["message"].lower()


def test_delete_last_template_sets_pending(client, staff, member, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    profile = member.member_profile
    profile.fingerprint_status = "ready"
    profile.save(update_fields=["fingerprint_status", "updated_at"])
    _seed_template(profile, 0)

    client.force_authenticate(staff)
    with (
        patch("biometrics.bridge.require_device_online", return_value=None),
        patch("biometrics.bridge.delete_fingerprint", return_value={"ok": True}),
    ):
        resp = client.delete(
            f"/api/v1/admin/members/{member.pk}/fingerprint/templates/0/"
        )
    assert resp.status_code == 200
    assert resp.data["finger_indexes"] == []
    assert resp.data["fingerprint_status"] == "pending"
    profile.refresh_from_db()
    assert profile.fingerprint_status == "pending"
    assert not MemberBiometricTemplate.objects.filter(member=profile).exists()


def test_delete_keeps_ready_when_other_fingers_remain(client, staff, member, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    profile = member.member_profile
    profile.fingerprint_status = "ready"
    profile.save(update_fields=["fingerprint_status", "updated_at"])
    _seed_template(profile, 0)
    _seed_template(profile, 2)

    client.force_authenticate(staff)
    with (
        patch("biometrics.bridge.require_device_online", return_value=None),
        patch("biometrics.bridge.delete_fingerprint", return_value={"ok": True}),
    ):
        resp = client.delete(
            f"/api/v1/admin/members/{member.pk}/fingerprint/templates/0/"
        )
    assert resp.status_code == 200
    assert resp.data["finger_indexes"] == [2]
    assert resp.data["fingerprint_status"] == "ready"
