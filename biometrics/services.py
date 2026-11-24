from __future__ import annotations

import base64
import logging

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from accounts.models import StaffProfile, User
from biometrics import bridge, crypto
from biometrics.models import (
    FingerprintDevice,
    FingerprintDeviceStaffSyncState,
    FingerprintDeviceSyncState,
    MemberBiometricTemplate,
    StaffBiometricTemplate,
)
from members.models import MemberProfile
from members.services import get_member
from operations.services import record

log = logging.getLogger(__name__)


def _staff_privilege(staff: StaffProfile) -> int:
    return bridge.ZK_PRIVILEGE_ADMIN if staff.device_admin else bridge.ZK_PRIVILEGE_DEFAULT


def staff_profile_for_user(user: User) -> StaffProfile:
    try:
        return user.staff_profile
    except StaffProfile.DoesNotExist as exc:
        raise NotFound("Staff profile not found.") from exc


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
        "last_seen_at": st.last_seen_at,
        "heartbeat_age_sec": st.heartbeat_age_sec,
    }


def bridge_ping_payload(*, device_id: str | None = None) -> dict:
    """Lightweight connection check for admin UIs (heartbeat freshness)."""
    st = bridge.device_status(device_id=device_id)
    if st.bridge_ok and st.online:
        message = "Bridge connected; scanner online."
    elif st.bridge_ok:
        message = st.message or "Bridge connected; scanner offline."
    else:
        message = st.message or "Bridge offline (no recent heartbeat)."
    return {
        "ok": st.bridge_ok,
        "bridge_connected": st.bridge_ok,
        "scanner_online": st.online,
        "message": message,
        "last_seen_at": st.last_seen_at,
        "heartbeat_age_sec": st.heartbeat_age_sec,
        "bridge_device_id": st.bridge_device_id,
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


def _finger_indexes(member: MemberProfile) -> list[int]:
    return list(
        member.biometric_templates.order_by("finger_index").values_list(
            "finger_index", flat=True
        )
    )


def list_member_templates(member: MemberProfile) -> dict:
    return {
        "finger_indexes": _finger_indexes(member),
        "fingerprint_status": member.fingerprint_status,
    }


def enroll_prepare(actor, member: MemberProfile, pin: str = "", *, device_id: str | None = None):
    """Ensure the member exists on the device (used internally before interactive enroll)."""
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


def enroll_interactive(
    actor,
    member: MemberProfile,
    finger_id: int,
    *,
    pin: str = "",
    device_id: str | None = None,
) -> dict:
    try:
        finger_id = int(finger_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"finger_id": "Must be an integer 0–9."}) from exc
    if finger_id < 0 or finger_id > 9:
        raise ValidationError({"finger_id": "Must be between 0 and 9."})

    bridge.require_device_online(device_id=device_id)
    name = (member.user.full_name or member.member_id).strip() or member.member_id
    pin_value = pin or ""
    if pin_value:
        member.device_pin_enc = crypto.encrypt_bytes(pin_value.encode())
        member.device_pin_updated_at = timezone.now()
        member.save(update_fields=["device_pin_enc", "device_pin_updated_at", "updated_at"])
    # Single outbound job: ensure + capture + return templates (avoids 3 poll cycles).
    session = bridge.enroll_session(
        user_id=member.member_id,
        name=name,
        finger_id=finger_id,
        pin=pin_value,
        device_id=device_id,
    )
    pulled = store_member_templates(
        actor, member, templates=session.get("templates") or {}
    )
    member.refresh_from_db(fields=["fingerprint_status"])
    indexes = _finger_indexes(member)
    if actor is not None:
        record(
            actor,
            "member",
            "update",
            "adminActivityMemberFingerprintUpdated",
            {"memberId": member.member_id, "status": member.fingerprint_status, "fingerId": finger_id},
        )
    return {
        "enrolled": True,
        "finger_id": finger_id,
        "stored": int(pulled.get("stored") or 0),
        "fingerprint_status": member.fingerprint_status,
        "finger_indexes": indexes,
    }


def delete_member_template(
    actor,
    member: MemberProfile,
    finger_id: int,
    *,
    device_id: str | None = None,
) -> dict:
    try:
        finger_id = int(finger_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"finger_id": "Must be an integer 0–9."}) from exc
    if finger_id < 0 or finger_id > 9:
        raise ValidationError({"finger_id": "Must be between 0 and 9."})

    bridge.require_device_online(device_id=device_id)
    bridge.delete_fingerprint(member.member_id, finger_id, device_id=device_id)
    MemberBiometricTemplate.objects.filter(member=member, finger_index=finger_id).delete()
    indexes = _finger_indexes(member)
    if not indexes and member.fingerprint_status not in ("not_required",):
        member.fingerprint_status = "pending"
        member.save(update_fields=["fingerprint_status", "updated_at"])
    if actor is not None:
        record(
            actor,
            "member",
            "update",
            "adminActivityMemberFingerprintUpdated",
            {
                "memberId": member.member_id,
                "status": member.fingerprint_status,
                "fingerId": finger_id,
                "deleted": True,
            },
        )
    return {
        "finger_indexes": indexes,
        "fingerprint_status": member.fingerprint_status,
    }


def store_member_templates(
    actor, member: MemberProfile, *, templates: dict
) -> dict:
    """Persist base64 template map into the vault (no device call)."""
    _ = actor
    stored = 0
    for index_str, b64 in (templates or {}).items():
        if not isinstance(b64, str) or not b64:
            continue
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
        from notifications.services import notify_fingerprint_ready

        notify_fingerprint_ready(member.user)
    return {"stored": stored, "fingerprint_status": member.fingerprint_status}


def pull_templates(actor, member: MemberProfile, *, device_id: str | None = None) -> dict:
    raw = bridge.get_templates(member.member_id, device_id=device_id)
    return store_member_templates(actor, member, templates=raw.get("templates") or {})


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
    """Legacy: enqueue push_user jobs per member (bridge worker applies locally)."""
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


def export_vault(
    *,
    member_ids: list[str] | None = None,
    include_staff: bool = True,
) -> dict:
    """Return decrypted vault payloads for the bridge to push locally (no callback)."""
    users: list[dict] = []

    member_qs = MemberProfile.objects.filter(biometric_templates__isnull=False).distinct()
    if member_ids is not None:
        member_qs = member_qs.filter(member_id__in=member_ids)
    for profile in member_qs.select_related("user").prefetch_related("biometric_templates"):
        templates = {
            str(row.finger_index): base64.b64encode(
                crypto.decrypt_bytes(row.template_ciphertext)
            ).decode()
            for row in profile.biometric_templates.all()
        }
        if not templates:
            continue
        pin = ""
        if profile.device_pin_enc:
            pin = crypto.decrypt_bytes(profile.device_pin_enc).decode()
        users.append(
            {
                "kind": "member",
                "user_id": profile.member_id,
                "name": (profile.user.full_name or profile.member_id).strip()
                or profile.member_id,
                "pin": pin,
                "privilege": bridge.ZK_PRIVILEGE_DEFAULT,
                "templates": templates,
            }
        )

    if include_staff:
        staff_qs = (
            StaffProfile.objects.filter(biometric_templates__isnull=False)
            .select_related("user")
            .prefetch_related("biometric_templates")
            .distinct()
        )
        for staff in staff_qs:
            templates = {
                str(row.finger_index): base64.b64encode(
                    crypto.decrypt_bytes(row.template_ciphertext)
                ).decode()
                for row in staff.biometric_templates.all()
            }
            if not templates:
                continue
            users.append(
                {
                    "kind": "staff",
                    "user_id": staff.short_id,
                    "name": (staff.user.full_name or staff.short_id).strip()
                    or staff.short_id,
                    "pin": "",
                    "privilege": _staff_privilege(staff),
                    "templates": templates,
                }
            )

    return {"count": len(users), "users": users}


def ack_vault_sync(
    *,
    bridge_device_id: str,
    member_ids: list[str] | None = None,
    staff_ids: list[str] | None = None,
    failures: list[dict] | None = None,
) -> dict:
    """Mark vault rows synced after the bridge applied templates locally."""
    if not bridge_device_id:
        raise ValidationError({"bridge_device_id": "Required."})
    device = _resolve_target_device(bridge_device_id)
    if device is None:
        raise ValidationError({"bridge_device_id": "Unknown device."})

    failure_map = {
        str(item.get("member_id") or ""): str(item.get("error") or "")
        for item in (failures or [])
        if isinstance(item, dict)
    }
    now = timezone.now()
    synced_members = 0
    synced_staff = 0

    if member_ids is not None:
        for mid in member_ids:
            profile = MemberProfile.objects.filter(member_id=mid).first()
            if not profile:
                continue
            err = failure_map.get(mid, "")
            FingerprintDeviceSyncState.objects.update_or_create(
                device=device,
                member=profile,
                defaults={
                    "templates_synced_at": None if err else now,
                    "pin_synced_at": None if err else now,
                    "last_error": err,
                },
            )
            if not err:
                synced_members += 1

    if staff_ids is not None:
        for sid in staff_ids:
            staff = StaffProfile.objects.filter(short_id=sid).first()
            if not staff:
                continue
            err = failure_map.get(sid, "")
            FingerprintDeviceStaffSyncState.objects.update_or_create(
                device=device,
                staff=staff,
                defaults={
                    "templates_synced_at": None if err else now,
                    "last_error": err,
                },
            )
            if not err:
                synced_staff += 1

    return {
        "ok": True,
        "synced_members": synced_members,
        "synced_staff": synced_staff,
    }


def get_member_for_admin(pk):
    return get_member(pk)


def _staff_finger_indexes(staff: StaffProfile) -> list[int]:
    return list(
        staff.biometric_templates.order_by("finger_index").values_list(
            "finger_index", flat=True
        )
    )


def list_staff_templates(staff: StaffProfile) -> dict:
    return {
        "finger_indexes": _staff_finger_indexes(staff),
        "fingerprint_status": staff.fingerprint_status,
    }


def enroll_staff_prepare(
    actor, staff: StaffProfile, *, device_id: str | None = None
) -> dict:
    _ = actor
    name = (staff.user.full_name or staff.short_id).strip() or staff.short_id
    bridge.ensure_user(
        user_id=staff.short_id,
        name=name,
        device_id=device_id,
        privilege=_staff_privilege(staff),
    )
    return {"prepared": True}


def enroll_staff_interactive(
    actor,
    staff: StaffProfile,
    finger_id: int,
    *,
    device_id: str | None = None,
) -> dict:
    try:
        finger_id = int(finger_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"finger_id": "Must be an integer 0–9."}) from exc
    if finger_id < 0 or finger_id > 9:
        raise ValidationError({"finger_id": "Must be between 0 and 9."})

    bridge.require_device_online(device_id=device_id)
    name = (staff.user.full_name or staff.short_id).strip() or staff.short_id
    session = bridge.enroll_session(
        user_id=staff.short_id,
        name=name,
        finger_id=finger_id,
        device_id=device_id,
        privilege=_staff_privilege(staff),
    )
    pulled = store_staff_templates(
        actor, staff, templates=session.get("templates") or {}
    )
    staff.refresh_from_db(fields=["fingerprint_status"])
    indexes = _staff_finger_indexes(staff)
    if actor is not None:
        record(
            actor,
            "staff",
            "update",
            "adminActivityStaffFingerprintUpdated",
            {
                "shortId": staff.short_id,
                "status": staff.fingerprint_status,
                "fingerId": finger_id,
            },
        )
    return {
        "enrolled": True,
        "finger_id": finger_id,
        "stored": int(pulled.get("stored") or 0),
        "fingerprint_status": staff.fingerprint_status,
        "finger_indexes": indexes,
    }


def delete_staff_template(
    actor,
    staff: StaffProfile,
    finger_id: int,
    *,
    device_id: str | None = None,
) -> dict:
    try:
        finger_id = int(finger_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"finger_id": "Must be an integer 0–9."}) from exc
    if finger_id < 0 or finger_id > 9:
        raise ValidationError({"finger_id": "Must be between 0 and 9."})

    bridge.require_device_online(device_id=device_id)
    bridge.delete_fingerprint(staff.short_id, finger_id, device_id=device_id)
    StaffBiometricTemplate.objects.filter(staff=staff, finger_index=finger_id).delete()
    indexes = _staff_finger_indexes(staff)
    if not indexes and staff.fingerprint_status not in ("not_required",):
        staff.fingerprint_status = "pending"
        staff.save(update_fields=["fingerprint_status", "updated_at"])
    if actor is not None:
        record(
            actor,
            "staff",
            "update",
            "adminActivityStaffFingerprintUpdated",
            {
                "shortId": staff.short_id,
                "status": staff.fingerprint_status,
                "fingerId": finger_id,
                "deleted": True,
            },
        )
    return {
        "finger_indexes": indexes,
        "fingerprint_status": staff.fingerprint_status,
    }


def store_staff_templates(actor, staff: StaffProfile, *, templates: dict) -> dict:
    _ = actor
    stored = 0
    for index_str, b64 in (templates or {}).items():
        if not isinstance(b64, str) or not b64:
            continue
        finger_index = int(index_str)
        data = base64.b64decode(b64)
        StaffBiometricTemplate.objects.update_or_create(
            staff=staff,
            finger_index=finger_index,
            defaults={
                "template_ciphertext": crypto.encrypt_bytes(data),
                "template_sha256": crypto.sha256_hex(data),
                "algorithm": "zk",
                "template_format": "zk",
            },
        )
        stored += 1
    if stored and staff.fingerprint_status != "ready":
        staff.fingerprint_status = "ready"
        staff.save(update_fields=["fingerprint_status", "updated_at"])
    return {"stored": stored, "fingerprint_status": staff.fingerprint_status}


def pull_staff_templates(
    actor, staff: StaffProfile, *, device_id: str | None = None
) -> dict:
    raw = bridge.get_templates(staff.short_id, device_id=device_id)
    return store_staff_templates(actor, staff, templates=raw.get("templates") or {})


def push_staff_vault_to_device(
    actor, staff: StaffProfile, *, bridge_device_id: str | None = None
) -> dict:
    _ = actor
    name = (staff.user.full_name or staff.short_id).strip() or staff.short_id
    templates = {
        str(row.finger_index): base64.b64encode(
            crypto.decrypt_bytes(row.template_ciphertext)
        ).decode()
        for row in staff.biometric_templates.all()
    }
    device = _resolve_target_device(bridge_device_id)
    device_id = (device.bridge_device_id if device else "") or bridge_device_id
    bridge.push_user(
        user_id=staff.short_id,
        name=name,
        templates=templates,
        device_id=device_id or None,
        privilege=_staff_privilege(staff),
    )
    if device:
        FingerprintDeviceStaffSyncState.objects.update_or_create(
            device=device,
            staff=staff,
            defaults={
                "templates_synced_at": timezone.now(),
                "last_error": "",
            },
        )
    return {"pushed": True, "template_count": len(templates)}


def list_device_controllers() -> dict:
    qs = (
        StaffProfile.objects.filter(device_admin=True)
        .select_related("user")
        .order_by("short_id")
    )
    controllers = [
        {
            "id": str(row.user_id),
            "short_id": row.short_id,
            "name": (row.user.full_name or row.short_id).strip(),
            "is_active": row.user.is_active,
            "fingerprint_status": row.fingerprint_status,
            "device_admin": True,
        }
        for row in qs
    ]
    return {"count": len(controllers), "controllers": controllers}


def add_device_controller(actor, staff_user: User) -> dict:
    staff = staff_profile_for_user(staff_user)
    if not staff_user.is_active:
        raise PermissionDenied("Inactive staff cannot control the device.")
    bridge.require_device_online()
    if not staff.device_admin:
        staff.device_admin = True
        staff.save(update_fields=["device_admin", "updated_at"])
    name = (staff_user.full_name or staff.short_id).strip() or staff.short_id
    # Ensure device user exists with USER_ADMIN even before fingerprints are ready.
    bridge.ensure_user(
        user_id=staff.short_id,
        name=name,
        privilege=bridge.ZK_PRIVILEGE_ADMIN,
    )
    if actor is not None:
        record(
            actor,
            "staff",
            "update",
            "adminActivityDeviceControllerAdded",
            {"shortId": staff.short_id, "name": name},
        )
    return {
        "id": str(staff_user.pk),
        "short_id": staff.short_id,
        "name": name,
        "is_active": staff_user.is_active,
        "fingerprint_status": staff.fingerprint_status,
        "device_admin": True,
    }


def remove_device_controller(actor, staff_user: User) -> dict:
    staff = staff_profile_for_user(staff_user)
    if staff.device_admin:
        staff.device_admin = False
        staff.save(update_fields=["device_admin", "updated_at"])
    name = (staff_user.full_name or staff.short_id).strip() or staff.short_id
    try:
        bridge.ensure_user(
            user_id=staff.short_id,
            name=name,
            privilege=bridge.ZK_PRIVILEGE_DEFAULT,
        )
    except bridge.BridgeUnavailable:
        # Flag cleared in vault even if bridge is offline; next push will demote.
        log.warning("device controller demote bridge offline short_id=%s", staff.short_id)
    if actor is not None:
        record(
            actor,
            "staff",
            "update",
            "adminActivityDeviceControllerRemoved",
            {"shortId": staff.short_id, "name": name},
        )
    return {"removed": True, "short_id": staff.short_id}


def device_controller_input_staff(staff_id) -> User:
    return get_object_or_404(User, pk=staff_id, role="admin")


def _open_bridge_job(*, kind: str, user_id: str):
    """Return a pending/claimed job for this user_id, if any."""
    from biometrics.models import BridgeDeviceJob

    return (
        BridgeDeviceJob.objects.filter(
            kind=kind,
            status__in=(
                BridgeDeviceJob.STATUS_PENDING,
                BridgeDeviceJob.STATUS_CLAIMED,
            ),
            payload__user_id=user_id,
        )
        .order_by("-created_at")
        .first()
    )


def revoke_member_device_access(
    member: MemberProfile,
    *,
    wait: bool = False,
    idempotency_key: str = "",
) -> dict:
    """Remove the member from the scanner; vault templates are kept."""
    from biometrics.models import BridgeDeviceJob

    user_id = (member.member_id or "").strip()
    if not user_id:
        return {"revoked": False, "reason": "missing_member_id"}

    if not wait:
        open_job = _open_bridge_job(
            kind=BridgeDeviceJob.KIND_REVOKE_ACCESS, user_id=user_id
        )
        if open_job is not None:
            FingerprintDeviceSyncState.objects.filter(member=member).update(
                templates_synced_at=None,
                pin_synced_at=None,
                last_error="",
            )
            return {
                "revoked": True,
                "queued": True,
                "already_pending": True,
                "job_id": str(open_job.id),
            }

    try:
        result = bridge.revoke_access(
            user_id,
            wait=wait,
            idempotency_key=idempotency_key
            or f"revoke:{user_id}:{timezone.localdate().isoformat()}",
        )
    except bridge.BridgeUnavailable as exc:
        log.warning(
            "revoke_access bridge unavailable member=%s err=%s",
            user_id,
            exc,
        )
        return {"revoked": False, "reason": "bridge_unavailable", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        log.warning("revoke_access failed member=%s err=%s", user_id, exc)
        return {"revoked": False, "error": str(exc)}

    # Clear sync timestamps so reconcile knows device no longer has templates.
    FingerprintDeviceSyncState.objects.filter(member=member).update(
        templates_synced_at=None,
        pin_synced_at=None,
        last_error="",
    )
    if wait:
        return {"revoked": True, "result": result if isinstance(result, dict) else {}}
    job_id = getattr(result, "id", None)
    return {"revoked": True, "queued": True, "job_id": str(job_id) if job_id else ""}


def restore_member_device_access(
    member: MemberProfile,
    *,
    wait: bool = False,
) -> dict:
    """Re-push vault templates to the scanner after renew/activate."""
    member.refresh_from_db()
    if not member.biometric_templates.exists():
        return {"restored": False, "reason": "no_vault"}
    if member.membership_status != "active":
        return {"restored": False, "reason": "not_active"}

    name = (member.user.full_name or member.member_id).strip() or member.member_id
    pin = ""
    if member.device_pin_enc:
        pin = crypto.decrypt_bytes(member.device_pin_enc).decode()
    templates = {
        str(row.finger_index): base64.b64encode(
            crypto.decrypt_bytes(row.template_ciphertext)
        ).decode()
        for row in member.biometric_templates.all()
    }
    device = _resolve_target_device(None)
    device_id = device.bridge_device_id if device else None

    payload = {
        "user_id": member.member_id,
        "name": name,
        "pin": pin,
        "uid": 0,
        "templates": templates,
    }
    if device_id:
        payload["device_id"] = str(device_id)

    try:
        if wait:
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
            return {"restored": True, "template_count": len(templates)}

        from biometrics import jobs
        from biometrics.models import BridgeDeviceJob

        job = jobs.enqueue(
            BridgeDeviceJob.KIND_PUSH_USER,
            payload,
            bridge_device_id=device_id,
            timeout=70.0,
            idempotency_key=f"restore:{member.member_id}:{timezone.localdate().isoformat()}",
        )
        return {
            "restored": True,
            "queued": True,
            "job_id": str(job.id),
            "template_count": len(templates),
        }
    except bridge.BridgeUnavailable as exc:
        log.warning(
            "restore_access bridge unavailable member=%s err=%s",
            member.member_id,
            exc,
        )
        return {"restored": False, "reason": "bridge_unavailable", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        log.warning("restore_access failed member=%s err=%s", member.member_id, exc)
        return {"restored": False, "error": str(exc)}


def reconcile_device_access(*, today=None) -> dict:
    """Ensure expired members are revoked and active+ready members are restored.

    Safe to run daily alongside membership expiry notifications. Also flips
    past-due ``active`` rows (``expires_on < today``) so device sync cannot lag
    the calendar.
    """
    from biometrics.models import BridgeDeviceJob

    today = today or timezone.localdate()
    revoked = 0
    restored = 0
    skipped = 0
    flipped = 0
    errors: list[dict] = []

    # Catch-up flip before revoke loop (same rule as notify_membership_expiry_batch).
    past_due = (
        MemberProfile.objects.filter(
            membership_status="active",
            expires_on__lt=today,
        )
        .exclude(expires_on__isnull=True)
        .select_related("user")
    )
    for profile in past_due:
        profile.membership_status = "expired"
        profile.save(update_fields=["membership_status", "updated_at"])
        flipped += 1

    # Revoke anyone expired who might still be on the panel (vault and/or ready).
    expired_qs = (
        MemberProfile.objects.filter(membership_status="expired")
        .filter(Q(biometric_templates__isnull=False) | Q(fingerprint_status="ready"))
        .distinct()
        .select_related("user")
    )
    for profile in expired_qs:
        try:
            out = revoke_member_device_access(
                profile,
                wait=False,
                idempotency_key=(
                    f"reconcile-revoke:{profile.member_id}:{today.isoformat()}"
                ),
            )
            if out.get("revoked"):
                revoked += 1
            else:
                skipped += 1
                if out.get("error") or out.get("reason") == "bridge_unavailable":
                    errors.append({"member_id": profile.member_id, **out})
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "reconcile revoke failed member=%s err=%s", profile.member_id, exc
            )
            errors.append({"member_id": profile.member_id, "error": str(exc)})

    active_ready = (
        MemberProfile.objects.filter(
            membership_status="active",
            fingerprint_status="ready",
        )
        .filter(biometric_templates__isnull=False)
        .distinct()
        .select_related("user")
        .prefetch_related("device_sync_states", "biometric_templates")
    )
    for profile in active_ready:
        synced = any(
            state.templates_synced_at is not None
            for state in profile.device_sync_states.all()
        )
        if synced:
            skipped += 1
            continue
        open_push = _open_bridge_job(
            kind=BridgeDeviceJob.KIND_PUSH_USER, user_id=profile.member_id
        )
        if open_push is not None:
            skipped += 1
            continue
        try:
            out = restore_member_device_access(profile, wait=False)
            if out.get("restored"):
                restored += 1
            else:
                skipped += 1
                if out.get("error") or out.get("reason") == "bridge_unavailable":
                    errors.append({"member_id": profile.member_id, **out})
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "reconcile restore failed member=%s err=%s", profile.member_id, exc
            )
            errors.append({"member_id": profile.member_id, "error": str(exc)})

    return {
        "flipped": flipped,
        "revoked": revoked,
        "restored": restored,
        "skipped": skipped,
        "errors": errors,
    }
