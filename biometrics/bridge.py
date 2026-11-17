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


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.ZKTECO_BRIDGE_URL, timeout=70.0, headers=_headers())


def require_configured() -> None:
    if not configured():
        raise BridgeUnavailable("Fingerprint device is not configured.")


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
                return DeviceStatus(
                    online=False,
                    bridge_ok=False,
                    message=f"Bridge error ({resp.status_code}).",
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
            message="Fingerprint device is offline. Try again when the bridge is connected.",
        )


def ensure_user(
    *,
    user_id: str,
    name: str,
    pin: str = "",
    uid: int = 0,
    device_id: str | None = None,
) -> dict:
    require_configured()
    try:
        with _client() as client:
            payload = {"user_id": user_id, "name": name, "pin": pin, "uid": uid}
            if device_id:
                payload["device_id"] = str(device_id)
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
            resp = client.post("/internal/users/push/", json=payload)
            if resp.status_code >= 400:
                raise BridgeUnavailable(resp.text or "Bridge push failed.")
            return resp.json()
    except httpx.HTTPError as exc:
        raise BridgeUnavailable(str(exc)) from exc
