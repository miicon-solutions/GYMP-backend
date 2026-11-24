"""Device keypad id + random PIN helpers (ZK keypad is digits-only)."""

from __future__ import annotations

import re
import secrets
from typing import Any

from django.db import transaction
from django.utils import timezone

from accounts.models import StaffProfile
from biometrics import crypto
from members.models import MemberProfile

DEVICE_PIN_LENGTH = 4
KEYPAD_ID_MAX_LEN = 9  # typical ZK PIN/user_id width
_TRIVIAL_PINS = frozenset(
    {
        "0000",
        "1111",
        "2222",
        "3333",
        "4444",
        "5555",
        "6666",
        "7777",
        "8888",
        "9999",
        "1234",
        "4321",
        "1212",
        "2121",
        "1122",
        "1221",
    }
)
_DIGITS_RE = re.compile(r"\D+")


def generate_device_pin(*, length: int = DEVICE_PIN_LENGTH) -> str:
    """Return a random numeric PIN that avoids trivial sequences.

    First digit is never ``0`` — ZK keypad entry often cannot start with zero.
    """
    length = max(4, min(8, int(length or DEVICE_PIN_LENGTH)))
    for _ in range(64):
        # First digit 1–9; remaining digits 0–9 (no modulo bias).
        digits = [str(secrets.randbelow(9) + 1)]
        digits.extend(str(secrets.randbelow(10)) for _ in range(length - 1))
        pin = "".join(digits)
        if pin not in _TRIVIAL_PINS and len(set(pin)) > 1:
            return pin
    return "1" + "".join(str(secrets.randbelow(10)) for _ in range(length - 1))


def decrypt_device_pin(profile: Any) -> str:
    enc = getattr(profile, "device_pin_enc", "") or ""
    if not enc:
        return ""
    try:
        return crypto.decrypt_bytes(enc).decode()
    except Exception:  # noqa: BLE001
        return ""


def ensure_device_pin(profile: Any, *, rotate: bool = False) -> str:
    """Return plaintext PIN; generate+store when missing, wrong length, or rotate=True."""
    if not rotate:
        existing = decrypt_device_pin(profile)
        if (
            existing
            and existing.isdigit()
            and len(existing) == DEVICE_PIN_LENGTH
            and not existing.startswith("0")
        ):
            return existing
    pin = generate_device_pin()
    profile.device_pin_enc = crypto.encrypt_bytes(pin.encode())
    profile.device_pin_updated_at = timezone.now()
    profile.save(update_fields=["device_pin_enc", "device_pin_updated_at", "updated_at"])
    return pin


def normalize_keypad_id(raw: str) -> str:
    """Digits-only keypad id with no leading zeros (PF-0003 → 3; reject 0)."""
    digits = _DIGITS_RE.sub("", raw or "")
    if not digits:
        return ""
    digits = digits[-KEYPAD_ID_MAX_LEN:]
    n = int(digits)
    if n == 0:
        return ""
    return str(n)


def keypad_lookup_ids(punch_id: str) -> list[str]:
    """Exact punch id plus zero-padded / normalized variants for legacy rows."""
    raw = (punch_id or "").strip()
    if not raw.isdigit():
        return [raw] if raw else []
    norm = normalize_keypad_id(raw)
    ids: list[str] = []
    seen: set[str] = set()
    for candidate in (raw, norm):
        if candidate and candidate not in seen:
            seen.add(candidate)
            ids.append(candidate)
    if norm:
        for width in range(len(norm), KEYPAD_ID_MAX_LEN + 1):
            padded = norm.zfill(width)
            if padded not in seen:
                seen.add(padded)
                ids.append(padded)
    return ids


def _digits_from_display(display_id: str) -> str:
    return normalize_keypad_id(display_id)


def _keypad_taken(keypad_id: str, *, exclude_member=None, exclude_staff=None) -> bool:
    """True if another profile already owns this keypad id (incl. zero-padded)."""
    if not keypad_id or not str(keypad_id).isdigit():
        return True
    target = int(keypad_id)

    mq = MemberProfile.objects.exclude(device_keypad_id="")
    if exclude_member is not None:
        mq = mq.exclude(pk=exclude_member.pk)
    for raw in mq.values_list("device_keypad_id", flat=True):
        if str(raw).isdigit() and int(raw) == target:
            return True

    sq = StaffProfile.objects.exclude(device_keypad_id="")
    if exclude_staff is not None:
        sq = sq.exclude(pk=exclude_staff.pk)
    for raw in sq.values_list("device_keypad_id", flat=True):
        if str(raw).isdigit() and int(raw) == target:
            return True
    return False


def _next_free_keypad_id(*, exclude_member=None, exclude_staff=None) -> str:
    """Allocate the next free integer string in the shared keypad namespace."""
    del exclude_member, exclude_staff  # API parity with _keypad_taken
    used: set[int] = set()
    for raw in MemberProfile.objects.exclude(device_keypad_id="").values_list(
        "device_keypad_id", flat=True
    ):
        if str(raw).isdigit():
            used.add(int(raw))
    for raw in StaffProfile.objects.exclude(device_keypad_id="").values_list(
        "device_keypad_id", flat=True
    ):
        if str(raw).isdigit():
            used.add(int(raw))
    n = 1
    while n in used or n == 0:
        n += 1
        if n > 10**KEYPAD_ID_MAX_LEN:
            raise RuntimeError("device keypad id space exhausted")
    return str(n)


@transaction.atomic
def ensure_device_keypad_id(profile: Any) -> str:
    """Ensure a unique unpadded digits-only keypad id is stored on the profile.

    Migrates legacy zero-padded ids (``0003`` → ``3``). Callers that push to
    the scanner should soft-delete the previous padded ``user_id`` when it
    changes (see ``_retire_legacy_display_user``).
    """
    existing = (getattr(profile, "device_keypad_id", "") or "").strip()
    if isinstance(profile, MemberProfile):
        exclude_member, exclude_staff = profile, None
        display = profile.member_id
    elif isinstance(profile, StaffProfile):
        exclude_member, exclude_staff = None, profile
        display = profile.short_id
    else:
        raise TypeError("profile must be MemberProfile or StaffProfile")

    if existing.isdigit():
        normalized = normalize_keypad_id(existing)
        if normalized == existing:
            return existing
        if normalized and not _keypad_taken(
            normalized, exclude_member=exclude_member, exclude_staff=exclude_staff
        ):
            profile.device_keypad_id = normalized
            profile.save(update_fields=["device_keypad_id", "updated_at"])
            return normalized
        # Normalized form taken by someone else, or existing was all zeros.
        keypad = _next_free_keypad_id(
            exclude_member=exclude_member, exclude_staff=exclude_staff
        )
        profile.device_keypad_id = keypad
        profile.save(update_fields=["device_keypad_id", "updated_at"])
        return keypad

    candidate = _digits_from_display(display)
    if candidate and not _keypad_taken(
        candidate, exclude_member=exclude_member, exclude_staff=exclude_staff
    ):
        keypad = candidate
    else:
        keypad = _next_free_keypad_id(
            exclude_member=exclude_member, exclude_staff=exclude_staff
        )

    profile.device_keypad_id = keypad
    profile.save(update_fields=["device_keypad_id", "updated_at"])
    return keypad


def device_user_id_for_profile(profile: Any) -> str:
    """ZK user_id to write/delete: stored keypad id, else legacy display id.

    Callers that provision should run ``ensure_device_keypad_id`` first so the
    stored value has no leading zeros.
    """
    keypad = (getattr(profile, "device_keypad_id", "") or "").strip()
    if keypad.isdigit():
        return keypad
    if isinstance(profile, MemberProfile):
        return (profile.member_id or "").strip()
    if isinstance(profile, StaffProfile):
        return (profile.short_id or "").strip()
    return ""
