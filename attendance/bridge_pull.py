"""Deprecated attendance pull from zkteco-bridge (inbound to the gym LAN).

Production attendance is **bridge → API** push via the bridge poller
(``SYNC_ENABLED`` + ``API_BASE_URL`` + ``ATTENDANCE_DEVICE_KEY``).

``ATTENDANCE_BRIDGE_PULL`` remains for emergency/dev only and requires a
reachable legacy ``ZKTECO_BRIDGE_URL``. Prefer push; leave pull ``false``.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework.exceptions import NotFound as DrfNotFound
from rest_framework.exceptions import PermissionDenied as DrfPermissionDenied

from biometrics import bridge
from biometrics.bridge import BridgeUnavailable

from .models import CheckInPunch, StaffCheckInPunch
from .services import record_checkin

logger = logging.getLogger(__name__)

DHAKA = ZoneInfo("Asia/Dhaka")


def _punch_already_stored(at: datetime) -> bool:
    return (
        CheckInPunch.objects.filter(punched_at=at).exists()
        or StaffCheckInPunch.objects.filter(punched_at=at).exists()
    )

_stop = threading.Event()
_thread: threading.Thread | None = None
_started = False
_start_lock = threading.Lock()


def should_autostart() -> bool:
    """Only under long-lived servers (runserver child / gunicorn), not one-shot cmds."""
    argv = " ".join(sys.argv).lower()
    if "test" in sys.argv:
        return False
    if any(
        token in argv
        for token in (
            "migrate",
            "makemigrations",
            "collectstatic",
            "shell",
            "pull_bridge_attendance",
        )
    ):
        return False
    if "manage.py" in argv and "runserver" not in argv:
        return False
    if "runserver" in argv and os.environ.get("RUN_MAIN") != "true":
        return False
    return True


def parse_bridge_timestamp(raw: str) -> datetime | None:
    """Bridge stamps are naive local device time (Asia/Dhaka) unless offset/Z."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt: datetime | None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=DHAKA)
    return dt


def pull_once(*, lookback_days: int | None = None) -> dict[str, int]:
    """Fetch attendance from the configured bridge and record punches.

    Returns counts: ``fetched``, ``recorded``, ``skipped``, ``errors``.
    """
    # Legacy inbound pull: requires deprecated ZKTECO_BRIDGE_URL (not heartbeat).
    if not (
        getattr(settings, "ZKTECO_BRIDGE_URL", "")
        and getattr(settings, "ZKTECO_BRIDGE_KEY", "")
    ):
        return {"fetched": 0, "recorded": 0, "skipped": 0, "errors": 0}

    days = lookback_days
    if days is None:
        days = int(getattr(settings, "ATTENDANCE_BRIDGE_PULL_LOOKBACK_DAYS", 14) or 14)
    days = max(1, min(90, days))
    date_from = (datetime.now(DHAKA).date() - timedelta(days=days)).isoformat()

    try:
        rows = bridge.list_attendance(date_from=date_from)
    except BridgeUnavailable as exc:
        logger.warning("bridge attendance pull failed: %s", exc)
        return {"fetched": 0, "recorded": 0, "skipped": 0, "errors": 1}

    recorded = 0
    skipped = 0
    errors = 0
    # Oldest first so first punch becomes checked_in_at.
    ordered = sorted(rows, key=lambda r: str(r.get("timestamp") or ""))
    for row in ordered:
        user_id = str(row.get("user_id") or "").strip()
        ts_raw = str(row.get("timestamp") or "").strip()
        at = parse_bridge_timestamp(ts_raw)
        if not user_id or at is None:
            skipped += 1
            continue
        if _punch_already_stored(at):
            skipped += 1
            continue
        try:
            record_checkin(
                {
                    "member_id": user_id,
                    "checked_in_at": at,
                    "source": "device",
                }
            )
            recorded += 1
        except (DjangoPermissionDenied, DrfPermissionDenied, Http404, DrfNotFound):
            skipped += 1
        except Exception:  # noqa: BLE001 — keep poller alive
            errors += 1
            logger.warning(
                "bridge pull record failed user_id=%s ts=%s",
                user_id,
                ts_raw,
                exc_info=True,
            )
    return {
        "fetched": len(rows),
        "recorded": recorded,
        "skipped": skipped,
        "errors": errors,
    }


def _run_loop() -> None:
    interval = max(10, int(getattr(settings, "ATTENDANCE_BRIDGE_PULL_INTERVAL_SEC", 20) or 20))
    # Immediate catch-up, then interval.
    while not _stop.is_set():
        try:
            stats = pull_once()
            if stats["recorded"] or stats["errors"]:
                logger.info(
                    "bridge attendance pull fetched=%s recorded=%s skipped=%s errors=%s",
                    stats["fetched"],
                    stats["recorded"],
                    stats["skipped"],
                    stats["errors"],
                )
        except Exception:  # noqa: BLE001
            logger.exception("bridge attendance pull crashed")
        if _stop.wait(interval):
            return


def start_puller_thread() -> None:
    global _thread, _started
    with _start_lock:
        if _started and _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(
            target=_run_loop, name="bridge-attendance-pull", daemon=True
        )
        _thread.start()
        _started = True


def stop_puller() -> None:
    _stop.set()


def maybe_start_from_apps() -> None:
    if not getattr(settings, "ATTENDANCE_BRIDGE_PULL", False):
        return
    # Pull still needs a legacy inbound URL; outbound-only deploys leave this off.
    if not (getattr(settings, "ZKTECO_BRIDGE_URL", "") and getattr(settings, "ZKTECO_BRIDGE_KEY", "")):
        logger.info("attendance bridge pull disabled (legacy ZKTECO_BRIDGE_URL/KEY missing)")
        return
    if not should_autostart():
        return
    start_puller_thread()
    logger.info(
        "attendance bridge pull enabled interval=%ss bridge=%s",
        getattr(settings, "ATTENDANCE_BRIDGE_PULL_INTERVAL_SEC", 20),
        settings.ZKTECO_BRIDGE_URL,
    )
