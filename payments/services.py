import secrets
from datetime import UTC, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.api import BadGateway, Conflict, require_admin, require_staff_permission
from members.models import MemberProfile
from members.services import owned_profile
from operations.services import DHAKA, record
from payments import gateway
from payments.models import CashPaymentRequest, Payment, PaymentSession
from plans.models import Plan
from plans.services import active_offer, pricing

PACK_DAYS = {1: 30, 3: 90, 6: 180, 9: 270, 12: 365}
READMISSION_LAPSE_DAYS = 180


def pack_days(months):
    """Fixed day packs mapped from plan duration_months."""
    try:
        return PACK_DAYS[months]
    except KeyError as exc:
        raise ValueError(f"Unsupported plan duration_months: {months}") from exc


def add_pack_days(base, months, *, extend=False):
    """Last valid day for a pack starting on base, or extend an existing last-valid day."""
    days = pack_days(months)
    return base + timedelta(days=days if extend else days - 1)


def business_today(*, cash=False, now=None):
    now = now or timezone.now()
    return now.astimezone(DHAKA if cash else UTC).date()


def requires_admission_fee(member, *, today=None, cash=False, now=None):
    """True for never-paid members or after READMISSION_LAPSE_DAYS past payment-backed expires_on.

    Membership clocks start only when cash is confirmed or online payment settles
    (those paths write expires_on). Registration / profile-complete alone never
    starts the 180-day grace. Prefer expires_on; paid-but-null expires_on requires
    admission as a safe default — never fall back to registration date.
    """
    today = today or business_today(cash=cash, now=now)
    if not member.payments.filter(status="paid").exists():
        return True
    if not member.expires_on:
        return True
    return (today - member.expires_on).days >= READMISSION_LAPSE_DAYS


def new_expiry(member, months, kind, now=None, cash=False):
    now = now or timezone.now()
    today = business_today(cash=cash, now=now)
    if member.expires_on and member.expires_on >= today:
        if member.membership_status == "active" or (not cash and kind in {"renew", "change_plan"}):
            return add_pack_days(member.expires_on, months, extend=True)
    return add_pack_days(today, months)


def get_plan(plan_id):
    return get_object_or_404(Plan, pk=plan_id, is_active=True)


def snapshot(plan, kind, member=None, *, today=None, cash=False, now=None):
    amounts = pricing(plan)
    if member is not None:
        charge = requires_admission_fee(member, today=today, cash=cash, now=now)
    else:
        charge = kind in {"first_purchase", "first_payment"}
    first_join_kind = kind in {"first_purchase", "first_payment"}
    renewal = amounts["effective_renewal_taka"]
    standing = amounts["standing_discount_taka"]
    offer_discount = amounts["offer_discount_taka"]
    admission_list = amounts["admission_fee_taka"]
    # Waive only when admission would otherwise be charged; renewals without
    # re-admission keep full list = period.
    waived = bool(charge and amounts["admission_waived"])
    admission_charged = 0 if (not charge or waived) else admission_list
    waived_taka = admission_list if waived else 0
    total = renewal + admission_charged
    list_amount = amounts["period_coverage_taka"] + (admission_list if charge else 0)
    lines = (
        [{"label": "Admission fee", "amount_taka": admission_charged}] if admission_charged else []
    )
    lines.append(
        {
            "label": plan.name + (" period" if first_join_kind else " renewal"),
            "amount_taka": renewal,
        }
    )
    offer = active_offer(plan)
    result = {
        "amount_taka": total,
        "list_amount_taka": list_amount,
        "standing_discount_taka": standing,
        "offer_discount_taka": offer_discount,
        "admission_waived_taka": waived_taka,
        "line_items": lines,
        "duration_months": plan.duration_months,
        "catalog_id": plan.catalog_id,
        "admission_waived": waived,
        "requires_admission": charge,
    }
    if offer is not None:
        result["offer_id"] = str(offer.pk)
        result["offer_name"] = offer.name
    return result


def offer_id_from_snapshot(price, *, first_payment=False):
    """Link a paid payment to the offer recorded on its pricing snapshot."""
    del first_payment  # kept for call-site compatibility
    if not price:
        return None
    raw = price.get("offer_id")
    if not raw:
        return None
    from plans.models import Offer

    return Offer.objects.filter(pk=raw).first()


def payment_pricing_fields(price):
    """Map a pricing snapshot onto Payment discount columns."""
    return {
        "list_amount_taka": price.get("list_amount_taka"),
        "standing_discount_taka": price.get("standing_discount_taka"),
        "offer_discount_taka": price.get("offer_discount_taka"),
        "admission_waived_taka": price.get("admission_waived_taka"),
    }


def check_kind(member, kind):
    if kind == "first_purchase":
        if (
            member.membership_status == "active"
            or member.payments.filter(status="paid", is_first_payment=True).exists()
        ):
            raise Conflict("First purchase is not available.")
    elif kind in {"renew", "change_plan"}:
        if member.membership_status not in {"active", "expired"}:
            raise ValidationError({"kind": "Renewal or plan change is not available."})
    else:
        raise ValidationError({"kind": "Choose a valid payment type."})


def create_session(user, data):
    member = owned_profile(user)
    with transaction.atomic():
        member = MemberProfile.objects.select_for_update().get(pk=member.pk)
        if not member.profile_complete:
            raise ValidationError({"profile": "Complete your profile first."})
        plan = get_object_or_404(
            Plan.objects.select_for_update(), pk=data["plan_id"], is_active=True
        )
        check_kind(member, data["kind"])
        price = snapshot(plan, data["kind"], member, cash=False)
        if price["amount_taka"] < 10:
            raise ValidationError({"amount_taka": "Amount is too low for online payment."})
        PaymentSession.objects.filter(member=member, kind=data["kind"], status="pending").update(
            status="cancelled"
        )
        session = PaymentSession.objects.create(
            member=member,
            plan=plan,
            kind=data["kind"],
            tran_id="PG" + timezone.now().strftime("%y%m%d") + secrets.token_hex(8),
            amount_taka=price["amount_taka"],
            pricing_snapshot=price,
        )
    if data.get("checkout") == "sdk":
        return session
    try:
        result = gateway.initiate(session)
    except BadGateway:
        mark_failed(session.pk)
        raise
    PaymentSession.objects.filter(pk=session.pk, status="pending").update(
        gateway_url=result["GatewayPageURL"], session_key=result.get("sessionkey", "")
    )
    session.refresh_from_db()
    return session


def mark_failed(pk):
    PaymentSession.objects.filter(pk=pk).exclude(status="paid").update(status="failed")


def validate_result(session, result):
    if str(result.get("status", "")).upper() not in {"VALID", "VALIDATED"}:
        return False
    try:
        amount = Decimal(str(result.get("amount", "")))
        valid_amount = amount.is_finite() and abs(amount - session.amount_taka) < Decimal("0.01")
    except InvalidOperation:
        valid_amount = False
    if (
        not valid_amount
        or result.get("tran_id") != session.tran_id
        or str(result.get("currency") or "").upper() != "BDT"
        or str(result.get("risk_level", "")) == "1"
        or not result.get("val_id")
    ):
        raise ValidationError({"payment": "Payment validation failed."})
    return True


@transaction.atomic
def settle(session, result):
    # Always lock member before session, shared with cash/create; serializes expiry extensions.
    member = MemberProfile.objects.select_for_update().get(pk=session.member_id)
    current = PaymentSession.objects.select_for_update().get(pk=session.pk)
    if current.status == "paid":
        return current
    price = current.pricing_snapshot
    expiry = new_expiry(member, price["duration_months"], current.kind)
    now = timezone.now()
    # True first join only — re-admission after lapse must not set is_first_payment
    # (keeps first-N offer seat math separate from admission reports).
    is_first = not member.payments.filter(status="paid").exists()
    payment = Payment.objects.create(
        member=member,
        plan=current.plan,
        tran_id=current.tran_id,
        catalog_id=price["catalog_id"],
        channel="sslcommerz",
        kind=current.kind,
        is_first_payment=is_first,
        amount_taka=current.amount_taka,
        paid_at=now,
        line_items=price.get("line_items") or [],
        offer=offer_id_from_snapshot(price, first_payment=is_first),
        **payment_pricing_fields(price),
    )
    activate(member, current.plan, expiry)
    current.status, current.paid_at = "paid", now
    current.val_id, current.bank_tran_id = result["val_id"], result.get("bank_tran_id", "")
    current.save()
    _notify_payment(member, payment)
    return current


def activate(member, plan, expires):
    from accounts.identifiers import is_temporary_member_id, next_display

    # First successful online settle or cash payment replaces PFT-####.
    # Later renewals keep the PF-#### id already stored.
    if is_temporary_member_id(member.member_id):
        member.member_id = next_display("member")
    member.plan, member.expires_on, member.membership_status = plan, expires, "active"
    if member.fingerprint_status == "not_required":
        member.fingerprint_status = "pending"
    member.save()
    # Re-push vault templates so the scanner unlocks after renew.
    try:
        from biometrics.services import restore_member_device_access

        if member.fingerprint_status == "ready" or member.biometric_templates.exists():
            restore_member_device_access(member, wait=False)
    except Exception:  # noqa: BLE001 — payment must not fail if bridge is down
        import logging

        logging.getLogger(__name__).exception(
            "restore device access after activate failed member=%s",
            getattr(member, "member_id", ""),
        )


def _notify_payment(member, payment):
    from notifications.services import notify_payment_received

    notify_payment_received(member.user, payment)


def confirm_session(user, tran_id, poll=False):
    member = owned_profile(user)
    session = get_object_or_404(PaymentSession, member=member, tran_id=tran_id)
    if session.status != "pending":
        return session
    try:
        result = gateway.query(tran_id)
        state = str(result.get("status", "")).upper()
        if state in {"", "PENDING"}:
            return session
        if state in {"FAILED", "CANCELLED", "UNATTEMPTED", "EXPIRED"}:
            if result.get("tran_id") != session.tran_id:
                raise ValidationError({"payment": "Payment validation failed."})
            mark_failed(session.pk)
        elif validate_result(session, result):
            return settle(session, result)
    except BadGateway, ValidationError:
        if not poll:
            raise
    session.refresh_from_db()
    return session


def handle_ipn(data):
    session = get_object_or_404(PaymentSession, tran_id=data["tran_id"])
    if session.status == "paid":
        return {"received": True}
    state = str(data.get("status", "")).upper()
    if state in {"FAILED", "CANCELLED", "UNATTEMPTED", "EXPIRED"}:
        verified = gateway.query(session.tran_id)
        verified_state = str(verified.get("status", "")).upper()
        if verified_state in {"FAILED", "CANCELLED", "UNATTEMPTED", "EXPIRED"}:
            if verified.get("tran_id") != session.tran_id:
                raise ValidationError({"payment": "Payment validation failed."})
            mark_failed(session.pk)
        elif validate_result(session, verified):
            settle(session, verified)
        return {"received": True}
    if not data.get("val_id"):
        raise ValidationError({"val_id": "Missing validation ID."})
    result = gateway.validate(data["val_id"])
    if validate_result(session, result):
        settle(session, result)
    return {"received": True}


def cash_details(member, plan):
    if not member.profile_complete:
        raise ValidationError({"profile": "Complete your profile first."})
    paid = member.payments.filter(status="paid").exists()
    kind = (
        "first_payment" if not paid else ("renewal" if member.plan_id == plan.pk else "plan_change")
    )
    price = snapshot(plan, kind, member, cash=True)
    preview = {
        "kind": kind,
        "amount_taka": price["amount_taka"],
        "new_expires_on": new_expiry(member, plan.duration_months, kind, cash=True),
        "plan_id": str(plan.pk),
        "catalog_id": plan.catalog_id,
        "requires_admission": price.get("requires_admission", False),
    }
    return preview, price


def cash_preview(actor, member, plan_id):
    require_admin(actor)
    return cash_details(member, get_plan(plan_id))[0]


def format_taka(amount):
    raw = str(abs(amount))
    if len(raw) <= 3:
        return "৳" + raw
    leading, last = raw[:-3], raw[-3:]
    groups = []
    while leading:
        groups.insert(0, leading[-2:])
        leading = leading[:-2]
    return "৳" + ",".join(groups + [last])


def _cash_audit(actor, member, plan, payment, kind, previous_plan_name):
    params = {
        "member_id": member.member_id,
        "name": member.user.full_name,
        "amount": format_taka(payment.amount_taka),
        "plan": plan.name,
    }
    if kind == "plan_change":
        params.update(from_plan=previous_plan_name, to_plan=plan.name)
    record(
        actor,
        "member",
        "activate" if kind == "first_payment" else "update",
        {
            "first_payment": "adminActivityMemberCashActivated",
            "renewal": "adminActivityMemberCashRenewed",
            "plan_change": "adminActivityMemberCashPlanChanged",
        }[kind],
        params,
    )


def _link_pending_cash_request(member, plan, payment, actor):
    from notifications.services import mark_staff_cash_request_notifications_read

    now = timezone.now()
    pending = (
        CashPaymentRequest.objects.select_for_update()
        .filter(member=member, status="pending", plan=plan)
        .first()
    )
    if pending is None:
        prior_ids = list(
            CashPaymentRequest.objects.filter(member=member, status="pending").values_list(
                "pk", flat=True
            )
        )
        CashPaymentRequest.objects.filter(member=member, status="pending").update(
            status="cancelled", resolved_at=now
        )
        for prior_id in prior_ids:
            mark_staff_cash_request_notifications_read(prior_id)
        return None
    pending.status = "accepted"
    pending.resolved_at = now
    pending.resolved_by = actor
    pending.payment = payment
    pending.save(update_fields=["status", "resolved_at", "resolved_by", "payment", "updated_at"])
    mark_staff_cash_request_notifications_read(pending.pk)
    return pending


@transaction.atomic
def receive_cash(actor, member, plan_id):
    require_admin(actor)
    member = MemberProfile.objects.select_for_update().get(pk=member.pk)
    plan = get_object_or_404(Plan.objects.select_for_update(), pk=plan_id, is_active=True)
    preview, price = cash_details(member, plan)
    previous_plan = member.plan.name if member.plan_id else plan.name
    is_first = not member.payments.filter(status="paid").exists()
    payment = Payment.objects.create(
        member=member,
        plan=plan,
        catalog_id=plan.catalog_id,
        channel="cash",
        kind=preview["kind"],
        is_first_payment=is_first,
        amount_taka=price["amount_taka"],
        line_items=price.get("line_items") or [],
        paid_at=timezone.now(),
        offer=offer_id_from_snapshot(price, first_payment=is_first),
        **payment_pricing_fields(price),
    )
    activate(member, plan, preview["new_expires_on"])
    _cash_audit(actor, member, plan, payment, preview["kind"], previous_plan)
    _link_pending_cash_request(member, plan, payment, actor)
    _notify_payment(member, payment)
    return member, payment


@transaction.atomic
def create_cash_request(user, data):
    member = owned_profile(user)
    member = MemberProfile.objects.select_for_update().get(pk=member.pk)
    if not member.profile_complete:
        raise ValidationError({"profile": "Complete your profile first."})
    plan = get_object_or_404(Plan.objects.select_for_update(), pk=data["plan_id"], is_active=True)
    preview, price = cash_details(member, plan)
    kind = preview["kind"]
    has_paid = member.payments.filter(status="paid").exists()

    if kind == "first_payment":
        if member.membership_status == "active" or has_paid:
            raise Conflict("First purchase is not available.")
    elif kind in {"renewal", "plan_change"}:
        if not has_paid or member.membership_status not in {"active", "expired"}:
            raise Conflict("Renewal or plan change is not available.")
    else:
        raise Conflict("Cash requests are not available for this membership.")

    now = timezone.now()
    prior_pending_ids = list(
        CashPaymentRequest.objects.filter(member=member, status="pending").values_list(
            "pk", flat=True
        )
    )
    CashPaymentRequest.objects.filter(member=member, status="pending").update(
        status="cancelled", resolved_at=now
    )
    if kind == "first_payment":
        PaymentSession.objects.filter(
            member=member, kind="first_purchase", status="pending"
        ).update(status="cancelled")
    else:
        PaymentSession.objects.filter(
            member=member, kind__in=("renew", "change_plan"), status="pending"
        ).update(status="cancelled")
    req = CashPaymentRequest.objects.create(
        member=member,
        plan=plan,
        kind=kind,
        amount_taka=price["amount_taka"],
        pricing_snapshot=price,
        status="pending",
    )
    if kind == "first_payment":
        member.membership_status = "pending_payment"
        member.save(update_fields=["membership_status", "updated_at"])
    req_id = req.pk

    if prior_pending_ids:
        from notifications.services import mark_staff_cash_request_notifications_read

        for prior_id in prior_pending_ids:
            mark_staff_cash_request_notifications_read(prior_id)

    def _push_staff():
        from notifications.services import notify_staff_cash_request

        notify_staff_cash_request(req_id)

    transaction.on_commit(_push_staff, robust=True)
    return req


def get_cash_request_for_member(user, request_id):
    member = owned_profile(user)
    return get_object_or_404(CashPaymentRequest, pk=request_id, member=member)


def list_member_cash_requests(user, status=None):
    member = owned_profile(user)
    rows = CashPaymentRequest.objects.filter(member=member).select_related("plan", "payment")
    if status:
        rows = rows.filter(status=status)
    return list(rows[:20])


@transaction.atomic
def cancel_cash_request(user, request_id):
    member = owned_profile(user)
    member = MemberProfile.objects.select_for_update().get(pk=member.pk)
    req = get_object_or_404(
        CashPaymentRequest.objects.select_for_update(), pk=request_id, member=member
    )
    if req.status != "pending":
        raise Conflict("Only pending cash requests can be cancelled.")
    req.status = "cancelled"
    req.resolved_at = timezone.now()
    req.save(update_fields=["status", "resolved_at", "updated_at"])
    if (
        member.membership_status == "pending_payment"
        and not member.payments.filter(status="paid").exists()
    ):
        member.membership_status = "none"
        member.save(update_fields=["membership_status", "updated_at"])
    from notifications.services import mark_staff_cash_request_notifications_read

    mark_staff_cash_request_notifications_read(req.pk)
    return req


def list_admin_cash_requests(actor, status="pending", member_id=None):
    require_staff_permission(actor, "cash_requests.view")
    rows = CashPaymentRequest.objects.select_related(
        "member", "member__user", "plan", "payment", "resolved_by"
    )
    if status:
        rows = rows.filter(status=status)
    if member_id:
        # Same User UUID as CashPaymentRequestSerializer.member_id / admin member detail.
        rows = rows.filter(member__user_id=member_id)
    return list(rows.order_by("-requested_at", "-id")[:100])


def list_member_admin_cash_requests(actor, member):
    require_staff_permission(actor, "cash_requests.view")
    return list(
        CashPaymentRequest.objects.filter(member=member)
        .select_related("plan", "payment", "resolved_by")
        .order_by("-requested_at", "-id")[:50]
    )


@transaction.atomic
def accept_cash_request(actor, request_id):
    require_staff_permission(actor, "cash_requests.update")
    req = get_object_or_404(CashPaymentRequest.objects.select_for_update(), pk=request_id)
    if req.status == "accepted" and req.payment_id:
        return req, req.payment, req.member
    if req.status != "pending":
        raise Conflict("Only pending cash requests can be accepted.")
    member = MemberProfile.objects.select_for_update().get(pk=req.member_id)
    plan = get_object_or_404(Plan.objects.select_for_update(), pk=req.plan_id)
    price = req.pricing_snapshot or snapshot(plan, req.kind, member, cash=True)
    # Re-validate kind against current membership; prefer frozen amount.
    preview, live_price = cash_details(member, plan)
    if preview["kind"] != req.kind:
        raise Conflict("Cash request kind no longer matches this member.")
    amount = price.get("amount_taka", live_price["amount_taka"])
    lines = price.get("line_items", live_price["line_items"])
    previous_plan = member.plan.name if member.plan_id else plan.name
    expiry = preview["new_expires_on"]
    is_first = not member.payments.filter(status="paid").exists()
    payment = Payment.objects.create(
        member=member,
        plan=plan,
        catalog_id=price.get("catalog_id", plan.catalog_id),
        channel="cash",
        kind=req.kind,
        is_first_payment=is_first,
        amount_taka=amount,
        line_items=lines or [],
        paid_at=timezone.now(),
        offer=offer_id_from_snapshot(price, first_payment=is_first),
        **payment_pricing_fields(price),
    )
    activate(member, plan, expiry)
    _cash_audit(actor, member, plan, payment, req.kind, previous_plan)
    now = timezone.now()
    req.status = "accepted"
    req.resolved_at = now
    req.resolved_by = actor
    req.payment = payment
    req.save(update_fields=["status", "resolved_at", "resolved_by", "payment", "updated_at"])
    _notify_payment(member, payment)
    from notifications.services import mark_staff_cash_request_notifications_read

    mark_staff_cash_request_notifications_read(req.pk)
    return req, payment, member


@transaction.atomic
def reject_cash_request(actor, request_id):
    require_staff_permission(actor, "cash_requests.update")
    req = get_object_or_404(CashPaymentRequest.objects.select_for_update(), pk=request_id)
    if req.status == "rejected":
        return req
    if req.status != "pending":
        raise Conflict("Only pending cash requests can be rejected.")
    member = MemberProfile.objects.select_for_update().get(pk=req.member_id)
    now = timezone.now()
    req.status = "rejected"
    req.resolved_at = now
    req.resolved_by = actor
    req.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])
    if (
        member.membership_status == "pending_payment"
        and not member.payments.filter(status="paid").exists()
    ):
        member.membership_status = "none"
        member.save(update_fields=["membership_status", "updated_at"])
    from notifications.services import (
        mark_staff_cash_request_notifications_read,
        notify_cash_rejected,
    )

    notify_cash_rejected(member.user, req.pk)
    mark_staff_cash_request_notifications_read(req.pk)
    return req
