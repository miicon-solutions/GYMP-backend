from __future__ import annotations

import base64

from django.utils import timezone

from biometrics import bridge, crypto
from biometrics.models import FingerprintDevice, MemberBiometricTemplate
from members.models import MemberProfile
from members.services import get_member


def status_payload():
    st = bridge.device_status()
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


def enroll_prepare(actor, member: MemberProfile, pin: str = ""):
    _ = actor
    name = (member.user.full_name or member.member_id).strip() or member.member_id
    bridge.ensure_user(user_id=member.member_id, name=name, pin=pin or "")
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


def pull_templates(actor, member: MemberProfile) -> dict:
    _ = actor
    raw = bridge.get_templates(member.member_id)
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


def push_vault_to_device(actor, member: MemberProfile) -> dict:
    _ = actor
    name = (member.user.full_name or member.member_id).strip() or member.member_id
    pin = ""
    if member.device_pin_enc:
        pin = crypto.decrypt_bytes(member.device_pin_enc).decode()
    templates = {
        str(row.finger_index): base64.b64encode(crypto.decrypt_bytes(row.template_ciphertext)).decode()
        for row in member.biometric_templates.all()
    }
    bridge.push_user(user_id=member.member_id, name=name, pin=pin, templates=templates)
    device = FingerprintDevice.objects.filter(is_active=True).order_by("created_at").first()
    if device:
        from biometrics.models import FingerprintDeviceSyncState

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


def get_member_for_admin(pk):
    return get_member(pk)
