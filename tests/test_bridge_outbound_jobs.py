"""Outbound bridge jobs + heartbeat (no ZKTECO_BRIDGE_URL)."""

from __future__ import annotations

import base64
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from biometrics.crypto import encrypt_bytes, sha256_hex
from biometrics.models import BridgeDeviceJob, FingerprintDevice, MemberBiometricTemplate

pytestmark = pytest.mark.django_db


def _heartbeat(client, settings, *, online=True, bridge_device_id="dev-1"):
    settings.ATTENDANCE_DEVICE_KEY = "test-device-key"
    return client.post(
        "/api/v1/internal/bridge/heartbeat/",
        {
            "bridge_device_id": bridge_device_id,
            "online": online,
            "name": "Front desk",
            "serial": "SN1",
            "firmware": "1.0",
            "user_count": 3,
            "ip": "192.168.1.50",
            "port": 4370,
        },
        format="json",
        HTTP_X_DEVICE_KEY="test-device-key",
    )


def test_heartbeat_upserts_device(client, settings):
    resp = _heartbeat(client, settings)
    assert resp.status_code == 200
    assert resp.data["ok"] is True
    device = FingerprintDevice.objects.get(bridge_device_id="dev-1")
    assert device.scanner_online is True
    assert device.serial == "SN1"
    assert device.lan_ip == "192.168.1.50"


def test_device_status_from_heartbeat(client, staff, settings):
    _heartbeat(client, settings, online=True)
    client.force_authenticate(staff)
    resp = client.get("/api/v1/admin/device/status/")
    assert resp.status_code == 200
    assert resp.data["bridge_ok"] is True
    assert resp.data["online"] is True
    assert resp.data["serial"] == "SN1"
    assert resp.data["heartbeat_age_sec"] is not None


def test_internal_and_admin_bridge_ping(client, staff, settings):
    settings.ATTENDANCE_DEVICE_KEY = "test-device-key"
    ping = client.get(
        "/api/v1/internal/bridge/ping/",
        HTTP_X_DEVICE_KEY="test-device-key",
    )
    assert ping.status_code == 200
    assert ping.data["ok"] is True

    _heartbeat(client, settings, online=True)
    client.force_authenticate(staff)
    admin_ping = client.get("/api/v1/admin/device/ping/")
    assert admin_ping.status_code == 200
    assert admin_ping.data["bridge_connected"] is True
    assert admin_ping.data["scanner_online"] is True


def test_device_status_stale_heartbeat(client, staff, settings):
    _heartbeat(client, settings, online=True)
    FingerprintDevice.objects.filter(bridge_device_id="dev-1").update(
        last_seen_at=timezone.now() - timedelta(seconds=500)
    )
    client.force_authenticate(staff)
    resp = client.get("/api/v1/admin/device/status/")
    assert resp.status_code == 200
    assert resp.data["bridge_ok"] is False
    assert resp.data["online"] is False


def test_claim_and_complete_job(client, settings):
    _heartbeat(client, settings)
    job = BridgeDeviceJob.objects.create(
        kind=BridgeDeviceJob.KIND_ENSURE_USER,
        status=BridgeDeviceJob.STATUS_PENDING,
        payload={"user_id": "PF-1", "name": "Test"},
        expires_at=timezone.now() + timedelta(seconds=60),
    )
    claim = client.get(
        "/api/v1/internal/bridge/jobs/",
        {"bridge_device_id": "dev-1", "limit": 1},
        HTTP_X_DEVICE_KEY="test-device-key",
    )
    assert claim.status_code == 200
    assert claim.data["count"] == 1
    assert claim.data["jobs"][0]["id"] == str(job.id)
    job.refresh_from_db()
    assert job.status == BridgeDeviceJob.STATUS_CLAIMED

    done = client.post(
        f"/api/v1/internal/bridge/jobs/{job.id}/complete/",
        {"status": "succeeded", "result": {"ok": True, "user": {"user_id": "PF-1"}}},
        format="json",
        HTTP_X_DEVICE_KEY="test-device-key",
    )
    assert done.status_code == 200
    job.refresh_from_db()
    assert job.status == BridgeDeviceJob.STATUS_SUCCEEDED


def test_enqueue_and_wait_succeeds_when_worker_completes(client, settings):
    from biometrics import bridge
    from biometrics import jobs as bridge_jobs

    _heartbeat(client, settings)
    settings.BRIDGE_JOB_POLL_INTERVAL_SEC = 0.05

    def complete_pending(_interval: float) -> None:
        pending = (
            BridgeDeviceJob.objects.filter(status=BridgeDeviceJob.STATUS_PENDING)
            .order_by("created_at")
            .first()
        )
        if pending:
            pending.status = BridgeDeviceJob.STATUS_SUCCEEDED
            pending.result = {"ok": True, "templates": {"1": "YQ=="}}
            pending.completed_at = timezone.now()
            pending.save(
                update_fields=["status", "result", "completed_at", "updated_at"]
            )

    with patch("biometrics.jobs.time.sleep", side_effect=complete_pending):
        result = bridge_jobs.enqueue_and_wait(
            BridgeDeviceJob.KIND_GET_TEMPLATES,
            {"user_id": "PF-1"},
            timeout=5.0,
        )
    assert result.get("ok") is True
    assert "1" in (result.get("templates") or {})
    assert bridge.configured() is True


def test_enroll_times_out_without_worker(client, staff, member, settings):
    settings.BRIDGE_JOB_POLL_INTERVAL_SEC = 0.1
    _heartbeat(client, settings, online=True)
    # Shrink job wait by patching enqueue_and_wait timeout path via short timeout
    # on enroll_fingerprint — use ensure path that fails when no completer.
    from biometrics import bridge
    from biometrics.bridge import BridgeUnavailable

    with patch("biometrics.jobs.enqueue_and_wait", side_effect=BridgeUnavailable("timeout")):
        client.force_authenticate(staff)
        resp = client.post(
            f"/api/v1/admin/members/{member.pk}/fingerprint/enroll/",
            {"finger_id": 1},
            format="json",
        )
    assert resp.status_code == 503


def test_vault_export_and_ack(client, member, settings):
    settings.ATTENDANCE_DEVICE_KEY = "test-device-key"
    profile = member.member_profile
    raw = b"vault-template"
    MemberBiometricTemplate.objects.create(
        member=profile,
        finger_index=0,
        template_ciphertext=encrypt_bytes(raw),
        template_sha256=sha256_hex(raw),
    )
    _heartbeat(client, settings, bridge_device_id="dev-export")

    export = client.post(
        "/api/v1/internal/biometrics/vault-export/",
        {"member_ids": [profile.member_id], "include_staff": False},
        format="json",
        HTTP_X_DEVICE_KEY="test-device-key",
    )
    assert export.status_code == 200
    assert export.data["count"] == 1
    user = export.data["users"][0]
    assert user["user_id"] == profile.member_id
    assert user["templates"]["0"] == base64.b64encode(raw).decode()

    ack = client.post(
        "/api/v1/internal/biometrics/vault-sync-ack/",
        {
            "bridge_device_id": "dev-export",
            "member_ids": [profile.member_id],
            "staff_ids": [],
            "failures": [],
        },
        format="json",
        HTTP_X_DEVICE_KEY="test-device-key",
    )
    assert ack.status_code == 200
    assert ack.data["synced_members"] == 1
