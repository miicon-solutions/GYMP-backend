"""Bridge device job queue: enqueue from admin APIs; claim/complete from LAN bridge."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from biometrics.models import BridgeDeviceJob, FingerprintDevice

log = logging.getLogger(__name__)

TERMINAL = frozenset(
    {
        BridgeDeviceJob.STATUS_SUCCEEDED,
        BridgeDeviceJob.STATUS_FAILED,
        BridgeDeviceJob.STATUS_EXPIRED,
    }
)


def heartbeat_stale_seconds() -> int:
    return max(15, int(getattr(settings, "BRIDGE_HEARTBEAT_STALE_SEC", 90) or 90))


def bridge_connected(*, device_id: str | None = None) -> bool:
    """True when a bridge worker heartbeated recently (scanner may still be offline)."""
    cutoff = timezone.now() - timedelta(seconds=heartbeat_stale_seconds())
    qs = FingerprintDevice.objects.filter(is_active=True, last_seen_at__gte=cutoff)
    if device_id:
        qs = qs.filter(bridge_device_id=str(device_id))
    return qs.exists()


def record_heartbeat(data: dict[str, Any]) -> FingerprintDevice:
    """Upsert FingerprintDevice reachability from the outbound bridge worker."""
    bridge_device_id = str(data.get("bridge_device_id") or "").strip()
    online = bool(data.get("online"))
    name = str(data.get("name") or "").strip()
    serial = str(data.get("serial") or "").strip()
    firmware = str(data.get("firmware") or "").strip()
    ip = str(data.get("ip") or "").strip()
    try:
        port = int(data.get("port") or 4370)
    except (TypeError, ValueError):
        port = 4370
    try:
        user_count = int(data.get("user_count") or 0)
    except (TypeError, ValueError):
        user_count = 0

    now = timezone.now()
    device: FingerprintDevice | None = None
    if bridge_device_id:
        device = FingerprintDevice.objects.filter(bridge_device_id=bridge_device_id).first()

    if device is None and ip:
        device = FingerprintDevice.objects.filter(lan_ip=ip, port=port).first()

    if device is None:
        lan = ip or (f"bridge-{(bridge_device_id or 'default')[:32]}")
        # Avoid unique collision on placeholder lan_ip/port.
        if FingerprintDevice.objects.filter(lan_ip=lan, port=port).exists():
            lan = f"{lan}-{now.strftime('%H%M%S')}"
        device = FingerprintDevice(
            name=name or f"Bridge device {(bridge_device_id or 'default')[:8]}",
            lan_ip=lan,
            port=port,
            bridge_device_id=bridge_device_id,
            is_active=True,
        )

    if name:
        device.name = name
    if serial:
        device.serial = serial
    if firmware:
        device.firmware = firmware
    if ip:
        device.lan_ip = ip
    device.port = port
    device.user_count = max(0, user_count)
    device.scanner_online = online
    device.last_seen_at = now
    device.is_active = True
    if bridge_device_id:
        device.bridge_device_id = bridge_device_id
    device.save()
    return device


def enqueue(
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    bridge_device_id: str | None = None,
    timeout: float = 70.0,
    idempotency_key: str = "",
) -> BridgeDeviceJob:
    now = timezone.now()
    expires = now + timedelta(seconds=max(5.0, float(timeout)))
    return BridgeDeviceJob.objects.create(
        kind=kind,
        status=BridgeDeviceJob.STATUS_PENDING,
        payload=payload or {},
        bridge_device_id=str(bridge_device_id or "").strip(),
        idempotency_key=(idempotency_key or "")[:120],
        expires_at=expires,
    )


def _expire_if_needed(job: BridgeDeviceJob) -> BridgeDeviceJob:
    if job.status in TERMINAL:
        return job
    if job.expires_at and job.expires_at <= timezone.now():
        BridgeDeviceJob.objects.filter(
            pk=job.pk,
            status__in=(BridgeDeviceJob.STATUS_PENDING, BridgeDeviceJob.STATUS_CLAIMED),
        ).update(
            status=BridgeDeviceJob.STATUS_EXPIRED,
            error=job.error or "Bridge job expired before completion.",
            completed_at=timezone.now(),
        )
        job.refresh_from_db()
    return job


def enqueue_and_wait(
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    bridge_device_id: str | None = None,
    timeout: float = 70.0,
    poll_interval: float | None = None,
) -> dict[str, Any]:
    """Create a job and block until the bridge completes it (or timeout)."""
    from biometrics.bridge import BridgeUnavailable

    device_id = str(bridge_device_id or (payload or {}).get("device_id") or "").strip() or None
    if not bridge_connected(device_id=device_id):
        raise BridgeUnavailable(
            "Fingerprint device bridge is offline. Try again when the bridge is connected."
        )

    job = enqueue(
        kind,
        payload,
        bridge_device_id=device_id,
        timeout=timeout,
    )
    interval = poll_interval
    if interval is None:
        interval = float(getattr(settings, "BRIDGE_JOB_POLL_INTERVAL_SEC", 0.4) or 0.4)
    interval = max(0.1, interval)
    deadline = time.monotonic() + max(5.0, float(timeout))

    while time.monotonic() < deadline:
        job.refresh_from_db()
        job = _expire_if_needed(job)
        if job.status == BridgeDeviceJob.STATUS_SUCCEEDED:
            return job.result if isinstance(job.result, dict) else {"ok": True}
        if job.status == BridgeDeviceJob.STATUS_FAILED:
            raise BridgeUnavailable(job.error or "Bridge job failed.")
        if job.status == BridgeDeviceJob.STATUS_EXPIRED:
            raise BridgeUnavailable(
                job.error or "Fingerprint device bridge did not complete the request in time."
            )
        time.sleep(interval)

    job = _expire_if_needed(job)
    if job.status == BridgeDeviceJob.STATUS_SUCCEEDED:
        return job.result if isinstance(job.result, dict) else {"ok": True}
    if job.status == BridgeDeviceJob.STATUS_FAILED:
        raise BridgeUnavailable(job.error or "Bridge job failed.")

    BridgeDeviceJob.objects.filter(
        pk=job.pk,
        status__in=(BridgeDeviceJob.STATUS_PENDING, BridgeDeviceJob.STATUS_CLAIMED),
    ).update(
        status=BridgeDeviceJob.STATUS_EXPIRED,
        error="Fingerprint device bridge did not complete the request in time.",
        completed_at=timezone.now(),
    )
    raise BridgeUnavailable(
        "Fingerprint device bridge did not complete the request in time."
    )


@transaction.atomic
def claim_next(*, bridge_device_id: str | None = None, limit: int = 1) -> list[BridgeDeviceJob]:
    """Atomically claim pending jobs for the bridge worker."""
    now = timezone.now()
    # Expire stale pending/claimed before selecting.
    BridgeDeviceJob.objects.filter(
        status__in=(BridgeDeviceJob.STATUS_PENDING, BridgeDeviceJob.STATUS_CLAIMED),
        expires_at__lte=now,
    ).update(
        status=BridgeDeviceJob.STATUS_EXPIRED,
        error="Bridge job expired before completion.",
        completed_at=now,
    )

    qs = (
        BridgeDeviceJob.objects.select_for_update(skip_locked=True)
        .filter(status=BridgeDeviceJob.STATUS_PENDING)
        .order_by("created_at")
    )
    bid = str(bridge_device_id or "").strip()
    if bid:
        # Prefer jobs targeted at this device, then unscoped jobs.
        targeted = list(qs.filter(bridge_device_id=bid)[: max(1, int(limit))])
        if targeted:
            claimed = targeted
        else:
            claimed = list(qs.filter(bridge_device_id="")[: max(1, int(limit))])
    else:
        claimed = list(qs[: max(1, int(limit))])

    out: list[BridgeDeviceJob] = []
    for job in claimed:
        job.status = BridgeDeviceJob.STATUS_CLAIMED
        job.claimed_at = now
        if bid and not job.bridge_device_id:
            job.bridge_device_id = bid
        job.save(
            update_fields=["status", "claimed_at", "bridge_device_id", "updated_at"]
        )
        out.append(job)
    return out


def complete_job(
    job_id,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> BridgeDeviceJob:
    try:
        job = BridgeDeviceJob.objects.get(pk=job_id)
    except BridgeDeviceJob.DoesNotExist as exc:
        from rest_framework.exceptions import NotFound

        raise NotFound("Bridge job not found.") from exc

    if job.status in TERMINAL:
        return job

    status = (status or "").strip().lower()
    if status not in (BridgeDeviceJob.STATUS_SUCCEEDED, BridgeDeviceJob.STATUS_FAILED):
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"status": "Must be succeeded or failed."})

    job.status = status
    job.result = result if isinstance(result, dict) else {}
    job.error = (error or "")[:2000]
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "result", "error", "completed_at", "updated_at"])
    return job


def job_wire(job: BridgeDeviceJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "kind": job.kind,
        "status": job.status,
        "payload": job.payload if isinstance(job.payload, dict) else {},
        "bridge_device_id": job.bridge_device_id or "",
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
