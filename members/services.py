import secrets
from datetime import UTC, timedelta
from urllib.parse import urljoin

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError

from accounts import providers
from accounts.crypto import normalize_phone
from accounts.models import User
from accounts.services import (
    bind_google,
    check_proof,
    consume_challenge,
    ensure_new_phone,
    lock_key,
    member_data,
)
from core.api import BadGateway, Conflict, require_admin
from core.images import read_image
from members.models import MemberProfile
from operations.services import DHAKA, gym_status, record


def owned_profile(user):
    if not user or user.role != "member" or not user.is_active:
        raise PermissionDenied()
    return MemberProfile.objects.select_related("user", "plan").get(user=user)


def get_member(member_id):
    return get_object_or_404(
        MemberProfile.objects.select_related("user", "plan"), user_id=member_id
    )


def profile_data(user):
    p = owned_profile(user)
    fp = getattr(user, "fitness_profile", None)
    return {
        **member_data(user),
        "emergency_name": p.emergency_name,
        "emergency_relationship": p.emergency_relationship,
        "emergency_phone_e164": p.emergency_phone_e164,
        "blood_group": p.blood_group,
        "height_cm": p.height_cm if p.height_cm is not None else (fp.height_cm if fp else None),
        "weight_kg": p.weight_kg if p.weight_kg is not None else (fp.weight_kg if fp else None),
        "age": p.age if p.age is not None else (fp.age if fp else None),
        "sex": p.sex or (fp.sex if fp else ""),
        "photo_url": urljoin(settings.PUBLIC_BASE_URL + "/", p.photo.url) if p.photo else None,
    }


def plan_brief(profile):
    return (
        {
            "id": str(profile.plan_id),
            "catalog_id": profile.plan.catalog_id,
            "name": profile.plan.name,
        }
        if profile.plan_id and profile.membership_status in {"active", "expired"}
        else None
    )


def admin_member_data(p):
    last = p.payments.filter(status="paid").order_by("-paid_at").first()
    return {
        **profile_data(p.user),
        "fingerprint_status": p.fingerprint_status,
        "plan": plan_brief(p),
        "expires_on": p.expires_on if p.membership_status in {"active", "expired"} else None,
        "last_paid_at": last.paid_at if last else None,
    }


@transaction.atomic
def save_profile(user, data, complete=False):
    owned_profile(user)
    user = User.objects.select_for_update().get(pk=user.pk)
    p = MemberProfile.objects.select_for_update().get(user=user)
    if complete and p.profile_complete:
        raise Conflict("Your profile is already complete.")
    if not complete and not p.profile_complete:
        raise ValidationError({"profile": "Complete your profile first."})
    if data["emergency_phone_e164"] == user.phone_e164:
        raise ValidationError(
            {"emergency_phone_e164": "Emergency phone cannot match your phone number."}
        )
    user.full_name = data["full_name"]
    user.save(update_fields=["full_name"])
    old_weight = p.weight_kg
    for key, value in data.items():
        if key != "full_name":
            setattr(p, key, value)
    p.profile_complete = True
    p.save()

    # Sync body data with FitnessProfile and auto-recalculate suggested targets (Suggestions 6 & 9)
    from fitness.models import AnthropometryLog, FitnessProfile
    from fitness.services import apply_suggested_targets_to_profile

    fp, _ = FitnessProfile.objects.get_or_create(user=user)
    body_changed = False
    for attr in ("height_cm", "weight_kg", "age", "sex"):
        val = getattr(p, attr, None)
        if val is not None and val != "" and getattr(fp, attr, None) != val:
            setattr(fp, attr, val)
            body_changed = True
    if body_changed:
        if not fp.has_custom_targets or (p.weight_kg is not None and p.weight_kg != old_weight):
            apply_suggested_targets_to_profile(user, fp, save=False)
        fp.save()
    if p.weight_kg is not None and p.weight_kg != old_weight:
        AnthropometryLog.objects.create(
            user=user,
            weight=p.weight_kg,
            weight_unit="kg",
            logged_at=timezone.now(),
        )
    return profile_data(user)


@transaction.atomic
def change_phone(user, proof):
    owned_profile(user)
    user = User.objects.select_for_update().get(pk=user.pk)
    claims = check_proof(user, proof, "changePhone")
    phone = normalize_phone(claims.get("phone_e164", ""))
    lock_key("phone:" + phone)
    ensure_new_phone(user, phone)
    user.phone_e164 = phone
    user.save(update_fields=["phone_e164"])
    return profile_data(user)


def link_google(user, raw):
    owned_profile(user)
    identity = providers.verify_google(raw)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        lock_key("google:" + identity["uid"])
        return bind_google(user, identity)


def admin_link_phone(actor, profile, data):
    require_admin(actor)
    otp = consume_challenge(
        data["otp_session_id"], data["code"], ["adminLinkMemberPhone"], actor, profile.user
    )
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=profile.user_id)
        lock_key("phone:" + otp.phone_e164)
        ensure_new_phone(user, otp.phone_e164)
        previous = user.phone_e164
        user.phone_e164 = otp.phone_e164
        user.save(update_fields=["phone_e164"])
        record(
            actor,
            "member",
            "update",
            "adminActivityMemberPhoneLinked",
            {"memberId": profile.member_id, "fromPhone": previous, "toPhone": user.phone_e164},
        )
        return admin_member_data(get_member(user.pk))


@transaction.atomic
def set_fingerprint(actor, profile, status):
    require_admin(actor)
    profile = MemberProfile.objects.select_for_update().get(pk=profile.pk)
    profile.fingerprint_status = status
    profile.save()
    record(
        actor,
        "member",
        "update",
        "adminActivityMemberFingerprintUpdated",
        {"memberId": profile.member_id, "status": status},
    )
    return admin_member_data(get_member(profile.user_id))


def recover_email(user):
    owned_profile(user)
    with transaction.atomic():
        p = MemberProfile.objects.select_for_update().get(user=user)
        if not user.firebase_uid or not user.email:
            raise PermissionDenied("Link your Google account to use email recovery.")
        now = timezone.now()
        if p.recovery_sent_at and now < p.recovery_sent_at + timedelta(minutes=1):
            raise Throttled(wait=60)
        p.recovery_sent_at = now
        p.save()
    if not settings.EMAIL_DEV_BYPASS:
        raise BadGateway("We couldn't send the email. Try again.")
    return {"sent": True, "dev_bypass": True}


def upload_photo(user, file):
    owned_profile(user)
    raw, extension = read_image(file, "photo")
    p = MemberProfile.objects.get(user=user)
    new_name = p.photo.storage.save(secrets.token_hex(16) + "." + extension, ContentFile(raw))
    try:
        with transaction.atomic():
            p = MemberProfile.objects.select_for_update().get(user=user)
            old_name = p.photo.name
            p.photo.name = new_name
            p.save(update_fields=["photo"])
            if old_name:
                transaction.on_commit(lambda: p.photo.storage.delete(old_name), robust=True)
    except Exception:
        p.photo.storage.delete(new_name)
        raise
    return profile_data(User.objects.get(pk=user.pk))


@transaction.atomic
def delete_photo(user):
    owned_profile(user)
    p = MemberProfile.objects.select_for_update().get(user=user)
    old = p.photo.name
    p.photo = ""
    p.save(update_fields=["photo"])
    if old:
        transaction.on_commit(lambda: p.photo.storage.delete(old), robust=True)


def dashboard(user):
    from payments.serializers import PaymentSerializer

    p = owned_profile(user)
    now = timezone.now()
    status = gym_status(now)
    last = p.check_ins.order_by("-checked_in_at").first()
    local = now.astimezone(DHAKA)
    include = p.membership_status in {"active", "expired"}
    result = {
        "member_id": p.member_id,
        "full_name": user.full_name,
        "plan": plan_brief(p),
        "status": p.membership_status,
        "expires_on": p.expires_on if include else None,
        "days_left": min(9999, max(0, (p.expires_on - now.astimezone(UTC).date()).days))
        if include and p.expires_on
        else None,
        "visits_this_month": p.check_ins.filter(
            check_in_date__year=local.year, check_in_date__month=local.month
        ).count(),
        "last_check_in_at": last.checked_in_at if last else None,
        "fingerprint_status": p.fingerprint_status,
        "payment_preview": PaymentSerializer(
            p.payments.order_by("-created_at")[:5], many=True
        ).data,
        "has_unread_notifications": False,
    }
    result.update({k: v for k, v in status.items() if k not in {"status", "today_weekday"}})
    result["gym_status"] = status["status"]
    return result
