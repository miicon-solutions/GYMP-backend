from __future__ import annotations

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.api import require_admin, require_staff_permission
from notifications.models import MemberDeviceToken, MemberNotification, StaffAnnouncement
from notifications.serializers import announcement_payload

logger = logging.getLogger(__name__)

# code → (kind, title_key, body_key, default_push, default_sms)
CATALOG = {
    "payment_received": (
        "payment",
        "notifPaymentReceivedTitle",
        "notifPaymentReceivedBody",
        True,
        True,
    ),
    "cash_request_rejected": (
        "payment",
        "notifCashRejectedTitle",
        "notifCashRejectedBody",
        True,
        True,
    ),
    "membership_activated": (
        "membership",
        "notifMembershipActiveTitle",
        "notifMembershipActiveBody",
        False,
        False,
    ),
    "fingerprint_ready": (
        "membership",
        "notifFingerprintReadyTitle",
        "notifFingerprintReadyBody",
        True,
        False,
    ),
    "membership_expiring": (
        "membership",
        "notifRenewReminderTitle",
        "notifRenewReminderBody",
        True,
        True,
    ),
    "membership_expired": (
        "membership",
        "notifMembershipExpiredTitle",
        "notifMembershipExpiredBody",
        True,
        True,
    ),
    "announcement": ("general", "", "", True, False),
}

# English plain-text SMS bodies (always EN; no member locale on API).
SMS_TEMPLATES = {
    "payment_received": "Pure Fitness: We received your payment of ৳{amount}. Thank you!",
    "payment_received_fallback": "Pure Fitness: We received your membership payment. Thank you!",
    "cash_request_rejected": (
        "Pure Fitness: Your cash payment request was not approved. "
        "Please visit reception for help."
    ),
    "membership_expiring": (
        "Pure Fitness: Your plan expires in {days} days. Renew anytime to stay active."
    ),
    "membership_expiring_fallback": (
        "Pure Fitness: Your plan is ending soon. Renew anytime to stay active."
    ),
    "membership_expired": (
        "Pure Fitness: Your plan expired on {expiresOn}. Renew to keep training."
    ),
    "membership_expired_fallback": (
        "Pure Fitness: Your membership has expired. Renew to keep training."
    ),
}

# Bangla FCM title/body (parity with mobile app_bn.arb). Tray text cannot use ARB keys.
# code → (title, body) or body variants with _fallback suffix where params are optional.
PUSH_TEMPLATES = {
    "payment_received": (
        "পেমেন্ট গৃহীত",
        "মেম্বারশিপ পেমেন্ট হিসেবে ৳{amount} গৃহীত হয়েছে।",
    ),
    "payment_received_fallback": (
        "পেমেন্ট গৃহীত",
        "আপনার মেম্বারশিপ পেমেন্ট গৃহীত হয়েছে।",
    ),
    "cash_request_rejected": (
        "নগদ পেমেন্ট প্রত্যাখ্যান",
        "রিসেপশন আপনার নগদ পেমেন্ট নিশ্চিত করতে পারেনি। মেম্বারশিপ থেকে আবার চেষ্টা করুন।",
    ),
    "membership_activated": (
        "মেম্বারশিপ সক্রিয়",
        "আপনার মেম্বারশিপ সক্রিয়। ওয়ার্কআউট উপভোগ করুন।",
    ),
    "fingerprint_ready": (
        "ফিঙ্গারপ্রিন্ট প্রস্তুত",
        "স্টাফ আপনার ফিঙ্গারপ্রিন্ট নিশ্চিত করেছে। আপনি Pure Fitness-এ চেক ইন করতে পারেন।",
    ),
    "membership_expiring": (
        "নবায়নের অনুস্মারক",
        "আপনার প্ল্যানের মেয়াদ {days} দিনের মধ্যে শেষ। সক্রিয় থাকতে যেকোনো সময় নবায়ন করুন।",
    ),
    "membership_expiring_fallback": (
        "নবায়নের অনুস্মারক",
        "আপনার প্ল্যানের মেয়াদ শীঘ্রই শেষ। সক্রিয় থাকতে যেকোনো সময় নবায়ন করুন।",
    ),
    "membership_expired": (
        "মেম্বারশিপের মেয়াদ শেষ",
        "আপনার প্ল্যানের মেয়াদ {expiresOn}-এ শেষ হয়েছে। চালিয়ে যেতে নবায়ন করুন।",
    ),
    "membership_expired_fallback": (
        "মেম্বারশিপের মেয়াদ শেষ",
        "আপনার মেম্বারশিপের মেয়াদ শেষ। চালিয়ে যেতে নবায়ন করুন।",
    ),
}


def has_unread(user) -> bool:
    return MemberNotification.objects.filter(user=user, is_unread=True).exists()


def list_for_member(user):
    return list(MemberNotification.objects.filter(user=user)[:100])


def mark_read(user, notification_id):
    notif = get_object_or_404(MemberNotification, pk=notification_id, user=user)
    if notif.is_unread:
        notif.is_unread = False
        notif.save(update_fields=["is_unread", "updated_at"])
    return notif


def mark_all_read(user) -> dict:
    updated = MemberNotification.objects.filter(user=user, is_unread=True).update(
        is_unread=False
    )
    return {"updated": updated}


def create_notification(
    user,
    *,
    code: str,
    kind: str | None = None,
    title_key: str = "",
    body_key: str = "",
    title_params: dict | None = None,
    body_params: dict | None = None,
    title: str = "",
    body: str = "",
    related_object_id: str = "",
    dedupe_key: str = "",
    push: bool | None = None,
    sms: bool | None = None,
) -> MemberNotification | None:
    """Insert an in-app notification; optionally queue FCM/SMS after commit.

    Returns None when a dedupe unique constraint rejects a duplicate.
    """
    catalog = CATALOG.get(code)
    if catalog:
        cat_kind, cat_title_key, cat_body_key, cat_push, cat_sms = catalog
        kind = kind or cat_kind
        title_key = title_key or cat_title_key
        body_key = body_key or cat_body_key
        if push is None:
            push = cat_push
        if sms is None:
            sms = cat_sms
    elif kind is None:
        raise ValidationError({"code": f"Unknown notification code: {code}"})
    if push is None:
        push = False
    if sms is None:
        sms = False

    try:
        with transaction.atomic():
            notif = MemberNotification.objects.create(
                user=user,
                kind=kind,
                code=code,
                title_key=title_key,
                body_key=body_key,
                title_params=title_params or {},
                body_params=body_params or {},
                title=title,
                body=body,
                related_object_id=related_object_id or "",
                dedupe_key=dedupe_key or "",
                send_push=bool(push),
                send_sms=bool(sms),
            )
    except IntegrityError:
        return None

    notif_id = notif.pk
    if push and _user_push_enabled(user):
        transaction.on_commit(lambda: send_fcm_for_notification(notif_id), robust=True)
    if sms and _user_sms_enabled(user):
        transaction.on_commit(lambda: send_sms_for_notification(notif_id), robust=True)
    return notif


def _member_profile_flag(user, field: str, default: bool = True) -> bool:
    profile = getattr(user, "member_profile", None)
    if profile is None:
        try:
            from members.models import MemberProfile

            profile = MemberProfile.objects.filter(user=user).only(field).first()
        except Exception:
            return default
    if profile is None:
        return default
    return bool(getattr(profile, field, default))


def _user_push_enabled(user) -> bool:
    return _member_profile_flag(user, "push_enabled", True)


def _user_sms_enabled(user) -> bool:
    return _member_profile_flag(user, "sms_enabled", True)


def format_sms(notif: MemberNotification) -> str:
    """Render plain-text SMS for a notification (English system templates)."""
    params = dict(notif.body_params or {})
    code = notif.code
    if code == "announcement":
        title = (notif.title or "").strip()
        body = (notif.body or "").strip()
        if title and body:
            return f"{title}: {body}"
        return body or title or "Pure Fitness"
    if code == "payment_received":
        amount = params.get("amount")
        if amount is not None and amount != "":
            return SMS_TEMPLATES["payment_received"].format(amount=amount)
        return SMS_TEMPLATES["payment_received_fallback"]
    if code == "cash_request_rejected":
        return SMS_TEMPLATES["cash_request_rejected"]
    if code == "membership_expiring":
        days = params.get("days")
        if days is not None and days != "":
            return SMS_TEMPLATES["membership_expiring"].format(days=days)
        return SMS_TEMPLATES["membership_expiring_fallback"]
    if code == "membership_expired":
        expires_on = params.get("expiresOn")
        if expires_on:
            return SMS_TEMPLATES["membership_expired"].format(expiresOn=expires_on)
        return SMS_TEMPLATES["membership_expired_fallback"]
    # Fallback for unexpected codes with free text
    title = (notif.title or "").strip()
    body = (notif.body or "").strip()
    if title and body:
        return f"{title}: {body}"
    return body or title or "Pure Fitness"


def format_push(notif: MemberNotification) -> tuple[str, str]:
    """Resolve human-readable FCM title/body. Never return ARB keys."""
    free_title = (notif.title or "").strip()
    free_body = (notif.body or "").strip()
    if free_title or free_body:
        return free_title or "Pure Fitness", free_body

    params = dict(notif.body_params or {})
    code = notif.code
    if code == "payment_received":
        amount = params.get("amount")
        if amount is not None and amount != "":
            title, body = PUSH_TEMPLATES["payment_received"]
            return title, body.format(amount=amount)
        return PUSH_TEMPLATES["payment_received_fallback"]
    if code == "cash_request_rejected":
        return PUSH_TEMPLATES["cash_request_rejected"]
    if code == "membership_activated":
        return PUSH_TEMPLATES["membership_activated"]
    if code == "fingerprint_ready":
        return PUSH_TEMPLATES["fingerprint_ready"]
    if code == "membership_expiring":
        days = params.get("days")
        if days is not None and days != "":
            title, body = PUSH_TEMPLATES["membership_expiring"]
            return title, body.format(days=days)
        return PUSH_TEMPLATES["membership_expiring_fallback"]
    if code == "membership_expired":
        expires_on = params.get("expiresOn")
        if expires_on:
            title, body = PUSH_TEMPLATES["membership_expired"]
            return title, body.format(expiresOn=expires_on)
        return PUSH_TEMPLATES["membership_expired_fallback"]
    return "Pure Fitness", ""


def notify_payment_received(user, payment) -> None:
    create_notification(
        user,
        code="payment_received",
        body_params={"amount": payment.amount_taka},
        related_object_id=str(payment.pk),
    )
    if payment.is_first_payment:
        create_notification(
            user,
            code="membership_activated",
            related_object_id=str(payment.pk),
        )


def notify_cash_rejected(user, request_id) -> None:
    create_notification(
        user,
        code="cash_request_rejected",
        related_object_id=str(request_id),
    )


def notify_staff_cash_request(request_id) -> dict:
    """Push FCM to active staff when a member submits a cash payment request."""
    from accounts.models import User
    from payments.models import CashPaymentRequest

    try:
        req = CashPaymentRequest.objects.select_related("member__user", "plan").get(
            pk=request_id
        )
    except CashPaymentRequest.DoesNotExist:
        return {"sent": 0, "failed": 0, "skipped": "missing"}

    member = req.member
    user = member.user
    name = (user.full_name or "").strip() or member.member_id or "Member"
    title = "Cash payment request"
    body = f"{name} · ৳{req.amount_taka} · awaiting reception"
    data = {
        "type": "cash_request",
        "cash_request_id": str(req.pk),
        "member_id": str(member.user_id),
        "amount_taka": str(req.amount_taka),
    }
    staff_ids = User.objects.filter(role="admin", is_active=True).values_list(
        "pk", flat=True
    )
    tokens = list(
        MemberDeviceToken.objects.filter(user_id__in=staff_ids).values_list(
            "token", flat=True
        )
    )
    if not tokens:
        logger.info("Staff cash-request push skipped: no staff device tokens")
        return {"sent": 0, "failed": 0, "skipped": "no_device"}

    sent = 0
    failed = 0
    invalid: list[str] = []
    for token in tokens:
        try:
            _send_fcm(token, title=title, body=body, data=data)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("Staff FCM send failed for token …%s: %s", token[-8:], exc)
            if _is_invalid_token(exc):
                invalid.append(token)
    if invalid:
        MemberDeviceToken.objects.filter(token__in=invalid).delete()
    return {"sent": sent, "failed": failed, "skipped": None}


def notify_fingerprint_ready(user, *, related_object_id: str = "") -> None:
    create_notification(
        user,
        code="fingerprint_ready",
        related_object_id=related_object_id or "ready",
    )


def register_device(user, token: str, platform: str) -> MemberDeviceToken:
    existing = MemberDeviceToken.objects.filter(token=token).first()
    if existing:
        existing.user = user
        existing.platform = platform
        existing.save(update_fields=["user", "platform", "updated_at"])
        return existing
    return MemberDeviceToken.objects.create(user=user, token=token, platform=platform)


def unregister_device(user, token: str) -> dict:
    deleted, _ = MemberDeviceToken.objects.filter(user=user, token=token).delete()
    return {"deleted": deleted}


def unregister_all_devices(user) -> dict:
    deleted, _ = MemberDeviceToken.objects.filter(user=user).delete()
    return {"deleted": deleted}


def list_announcements():
    return StaffAnnouncement.objects.select_related(
        "created_by", "created_by__staff_profile"
    ).all()


def get_announcement(announcement_id) -> StaffAnnouncement:
    return get_object_or_404(
        StaffAnnouncement.objects.select_related("created_by", "created_by__staff_profile"),
        pk=announcement_id,
    )


def _announcement_recipients(scope: str, member_id):
    from members.models import MemberProfile

    if scope == "member":
        profile = get_object_or_404(MemberProfile, user_id=member_id)
        return [profile.user]
    return [
        p.user
        for p in MemberProfile.objects.filter(membership_status="active").select_related("user")
    ]


def _empty_push_stats() -> dict:
    return {
        "push_sent": 0,
        "push_failed": 0,
        "push_skipped_no_device": 0,
        "push_skipped_disabled": 0,
    }


def _empty_sms_stats() -> dict:
    return {
        "sms_sent": 0,
        "sms_failed": 0,
        "sms_skipped_disabled": 0,
        "sms_skipped_no_phone": 0,
    }


def _push_fanout(notification_ids: list) -> dict:
    push_sent = 0
    push_failed = 0
    push_skipped_no_device = 0
    push_skipped_disabled = 0
    for notif_id in notification_ids:
        result = send_fcm_for_notification(notif_id)
        push_sent += int(result.get("sent") or 0)
        push_failed += int(result.get("failed") or 0)
        skipped = result.get("skipped")
        if skipped == "no_device":
            push_skipped_no_device += 1
        elif skipped == "push_disabled":
            push_skipped_disabled += 1
    return {
        "push_sent": push_sent,
        "push_failed": push_failed,
        "push_skipped_no_device": push_skipped_no_device,
        "push_skipped_disabled": push_skipped_disabled,
    }


def _sms_fanout(notification_ids: list) -> dict:
    sms_sent = 0
    sms_failed = 0
    sms_skipped_disabled = 0
    sms_skipped_no_phone = 0
    for notif_id in notification_ids:
        result = send_sms_for_notification(notif_id)
        sms_sent += int(result.get("sent") or 0)
        sms_failed += int(result.get("failed") or 0)
        skipped = result.get("skipped")
        if skipped == "sms_disabled":
            sms_skipped_disabled += 1
        elif skipped == "no_phone":
            sms_skipped_no_phone += 1
    return {
        "sms_sent": sms_sent,
        "sms_failed": sms_failed,
        "sms_skipped_disabled": sms_skipped_disabled,
        "sms_skipped_no_phone": sms_skipped_no_phone,
    }


def send_announcement(actor, data: dict) -> dict:
    require_admin(actor)
    require_staff_permission(actor, "notifications.create")

    scope = data["scope"]
    send_push = bool(data.get("send_push", True))
    send_sms = bool(data.get("send_sms", False))
    title = data["title"].strip()
    body = data["body"].strip()
    member_id = data.get("member_id")
    recipients = _announcement_recipients(scope, member_id)

    with transaction.atomic():
        campaign = StaffAnnouncement.objects.create(
            title=title,
            body=body,
            scope=scope,
            member_id=member_id if scope == "member" else None,
            created_by=actor,
            send_push_requested=send_push,
            send_sms_requested=send_sms,
        )
        campaign_id = str(campaign.pk)
        fanout_ids: list = []
        for user in recipients:
            notif = create_notification(
                user,
                code="announcement",
                kind="general",
                title=title,
                body=body,
                related_object_id=campaign_id,
                push=False,
                sms=False,
            )
            if notif:
                fanout_ids.append(notif.pk)
                updates: list[str] = []
                if send_push:
                    notif.send_push = True
                    updates.append("send_push")
                if send_sms:
                    notif.send_sms = True
                    updates.append("send_sms")
                if updates:
                    updates.append("updated_at")
                    notif.save(update_fields=updates)

    push = _push_fanout(fanout_ids) if send_push and fanout_ids else _empty_push_stats()
    sms = _sms_fanout(fanout_ids) if send_sms and fanout_ids else _empty_sms_stats()
    payload = announcement_payload(campaign, recipient_count=len(fanout_ids))
    payload.update(
        {
            "created": len(fanout_ids),
            "push_requested": send_push,
            "sms_requested": send_sms,
            **push,
            **sms,
        }
    )
    return payload


def update_announcement(actor, announcement_id, data: dict) -> dict:
    require_admin(actor)
    require_staff_permission(actor, "notifications.update")
    campaign = get_announcement(announcement_id)
    fields: list[str] = []
    if "title" in data:
        campaign.title = data["title"].strip()
        fields.append("title")
    if "body" in data:
        campaign.body = data["body"].strip()
        fields.append("body")
    if not fields:
        raise ValidationError("Provide title and/or body.")
    fields.append("updated_at")
    campaign.save(update_fields=fields)

    updates = {}
    if "title" in data:
        updates["title"] = campaign.title
    if "body" in data:
        updates["body"] = campaign.body
    if updates:
        MemberNotification.objects.filter(
            code="announcement",
            related_object_id=str(campaign.pk),
        ).update(**updates)
    return announcement_payload(campaign)


def delete_announcement(actor, announcement_id) -> None:
    require_admin(actor)
    require_staff_permission(actor, "notifications.delete")
    campaign = get_announcement(announcement_id)
    MemberNotification.objects.filter(
        code="announcement",
        related_object_id=str(campaign.pk),
    ).delete()
    campaign.delete()


def resend_announcement_push(actor, announcement_id) -> dict:
    require_admin(actor)
    require_staff_permission(actor, "notifications.create")
    campaign = get_announcement(announcement_id)
    ids = list(
        MemberNotification.objects.filter(
            code="announcement",
            related_object_id=str(campaign.pk),
        ).values_list("pk", flat=True)
    )
    MemberNotification.objects.filter(pk__in=ids).update(send_push=True)
    return _push_fanout(ids)


def resend_announcement_sms(actor, announcement_id) -> dict:
    require_admin(actor)
    require_staff_permission(actor, "notifications.create")
    campaign = get_announcement(announcement_id)
    ids = list(
        MemberNotification.objects.filter(
            code="announcement",
            related_object_id=str(campaign.pk),
        ).values_list("pk", flat=True)
    )
    MemberNotification.objects.filter(pk__in=ids).update(send_sms=True)
    return _sms_fanout(ids)


def notify_membership_expiry_batch(*, today=None) -> dict:
    """Create expiring (7d, 1d) and expired notifications. Idempotent per day."""
    from members.models import MemberProfile

    today = today or timezone.localdate()
    created = {"expiring_7": 0, "expiring_1": 0, "expired": 0}

    for days, bucket in ((7, "expiring_7"), (1, "expiring_1")):
        target = today + timedelta(days=days)
        profiles = MemberProfile.objects.filter(
            membership_status="active",
            expires_on=target,
        ).select_related("user")
        for profile in profiles:
            notif = create_notification(
                profile.user,
                code="membership_expiring",
                body_params={"days": days, "expiresOn": target.isoformat()},
                dedupe_key=f"expiring:{days}:{target.isoformat()}",
            )
            if notif:
                created[bucket] += 1

    expired_day = today - timedelta(days=1)
    expired_profiles = MemberProfile.objects.filter(
        membership_status__in={"active", "expired"},
        expires_on=expired_day,
    ).select_related("user")
    for profile in expired_profiles:
        if profile.membership_status == "active":
            profile.membership_status = "expired"
            profile.save(update_fields=["membership_status", "updated_at"])
        notif = create_notification(
            profile.user,
            code="membership_expired",
            body_params={"expiresOn": expired_day.isoformat()},
            dedupe_key=f"expired:{expired_day.isoformat()}",
        )
        if notif:
            created["expired"] += 1
    return created


def send_fcm_for_notification(notification_id) -> dict:
    """Send FCM for one notification. Returns a small status dict for callers/admin."""
    try:
        notif = MemberNotification.objects.select_related("user").get(pk=notification_id)
    except MemberNotification.DoesNotExist:
        return {"sent": 0, "failed": 0, "skipped": "missing"}
    if not _user_push_enabled(notif.user):
        return {"sent": 0, "failed": 0, "skipped": "push_disabled"}
    tokens = list(
        MemberDeviceToken.objects.filter(user=notif.user).values_list("token", flat=True)
    )
    if not tokens:
        logger.warning(
            "FCM skipped notification %s for user %s: no device token",
            notification_id,
            notif.user_id,
        )
        return {"sent": 0, "failed": 0, "skipped": "no_device"}

    title, body = format_push(notif)
    data = {
        "notification_id": str(notif.pk),
        "code": notif.code,
        "kind": notif.kind,
        "title_key": notif.title_key,
        "body_key": notif.body_key,
    }
    sent = 0
    failed = 0
    errors: list[str] = []
    invalid: list[str] = []
    for token in tokens:
        try:
            _send_fcm(token, title=title, body=body, data=data)
            sent += 1
        except Exception as exc:  # noqa: BLE001 — never break callers
            failed += 1
            err_text = str(exc)
            errors.append(err_text)
            logger.warning("FCM send failed for token …%s: %s", token[-8:], exc)
            if _is_invalid_token(exc):
                invalid.append(token)
    if invalid:
        MemberDeviceToken.objects.filter(token__in=invalid).delete()
    return {
        "sent": sent,
        "failed": failed,
        "skipped": None,
        "errors": errors,
    }


def send_sms_for_notification(notification_id) -> dict:
    """Send SMS for one notification. Failures are non-fatal (do not raise)."""
    from django.conf import settings

    from accounts.providers import send_sms_message
    from core.api import BadGateway

    try:
        notif = MemberNotification.objects.select_related("user").get(pk=notification_id)
    except MemberNotification.DoesNotExist:
        return {"sent": 0, "failed": 0, "skipped": "missing"}
    if not _user_sms_enabled(notif.user):
        logger.warning(
            "SMS skipped notification %s for user %s: sms_enabled is off",
            notification_id,
            notif.user_id,
        )
        return {"sent": 0, "failed": 0, "skipped": "sms_disabled"}
    phone = (getattr(notif.user, "phone_e164", None) or "").strip()
    if not phone:
        logger.warning(
            "SMS skipped notification %s for user %s: no phone",
            notification_id,
            notif.user_id,
        )
        return {"sent": 0, "failed": 0, "skipped": "no_phone"}
    if not settings.SMS_NET_BD_API_KEY:
        logger.warning(
            "SMS skipped notification %s (%s): SMS_NET_BD_API_KEY is not configured",
            notification_id,
            notif.code,
        )
        return {
            "sent": 0,
            "failed": 1,
            "skipped": "sms_unconfigured",
            "errors": ["SMS_NET_BD_API_KEY is not configured"],
        }

    msg = format_sms(notif)
    try:
        send_sms_message(phone, msg)
        return {"sent": 1, "failed": 0, "skipped": None}
    except BadGateway as exc:
        logger.warning(
            "SMS send failed for notification %s (%s) to …%s: %s",
            notification_id,
            notif.code,
            phone[-4:],
            exc,
        )
        return {"sent": 0, "failed": 1, "skipped": None, "errors": [str(exc)]}
    except Exception as exc:  # noqa: BLE001 — never break callers
        logger.warning(
            "SMS send failed for notification %s (%s): %s",
            notification_id,
            notif.code,
            exc,
        )
        return {"sent": 0, "failed": 1, "skipped": None, "errors": [str(exc)]}


def _send_fcm(token: str, *, title: str, body: str, data: dict) -> None:
    from firebase_admin import messaging

    from accounts.providers import firebase_app

    message = messaging.Message(
        token=token,
        notification=messaging.Notification(title=title, body=body),
        data={k: str(v) for k, v in data.items()},
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id="pure_fitness_push",
                sound="default",
                priority="high",
                default_vibrate_timings=True,
            ),
        ),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(aps=messaging.Aps(sound="default")),
        ),
    )
    messaging.send(message, app=firebase_app())


def _is_invalid_token(exc: Exception) -> bool:
    """Drop only dead registration tokens — not Firebase/APNs project misconfig."""
    text = str(exc).lower()
    if "apns credential" in text or "auth error" in text or "senderid mismatch" in text:
        return False
    name = type(exc).__name__
    return name in {"UnregisteredError"} or "unregistered" in text or "not a valid fcm" in text
