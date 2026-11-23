import calendar
from datetime import UTC, date, timedelta

from django.db.models import Count, IntegerField, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.api import require_admin
from members.models import MemberProfile
from operations.models import Cost
from payments.models import Payment
from payments.serializers import PaymentSerializer


def _discount_aggregates(paid):
    """Collected vs list/discount totals; null list columns fall back to amount (discount 0)."""
    totals = paid.aggregate(
        total=Sum("amount_taka"),
        count=Count("id"),
        list_total=Sum(Coalesce("list_amount_taka", "amount_taka", output_field=IntegerField())),
        standing=Sum(Coalesce("standing_discount_taka", Value(0))),
        offer=Sum(Coalesce("offer_discount_taka", Value(0))),
        admission=Sum(Coalesce("admission_waived_taka", Value(0))),
    )
    total = totals["total"] or 0
    list_taka = totals["list_total"] or 0
    standing = totals["standing"] or 0
    offer = totals["offer"] or 0
    admission = totals["admission"] or 0
    discount = standing + offer + admission
    if discount == 0 and list_taka > total:
        discount = list_taka - total
    elif list_taka < total:
        list_taka = total
        discount = 0
    return {
        "total_taka": total,
        "payment_count": totals["count"],
        "list_taka": list_taka,
        "discount_taka": discount,
        "discount_standing_taka": standing,
        "discount_offer_taka": offer,
        "discount_admission_taka": admission,
    }


def _prior_window(kind, start, end):
    """Previous equal-length window, or None when overall/dates."""
    if kind in {"overall", "dates"} or start is None or end is None:
        return None
    if kind == "month":
        if start.month == 1:
            prev_start = date(start.year - 1, 12, 1)
        else:
            prev_start = date(start.year, start.month - 1, 1)
        last_day = calendar.monthrange(prev_start.year, prev_start.month)[1]
        return prev_start, date(prev_start.year, prev_start.month, last_day)
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return prev_start, prev_end


def _filter_paid(base_qs, *, start, end, dates, member_id=None, channel="all"):
    rows = base_qs
    if dates:
        rows = rows.filter(report_day__in=dates)
    else:
        if start:
            rows = rows.filter(report_day__gte=start)
        if end:
            rows = rows.filter(report_day__lte=end)
    if member_id:
        rows = rows.filter(member__user_id=member_id)
    if channel != "all":
        rows = rows.filter(channel=channel)
    return rows


def _resolve_window(data):
    chosen = data.get("date", timezone.localdate())
    kind = data.get("range") or "month"
    dates = []
    raw_dates = data.get("dates") or ""
    if isinstance(raw_dates, str) and raw_dates.strip():
        try:
            dates = sorted(
                {date.fromisoformat(p.strip()) for p in raw_dates.split(",") if p.strip()}
            )
        except ValueError as exc:
            raise ValidationError({"dates": "Enter valid dates."}) from exc
        if not dates or len(dates) > 62:
            raise ValidationError({"dates": "Choose between 1 and 62 dates."})
        kind = "dates"
    start, end = None, None
    if kind == "dates":
        if not dates:
            raise ValidationError({"dates": "Choose at least one date."})
        start, end = dates[0], dates[-1]
    elif kind == "day":
        start = end = chosen
    elif kind == "week":
        start, end = chosen - timedelta(days=6), chosen
    elif kind == "month":
        start, end = (
            chosen.replace(day=1),
            chosen.replace(day=calendar.monthrange(chosen.year, chosen.month)[1]),
        )
    elif kind == "overall":
        start = end = None
    elif kind == "custom":
        start, end = data.get("from"), data.get("to")
        if not start or not end or start > end:
            raise ValidationError({"to": "Choose a valid start and end date."})
    else:
        raise ValidationError({"range": "Choose a valid range."})
    return kind, start, end, dates


def _payment_base():
    return Payment.objects.annotate(
        report_day=TruncDate(Coalesce("paid_at", "created_at"), tzinfo=UTC)
    )


def _series_keys(kind, start, end, dates, buckets, *, monthly=False):
    if kind == "overall":
        return sorted(buckets)
    if kind == "dates":
        return [d.isoformat() for d in dates]
    if monthly and start and end:
        keys = []
        cur = start.replace(day=1)
        while cur <= end:
            keys.append(cur.strftime("%Y-%m"))
            cur = date(cur.year + 1, 1, 1) if cur.month == 12 else cur.replace(month=cur.month + 1)
        return keys
    if kind == "month":
        return sorted(buckets)
    if start and end:
        return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    return sorted(buckets)


def _share_pct(part, total):
    if total <= 0:
        return 0
    return round(100 * part / total)


def revenue(actor, data):
    require_admin(actor)
    kind, start, end, dates = _resolve_window(data)
    channel = data.get("channel") or "all"
    base = _payment_base()
    rows = _filter_paid(
        base,
        start=start,
        end=end,
        dates=dates,
        member_id=data.get("member_id"),
        channel=channel,
    )
    paid = rows.filter(status="paid")
    discount_totals = _discount_aggregates(paid)
    by_channel = {"cash": 0, "sslcommerz": 0}
    for group in paid.order_by().values("channel").annotate(amount=Sum("amount_taka")):
        by_channel[group["channel"]] = group["amount"]
    by_plan = {
        (group["catalog_id"] or "other"): group["amount"]
        for group in paid.order_by().values("catalog_id").annotate(amount=Sum("amount_taka"))
    }
    buckets = {}
    monthly = kind == "overall" or (
        kind == "custom" and start and end and (end - start).days + 1 > 90
    )
    for group in (
        paid.filter(paid_at__isnull=False)
        .order_by()
        .annotate(bucket=TruncDate("paid_at", tzinfo=UTC))
        .values("bucket")
        .annotate(
            amount=Sum("amount_taka"),
            count=Count("id"),
            list_amount=Sum(
                Coalesce("list_amount_taka", "amount_taka", output_field=IntegerField())
            ),
        )
    ):
        key = group["bucket"].strftime("%Y-%m" if monthly else "%Y-%m-%d")
        bucket = buckets.setdefault(
            key,
            {"bucket": key, "amount_taka": 0, "list_amount_taka": 0, "count": 0},
        )
        bucket["amount_taka"] += group["amount"]
        bucket["list_amount_taka"] += group["list_amount"] or 0
        bucket["count"] += group["count"]
    keys = _series_keys(kind, start, end, dates, buckets, monthly=monthly)
    series = []
    for key in keys:
        point = buckets.get(
            key, {"bucket": key, "amount_taka": 0, "list_amount_taka": 0, "count": 0}
        )
        list_amt = point.get("list_amount_taka") or point["amount_taka"]
        series.append(
            {
                "bucket": point["bucket"],
                "amount_taka": point["amount_taka"],
                "list_amount_taka": list_amt,
                "discount_taka": max(0, list_amt - point["amount_taka"]),
                "count": point["count"],
            }
        )
    payments = []
    for p in rows.select_related("member__user").order_by("-paid_at", "-created_at", "-id")[
        : data.get("limit") or 50
    ]:
        payments.append(
            {
                **PaymentSerializer(p).data,
                "member_id": str(p.member.user_id),
                "member_display_id": p.member.member_id,
                "member_name": p.member.user.full_name,
            }
        )
    prior = None
    prior_bounds = _prior_window(kind, start, end)
    if prior_bounds is not None:
        prior_start, prior_end = prior_bounds
        prior_rows = _filter_paid(
            base,
            start=prior_start,
            end=prior_end,
            dates=None,
            member_id=data.get("member_id"),
            channel=channel,
        ).filter(status="paid")
        prior = {
            **_discount_aggregates(prior_rows),
            "from": prior_start,
            "to": prior_end,
        }
    return {
        "range": kind,
        "from": start,
        "to": end,
        **discount_totals,
        "failed_count": rows.filter(status="failed").count(),
        "by_channel": by_channel,
        "by_plan": by_plan,
        "payments": payments,
        "series": series,
        "prior": prior,
    }


def cash_vs_online(actor, data):
    require_admin(actor)
    kind, start, end, dates = _resolve_window(data)
    paid = _filter_paid(
        _payment_base(), start=start, end=end, dates=dates
    ).filter(status="paid")
    cash = paid.filter(channel="cash").aggregate(
        amount=Sum("amount_taka"), count=Count("id")
    )
    online = paid.filter(channel="sslcommerz").aggregate(
        amount=Sum("amount_taka"), count=Count("id")
    )
    cash_taka = cash["amount"] or 0
    online_taka = online["amount"] or 0
    total = cash_taka + online_taka
    monthly = kind == "overall" or (
        kind == "custom" and start and end and (end - start).days + 1 > 90
    )
    buckets = {}
    for group in (
        paid.filter(paid_at__isnull=False)
        .order_by()
        .annotate(bucket=TruncDate("paid_at", tzinfo=UTC))
        .values("bucket", "channel")
        .annotate(amount=Sum("amount_taka"))
    ):
        key = group["bucket"].strftime("%Y-%m" if monthly else "%Y-%m-%d")
        point = buckets.setdefault(key, {"bucket": key, "cash_taka": 0, "online_taka": 0})
        if group["channel"] == "cash":
            point["cash_taka"] += group["amount"]
        else:
            point["online_taka"] += group["amount"]
    keys = _series_keys(kind, start, end, dates, buckets, monthly=monthly)
    series = [
        buckets.get(key, {"bucket": key, "cash_taka": 0, "online_taka": 0}) for key in keys
    ]
    return {
        "from": start,
        "to": end,
        "cash_taka": cash_taka,
        "online_taka": online_taka,
        "total_taka": total,
        "cash_share_pct": _share_pct(cash_taka, total),
        "online_share_pct": _share_pct(online_taka, total),
        "payment_count_cash": cash["count"] or 0,
        "payment_count_online": online["count"] or 0,
        "series": series,
    }


def member_collections(actor, data):
    require_admin(actor)
    kind, start, end, dates = _resolve_window(data)
    channel = data.get("channel") or "all"
    paid = _filter_paid(
        _payment_base(),
        start=start,
        end=end,
        dates=dates,
        channel=channel,
    ).filter(status="paid")
    total = paid.aggregate(amount=Sum("amount_taka"))["amount"] or 0
    members = []
    for row in (
        paid.order_by()
        .values(
            "member__user_id",
            "member__member_id",
            "member__user__full_name",
        )
        .annotate(amount_taka=Sum("amount_taka"), paid_count=Count("id"))
        .order_by("-amount_taka")
    ):
        members.append(
            {
                "member_id": str(row["member__user_id"]),
                "display_id": row["member__member_id"],
                "name": row["member__user__full_name"],
                "paid_count": row["paid_count"],
                "amount_taka": row["amount_taka"] or 0,
            }
        )
    return {"from": start, "to": end, "total_taka": total, "members": members}


def revenue_vs_expense(actor, data):
    require_admin(actor)
    kind, start, end, dates = _resolve_window(data)
    paid = _filter_paid(
        _payment_base(), start=start, end=end, dates=dates
    ).filter(status="paid")
    revenue_taka = paid.aggregate(amount=Sum("amount_taka"))["amount"] or 0
    costs = Cost.objects.filter(is_archived=False)
    if dates:
        costs = costs.filter(date__in=dates)
    else:
        if start:
            costs = costs.filter(date__gte=start)
        if end:
            costs = costs.filter(date__lte=end)
    expense_taka = costs.aggregate(amount=Sum("amount_taka"))["amount"] or 0
    by_category = {
        (row["category"] or "other"): row["amount"] or 0
        for row in costs.order_by().values("category").annotate(amount=Sum("amount_taka"))
    }
    monthly = kind == "overall" or (
        kind == "custom" and start and end and (end - start).days + 1 > 90
    )
    buckets = {}
    for group in (
        paid.filter(paid_at__isnull=False)
        .order_by()
        .annotate(bucket=TruncDate("paid_at", tzinfo=UTC))
        .values("bucket")
        .annotate(amount=Sum("amount_taka"))
    ):
        key = group["bucket"].strftime("%Y-%m" if monthly else "%Y-%m-%d")
        point = buckets.setdefault(
            key, {"bucket": key, "revenue_taka": 0, "expense_taka": 0}
        )
        point["revenue_taka"] += group["amount"]
    for row in costs.order_by().values("date").annotate(amount=Sum("amount_taka")):
        key = row["date"].strftime("%Y-%m" if monthly else "%Y-%m-%d")
        point = buckets.setdefault(
            key, {"bucket": key, "revenue_taka": 0, "expense_taka": 0}
        )
        point["expense_taka"] += row["amount"] or 0
    keys = _series_keys(kind, start, end, dates, buckets, monthly=monthly)
    series = [
        buckets.get(key, {"bucket": key, "revenue_taka": 0, "expense_taka": 0})
        for key in keys
    ]
    return {
        "from": start,
        "to": end,
        "revenue_taka": revenue_taka,
        "expense_taka": expense_taka,
        "net_taka": revenue_taka - expense_taka,
        "by_cost_category": by_category,
        "series": series,
    }


def membership_status(actor, data):
    require_admin(actor)
    within = data.get("within_days") or 7
    if within < 1 or within > 90:
        raise ValidationError({"within_days": "Choose between 1 and 90 days."})
    today = timezone.localdate()
    soon = today + timedelta(days=within)
    expired = []
    expiring = []
    for m in (
        MemberProfile.objects.filter(membership_status__in=["active", "expired"])
        .select_related("user", "plan")
        .order_by("expires_on", "member_id")
    ):
        if m.expires_on is None:
            continue
        days_left = (m.expires_on - today).days
        row = {
            "member_id": str(m.user_id),
            "display_id": m.member_id,
            "name": m.user.full_name,
            "plan": m.plan.name if m.plan_id else None,
            "catalog_id": m.plan.catalog_id if m.plan_id else None,
            "expires_on": m.expires_on,
            "days_left": days_left,
        }
        if m.membership_status == "expired" or days_left < 0:
            expired.append(row)
        elif days_left <= within and m.expires_on <= soon:
            expiring.append(row)
    return {
        "as_of": today,
        "within_days": within,
        "expired": expired,
        "expiring_soon": expiring,
    }


def expenses_by_admin(actor, data):
    require_admin(actor)
    kind, start, end, dates = _resolve_window(data)
    costs = Cost.objects.filter(is_archived=False).select_related(
        "created_by", "created_by__staff_profile"
    )
    if dates:
        costs = costs.filter(date__in=dates)
    else:
        if start:
            costs = costs.filter(date__gte=start)
        if end:
            costs = costs.filter(date__lte=end)
    total = costs.aggregate(amount=Sum("amount_taka"))["amount"] or 0
    by_category = {
        (row["category"] or "other"): row["amount"] or 0
        for row in costs.order_by().values("category").annotate(amount=Sum("amount_taka"))
    }
    by_admin_map = {}
    for cost in costs:
        user = cost.created_by
        key = str(user.pk) if user else "unknown"
        entry = by_admin_map.setdefault(
            key,
            {
                "admin_id": key if user else None,
                "short_id": getattr(getattr(user, "staff_profile", None), "short_id", None)
                if user
                else None,
                "name": user.full_name if user else "Unknown",
                "amount_taka": 0,
                "count": 0,
            },
        )
        entry["amount_taka"] += cost.amount_taka
        entry["count"] += 1
    by_admin = sorted(by_admin_map.values(), key=lambda r: r["amount_taka"], reverse=True)
    return {
        "from": start,
        "to": end,
        "total_taka": total,
        "by_admin": by_admin,
        "by_category": by_category,
    }


def _payment_has_admission_activity(payment):
    """True when admission was charged or waived (first join or re-admission after lapse)."""
    if (payment.admission_waived_taka or 0) > 0:
        return True
    for item in payment.line_items or []:
        if isinstance(item, dict) and item.get("label") == "Admission fee":
            if int(item.get("amount_taka") or 0) > 0:
                return True
    return False


def admission_report(actor, data):
    require_admin(actor)
    kind, start, end, dates = _resolve_window(data)
    # Include re-admission after 180-day lapse (is_first_payment=False but admission
    # line / waived columns set). Seat math still uses is_first_payment only.
    paid = _filter_paid(_payment_base(), start=start, end=end, dates=dates).filter(status="paid")
    waived_total = 0
    collected_total = 0
    waived_count = 0
    admission_payment_count = 0
    buckets = {}
    monthly = kind == "overall" or (
        kind == "custom" and start and end and (end - start).days + 1 > 90
    )
    for payment in paid:
        if not _payment_has_admission_activity(payment):
            continue
        admission_payment_count += 1
        waived = payment.admission_waived_taka or 0
        collected = 0
        for item in payment.line_items or []:
            if isinstance(item, dict) and item.get("label") == "Admission fee":
                collected += int(item.get("amount_taka") or 0)
        waived_total += waived
        collected_total += collected
        if waived > 0:
            waived_count += 1
        day = (payment.paid_at or payment.created_at).astimezone(UTC).date()
        key = day.strftime("%Y-%m" if monthly else "%Y-%m-%d")
        point = buckets.setdefault(
            key, {"bucket": key, "collected_taka": 0, "waived_taka": 0}
        )
        point["collected_taka"] += collected
        point["waived_taka"] += waived
    keys = _series_keys(kind, start, end, dates, buckets, monthly=monthly)
    series = [
        buckets.get(key, {"bucket": key, "collected_taka": 0, "waived_taka": 0})
        for key in keys
    ]
    return {
        "from": start,
        "to": end,
        "admission_collected_taka": collected_total,
        "admission_waived_taka": waived_total,
        "first_payment_count": admission_payment_count,
        "waived_count": waived_count,
        "series": series,
    }


def plan_mix(actor, data):
    require_admin(actor)
    kind, start, end, dates = _resolve_window(data)
    channel = data.get("channel") or "all"
    paid = _filter_paid(
        _payment_base(),
        start=start,
        end=end,
        dates=dates,
        channel=channel,
    ).filter(status="paid")
    total = paid.aggregate(amount=Sum("amount_taka"))["amount"] or 0
    by_plan = []
    for row in (
        paid.order_by()
        .values("catalog_id")
        .annotate(amount_taka=Sum("amount_taka"), payment_count=Count("id"))
        .order_by("-amount_taka")
    ):
        amount = row["amount_taka"] or 0
        by_plan.append(
            {
                "catalog_id": row["catalog_id"] or "other",
                "amount_taka": amount,
                "payment_count": row["payment_count"],
                "share_pct": _share_pct(amount, total),
            }
        )
    return {"from": start, "to": end, "total_taka": total, "by_plan": by_plan}
