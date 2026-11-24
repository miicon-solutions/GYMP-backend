"""Fingerprint device control via outbound bridge jobs (no ZKTECO_BRIDGE_URL)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import APIException

from biometrics import jobs
from biometrics.models import BridgeDeviceJob, FingerprintDevice

log = logging.getLogger(__name__)


class BridgeUnavailable(APIException):
    status_code = 503
    default_detail = "Fingerprint device bridge is not configured or unreachable."
    default_code = "bridge_unavailable"


@dataclass
class DeviceStatus:
    online: bool
    bridge_ok: bool
    name: str = ""
    serial: str = ""
    firmware: str = ""
    user_count: int = 0
    ip: str = ""
    port: int = 0
    message: str = ""
    last_seen_at: datetime | None = None
    heartbeat_age_sec: int | None = None
    bridge_device_id: str = ""


# pyzk privilege levels mirrored on zkteco-bridge.
ZK_PRIVILEGE_DEFAULT = 0
ZK_PRIVILEGE_ADMIN = 14


def configured() -> bool:
    """True when a bridge worker has heartbeated recently."""
    return jobs.bridge_connected()


def require_configured() -> None:
    if not configured():
        raise BridgeUnavailable(
            "Fingerprint device bridge is offline. Try again when the bridge is connected."
        )


def _device_qs(*, device_id: str | None = None):
    qs = FingerprintDevice.objects.filter(is_active=True)
    if device_id:
        qs = qs.filter(bridge_device_id=str(device_id))
    return qs


def _heartbeat_age_sec(last_seen_at: datetime | None) -> int | None:
    if last_seen_at is None:
        return None
    return max(0, int((timezone.now() - last_seen_at).total_seconds()))


def device_status(*, device_id: str | None = None) -> DeviceStatus:
    """Read last bridge heartbeat (no live probe; worker reports periodically)."""
    cutoff = timezone.now() - timedelta(seconds=jobs.heartbeat_stale_seconds())
    qs = _device_qs(device_id=device_id).filter(last_seen_at__gte=cutoff)
    device = qs.order_by("-last_seen_at").first()
    if device is None:
        # Any historical device row for messaging, or empty.
        any_device = _device_qs(device_id=device_id).order_by("-last_seen_at").first()
        if any_device is None and not device_id:
            any_device = FingerprintDevice.objects.order_by("-last_seen_at").first()
        return DeviceStatus(
            online=False,
            bridge_ok=False,
            name=(any_device.name if any_device else ""),
            serial=(any_device.serial if any_device else ""),
            firmware=(any_device.firmware if any_device else ""),
            user_count=int(any_device.user_count if any_device else 0),
            ip=(any_device.lan_ip if any_device else ""),
            port=int(any_device.port if any_device else 0),
            message="Fingerprint device bridge is offline. Try again when the bridge is connected.",
            last_seen_at=(any_device.last_seen_at if any_device else None),
            heartbeat_age_sec=_heartbeat_age_sec(
                any_device.last_seen_at if any_device else None
            ),
            bridge_device_id=(any_device.bridge_device_id if any_device else "") or "",
        )

    online = bool(device.scanner_online)
    return DeviceStatus(
        online=online,
        bridge_ok=True,
        name=device.name or "",
        serial=device.serial or "",
        firmware=device.firmware or "",
        user_count=int(device.user_count or 0),
        ip=device.lan_ip or "",
        port=int(device.port or 0),
        message=(
            ""
            if online
            else "Fingerprint device is offline. Try again when the scanner is connected."
        ),
        last_seen_at=device.last_seen_at,
        heartbeat_age_sec=_heartbeat_age_sec(device.last_seen_at),
        bridge_device_id=device.bridge_device_id or "",
    )


def require_device_online(*, device_id: str | None = None) -> DeviceStatus:
    """Raise BridgeUnavailable when the scanner cannot be managed."""
    st = device_status(device_id=device_id)
    if st.online:
        return st
    raise BridgeUnavailable(
        st.message
        or "Fingerprint device is offline. Try again when the scanner is connected."
    )


def ensure_user(
    *,
    user_id: str,
    name: str,
    pin: str = "",
    uid: int = 0,
    device_id: str | None = None,
    privilege: int | None = None,
) -> dict:
    payload: dict = {"user_id": user_id, "name": name, "pin": pin, "uid": uid}
    if device_id:
        payload["device_id"] = str(device_id)
    if privilege is not None:
        payload["privilege"] = int(privilege)
    return jobs.enqueue_and_wait(
        BridgeDeviceJob.KIND_ENSURE_USER,
        payload,
        bridge_device_id=device_id,
        timeout=70.0,
    )


def get_templates(user_id: str, *, device_id: str | None = None) -> dict:
    payload: dict = {"user_id": user_id}
    if device_id:
        payload["device_id"] = str(device_id)
    return jobs.enqueue_and_wait(
        BridgeDeviceJob.KIND_GET_TEMPLATES,
        payload,
        bridge_device_id=device_id,
        timeout=70.0,
    )


def push_user(
    *,
    user_id: str,
    name: str,
    pin: str = "",
    uid: int = 0,
    templates: dict[str, str] | None = None,
    device_id: str | None = None,
    privilege: int | None = None,
) -> dict:
    payload: dict = {
        "user_id": user_id,
        "name": name,
        "pin": pin,
        "uid": uid,
        "templates": templates or {},
    }
    if device_id:
        payload["device_id"] = str(device_id)
    if privilege is not None:
        payload["privilege"] = int(privilege)
    return jobs.enqueue_and_wait(
        BridgeDeviceJob.KIND_PUSH_USER,
        payload,
        bridge_device_id=device_id,
        timeout=70.0,
    )


def enroll_fingerprint(
    user_id: str,
    finger_id: int,
    *,
    device_id: str | None = None,
) -> dict:
    """Interactive capture on the scanner; waits until bridge completes (~1–2 min)."""
    payload: dict = {"user_id": user_id, "finger_id": int(finger_id)}
    if device_id:
        payload["device_id"] = str(device_id)
    return jobs.enqueue_and_wait(
        BridgeDeviceJob.KIND_ENROLL,
        payload,
        bridge_device_id=device_id,
        timeout=120.0,
    )


def delete_fingerprint(
    user_id: str,
    finger_id: int,
    *,
    device_id: str | None = None,
) -> dict:
    payload: dict = {"user_id": user_id, "finger_id": int(finger_id)}
    if device_id:
        payload["device_id"] = str(device_id)
    return jobs.enqueue_and_wait(
        BridgeDeviceJob.KIND_DELETE_FINGERPRINT,
        payload,
        bridge_device_id=device_id,
        timeout=70.0,
    )


def list_attendance(
    *,
    user_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    device_id: str | None = None,
) -> list[dict]:
    """Deprecated pull helper. Prefer bridge→API push. Uses legacy URL if set."""
    import httpx

    base = (getattr(settings, "ZKTECO_BRIDGE_URL", "") or "").rstrip("/")
    key = getattr(settings, "ZKTECO_BRIDGE_KEY", "") or ""
    if not base or not key:
        raise BridgeUnavailable(
            "Attendance pull is disabled; the bridge pushes punches to the API."
        )
    params: dict[str, str] = {}
    if device_id:
        params["device_id"] = str(device_id)
    if user_id:
        params["user_id"] = user_id
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    try:
        with httpx.Client(
            base_url=base,
            timeout=45.0,
            headers={"X-Bridge-Key": key, "Content-Type": "application/json"},
        ) as client:
            resp = client.get("/internal/attendance/", params=params)
            if resp.status_code >= 400:
                raise BridgeUnavailable(
                    (resp.text or "").strip() or f"Bridge error ({resp.status_code})."
                )
            body = resp.json()
            rows = body.get("attendance") if isinstance(body, dict) else None
            if not isinstance(rows, list):
                raise BridgeUnavailable("Bridge returned invalid attendance payload.")
            return [row for row in rows if isinstance(row, dict)]
    except httpx.HTTPError as exc:
        raise BridgeUnavailable(str(exc)) from exc
