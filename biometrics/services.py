from __future__ import annotations

import base64
import logging

from django.db.models import Prefetch
from django.utils import timezone

from biometrics import bridge, crypto
from biometrics.models import FingerprintDevice, FingerprintDeviceSyncState, MemberBiometricTemplate
from members.models import MemberProfile
from members.services import get_member

log = logging.getLogger(__name__)


def status_payload(*, device_id: str | None = None):
    st = bridge.device_status(device_id=device_id)
    return {
        "online": st.online,
        "bridge_ok": st.bridge_ok,
        "name": st.name,
        "serial": st.serial,
        "firmware": st.firmware,
        "user_count": st.user_count,
        "ip": st.ip,
        "port": st.port,
        "message": st.message,
    }


def _resolve_target_device(bridge_device_id: str | None = None) -> FingerprintDevice | None:
    if bridge_device_id:
        bid = str(bridge_device_id)
        device = FingerprintDevice.objects.filter(bridge_device_id=bid).first()
        if device:
            if not device.is_active:
                device.is_active = True
                device.save(update_fields=["is_active", "updated_at"])
            return device
        # Unique lan_ip/port placeholder so multiple bridge devices can be mirrored.
        return FingerprintDevice.objects.create(
            name=f"Bridge device {bid[:8]}",
            lan_ip=f"bridge-{bid[:32]}",
            port=4370,
            bridge_device_id=bid,
            is_active=True,
        )
    return FingerprintDevice.objects.filter(is_active=True).order_by("created_at").first()


def enroll_prepare(actor, member: MemberProfile, pin: str = "", *, device_id: str | None = None):
    _ = actor
    name = (member.user.full_name or member.member_id).strip() or member.member_id
    bridge.ensure_user(
        user_id=member.member_id, name=name, pin=pin or "", device_id=device_id
    )
    if pin:
        member.device_pin_enc = crypto.encrypt_bytes(pin.encode())
        member.device_pin_updated_at = timezone.now()
        member.save(update_fields=["device_pin_enc", "device_pin_updated_at", "updated_at"])
    return {
        "prepared": True,
        "message": (
            "Member is on the device. Capture the fingerprint on the scanner, "
            "then mark enrolled when done."
        ),
    }


def pull_templates(actor, member: MemberProfile, *, device_id: str | None = None) -> dict:
    _ = actor
    raw = bridge.get_templates(member.member_id, device_id=device_id)
    templates = raw.get("templates") or {}
    stored = 0
    for index_str, b64 in templates.items():
        finger_index = int(index_str)
        data = base64.b64decode(b64)
        MemberBiometricTemplate.objects.update_or_create(
            member=member,
            finger_index=finger_index,
            defaults={
                "template_ciphertext": crypto.encrypt_bytes(data),
                "template_sha256": crypto.sha256_hex(data),
                "algorithm": "zk",
                "template_format": "zk",
            },
        )
        stored += 1
    if stored and member.fingerprint_status != "ready":
        member.fingerprint_status = "ready"
        member.save(update_fields=["fingerprint_status", "updated_at"])
    return {"stored": stored, "fingerprint_status": member.fingerprint_status}


def push_vault_to_device(
    actor, member: MemberProfile, *, bridge_device_id: str | None = None
) -> dict:
    _ = actor
    name = (member.user.full_name or member.member_id).strip() or member.member_id
    pin = ""
    if member.device_pin_enc:
        pin = crypto.decrypt_bytes(member.device_pin_enc).decode()
    templates = {
        str(row.finger_index): base64.b64encode(crypto.decrypt_bytes(row.template_ciphertext)).decode()
        for row in member.biometric_templates.all()
    }
    device = _resolve_target_device(bridge_device_id)
    device_id = (device.bridge_device_id if device else "") or bridge_device_id
    bridge.push_user(
        user_id=member.member_id,
        name=name,
        pin=pin,
        templates=templates,
        device_id=device_id or None,
    )
    if device:
        FingerprintDeviceSyncState.objects.update_or_create(
            device=device,
            member=member,
            defaults={
                "templates_synced_at": timezone.now(),
                "pin_synced_at": timezone.now() if pin else None,
                "last_error": "",
            },
        )
    return {"pushed": True, "template_count": len(templates)}


def list_vault_members() -> dict:
    qs = (
        MemberProfile.objects.filter(biometric_templates__isnull=False)
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "biometric_templates",
                queryset=MemberBiometricTemplate.objects.order_by("finger_index"),
            )
        )
        .distinct()
        .order_by("member_id")
    )
    members = []
    for profile in qs:
        fingers = [row.finger_index for row in profile.biometric_templates.all()]
        if not fingers:
            continue
        members.append(
            {
                "member_id": profile.member_id,
                "name": (profile.user.full_name or profile.member_id).strip(),
                "finger_indexes": fingers,
                "has_pin": bool(profile.device_pin_enc),
                "fingerprint_status": profile.fingerprint_status,
            }
        )
    return {"count": len(members), "members": members}


def push_vault_bulk(*, bridge_device_id: str, member_ids: list[str] | None) -> dict:
    if not bridge_device_id:
        raise ValueError("bridge_device_id is required")
    qs = MemberProfile.objects.filter(biometric_templates__isnull=False).distinct()
    if member_ids is not None:
        qs = qs.filter(member_id__in=member_ids)
    pushed = 0
    failures = []
    for profile in qs.select_related("user").prefetch_related("biometric_templates"):
        if not profile.biometric_templates.exists():
            continue
        try:
            push_vault_to_device(None, profile, bridge_device_id=bridge_device_id)
            pushed += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("vault bulk push failed member=%s err=%s", profile.member_id, exc)
            failures.append({"member_id": profile.member_id, "error": str(exc)})
    return {"pushed": pushed, "failed": len(failures), "failures": failures}


def get_member_for_admin(pk):
    return get_member(pk)
