import calendar
from datetime import UTC, date, timedelta

from django.db.models import Count, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.api import require_admin
from payments.models import Payment
from payments.serializers import PaymentSerializer


def revenue(actor, data):
    require_admin(actor)
    chosen = data.get("date", timezone.localdate())
    kind = data["range"]
    dates = []
    if data.get("dates", "").strip():
        try:
            dates = sorted(
                {date.fromisoformat(p.strip()) for p in data["dates"].split(",") if p.strip()}
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
    elif kind == "custom":
        start, end = data.get("from"), data.get("to")
        if not start or not end or start > end:
            raise ValidationError({"to": "Choose a valid start and end date."})
    rows = Payment.objects.annotate(
        report_day=TruncDate(Coalesce("paid_at", "created_at"), tzinfo=UTC)
    )
    if dates:
        rows = rows.filter(report_day__in=dates)
    else:
        if start:
            rows = rows.filter(report_day__gte=start)
        if end:
            rows = rows.filter(report_day__lte=end)
    if data.get("member_id"):
        rows = rows.filter(member__user_id=data["member_id"])
    if data["channel"] != "all":
        rows = rows.filter(channel=data["channel"])
    paid = rows.filter(status="paid")
    totals = paid.aggregate(total=Sum("amount_taka"), count=Count("id"))
    by_channel = {"cash": 0, "sslcommerz": 0}
    for group in paid.order_by().values("channel").annotate(amount=Sum("amount_taka")):
        by_channel[group["channel"]] = group["amount"]
    by_plan = {
        (group["catalog_id"] or "other"): group["amount"]
        for group in paid.order_by().values("catalog_id").annotate(amount=Sum("amount_taka"))
    }
    buckets = {}
    monthly = kind == "overall" or (kind == "custom" and (end - start).days + 1 > 90)
    for group in (
        paid.filter(paid_at__isnull=False)
        .order_by()
        .annotate(bucket=TruncDate("paid_at", tzinfo=UTC))
        .values("bucket")
        .annotate(amount=Sum("amount_taka"), count=Count("id"))
    ):
        key = group["bucket"].strftime("%Y-%m" if monthly else "%Y-%m-%d")
        bucket = buckets.setdefault(key, {"bucket": key, "amount_taka": 0, "count": 0})
        bucket["amount_taka"] += group["amount"]
        bucket["count"] += group["count"]
    keys = []
    if kind == "overall":
        keys = sorted(buckets)
    elif kind == "dates":
        keys = [d.isoformat() for d in dates]
    elif monthly:
        cur = start.replace(day=1)
        while cur <= end:
            keys.append(cur.strftime("%Y-%m"))
            cur = date(cur.year + 1, 1, 1) if cur.month == 12 else cur.replace(month=cur.month + 1)
    elif kind == "month":
        keys = sorted(buckets)
    else:
        keys = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    payments = []
    for p in rows.select_related("member__user").order_by("-paid_at", "-created_at", "-id")[
        : data["limit"]
    ]:
        payments.append(
            {
                **PaymentSerializer(p).data,
                "member_id": str(p.member.user_id),
                "member_display_id": p.member.member_id,
                "member_name": p.member.user.full_name,
            }
        )
    return {
        "range": kind,
        "from": start,
        "to": end,
        "total_taka": totals["total"] or 0,
        "payment_count": totals["count"],
        "failed_count": rows.filter(status="failed").count(),
        "by_channel": by_channel,
        "by_plan": by_plan,
        "payments": payments,
        "series": [buckets.get(key, {"bucket": key, "amount_taka": 0, "count": 0}) for key in keys],
    }
