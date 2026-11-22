"""HTTP client for the standalone zkteco-bridge. No-op when unset."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from django.conf import settings
from rest_framework.exceptions import APIException

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


def configured() -> bool:
    return bool(settings.ZKTECO_BRIDGE_URL and settings.ZKTECO_BRIDGE_KEY)


def _headers() -> dict[str, str]:
    return {"X-Bridge-Key": settings.ZKTECO_BRIDGE_KEY, "Content-Type": "application/json"}


def _client(*, timeout: float = 70.0) -> httpx.Client:
    return httpx.Client(
        base_url=settings.ZKTECO_BRIDGE_URL, timeout=timeout, headers=_headers()
    )


def require_configured() -> None:
    if not configured():
        raise BridgeUnavailable("Fingerprint device is not configured.")


def _bridge_error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, str) and err.strip():
            return err.strip()
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    except Exception:  # noqa: BLE001 — fall back to raw text
        pass
    text = (resp.text or "").strip()
    return text or f"Bridge error ({resp.status_code})."


def _device_params(device_id: str | None = None) -> dict[str, str]:
    if device_id:
        return {"device_id": str(device_id)}
    return {}


def device_status(*, device_id: str | None = None) -> DeviceStatus:
    if not configured():
        return DeviceStatus(
            online=False,
            bridge_ok=False,
            message="Fingerprint device is not configured.",
        )
    try:
        with _client() as client:
            resp = client.get("/internal/device/", params=_device_params(device_id))
            if resp.status_code >= 400:
                # Bridge answered; the scanner itself is unreachable / errored.
                detail = _bridge_error_detail(resp)
                return DeviceStatus(
                    online=False,
                    bridge_ok=True,
                    message=detail
                    or "Fingerprint device is offline. Try again when the scanner is connected.",
                )
            body = resp.json()
            device = body.get("device") or {}
            return DeviceStatus(
                online=True,
                bridge_ok=True,
                name=device.get("name") or "",
                serial=device.get("serial") or "",
                firmware=device.get("firmware") or "",
                user_count=int(device.get("user_count") or device.get("userCount") or 0),
                ip=device.get("ip") or "",
                port=int(device.get("port") or 0),
            )
    except httpx.HTTPError as exc:
        log.warning("zkteco bridge unreachable: %s", exc)
        return DeviceStatus(
            online=False,
            bridge_ok=False,
            message="Fingerprint device bridge is offline. Try again when the bridge is connected.",
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


# pyzk privilege levels mirrored on zkteco-bridge.
ZK_PRIVILEGE_DEFAULT = 0
ZK_PRIVILEGE_ADMIN = 14


def ensure_user(
    *,
    user_id: str,
    name: str,
    pin: str = "",
    uid: int = 0,
    device_id: str | None = None,
    privilege: int | None = None,
) -> dict:
    require_configured()
    try:
        with _client() as client:
            payload = {"user_id": user_id, "name": name, "pin": pin, "uid": uid}
            if device_id:
                payload["device_id"] = str(device_id)
            if privilege is not None:
                payload["privilege"] = int(privilege)
            resp = client.post("/internal/users/ensure/", json=payload)
            if resp.status_code >= 400:
                raise BridgeUnavailable(resp.text or "Bridge ensure failed.")
            return resp.json()
    except httpx.HTTPError as exc:
        raise BridgeUnavailable(str(exc)) from exc


def get_templates(user_id: str, *, device_id: str | None = None) -> dict:
    require_configured()
    try:
        with _client() as client:
            resp = client.get(
                f"/internal/users/{user_id}/templates/",
                params=_device_params(device_id),
            )
            if resp.status_code >= 400:
                raise BridgeUnavailable(resp.text or "Bridge templates failed.")
            return resp.json()
    except httpx.HTTPError as exc:
        raise BridgeUnavailable(str(exc)) from exc


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
    require_configured()
    try:
        with _client() as client:
            payload = {
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
            resp = client.post("/internal/users/push/", json=payload)
            if resp.status_code >= 400:
                raise BridgeUnavailable(resp.text or "Bridge push failed.")
            return resp.json()
    except httpx.HTTPError as exc:
        raise BridgeUnavailable(str(exc)) from exc


def enroll_fingerprint(
    user_id: str,
    finger_id: int,
    *,
    device_id: str | None = None,
) -> dict:
    """Interactive capture on the scanner; bridge blocks until done (~1–2 min)."""
    require_configured()
    try:
        with _client(timeout=120.0) as client:
            payload: dict = {"user_id": user_id, "finger_id": int(finger_id)}
            if device_id:
                payload["device_id"] = str(device_id)
            resp = client.post("/internal/users/enroll/", json=payload)
            if resp.status_code >= 400:
                raise BridgeUnavailable(_bridge_error_detail(resp))
            return resp.json()
    except httpx.HTTPError as exc:
        raise BridgeUnavailable(str(exc)) from exc


def delete_fingerprint(
    user_id: str,
    finger_id: int,
    *,
    device_id: str | None = None,
) -> dict:
    require_configured()
    try:
        with _client() as client:
            resp = client.delete(
                f"/internal/users/{user_id}/templates/{int(finger_id)}/",
                params=_device_params(device_id),
            )
            if resp.status_code >= 400:
                raise BridgeUnavailable(resp.text or "Bridge delete failed.")
            return resp.json()
    except httpx.HTTPError as exc:
        raise BridgeUnavailable(str(exc)) from exc


def list_attendance(
    *,
    user_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    device_id: str | None = None,
) -> list[dict]:
    """Live attendance rows from the bridge (device log, newest-first on bridge)."""
    require_configured()
    params = _device_params(device_id)
    if user_id:
        params["user_id"] = user_id
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    try:
        with _client(timeout=45.0) as client:
            resp = client.get("/internal/attendance/", params=params)
            if resp.status_code >= 400:
                raise BridgeUnavailable(_bridge_error_detail(resp))
            body = resp.json()
            rows = body.get("attendance") if isinstance(body, dict) else None
            if not isinstance(rows, list):
                raise BridgeUnavailable("Bridge returned invalid attendance payload.")
            return [row for row in rows if isinstance(row, dict)]
    except httpx.HTTPError as exc:
        raise BridgeUnavailable(str(exc)) from exc
