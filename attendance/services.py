from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from attendance.models import CheckIn
from members.models import MemberProfile
from members.services import owned_profile
from operations.models import WeekdayHours
from operations.services import DHAKA


def month_attendance(user, year, month):
    p = owned_profile(user)
    days = list(
        p.check_ins.filter(check_in_date__year=year, check_in_date__month=month)
        .order_by("check_in_date")
        .values_list("check_in_date", flat=True)
    )
    closed = WeekdayHours.objects.filter(is_open=False).order_by("weekday").first()
    return {
        "year": year,
        "month": month,
        "attended_days": days,
        "visit_count": len(days),
        "closed_weekday": closed.weekday if closed else 5,
    }


@transaction.atomic
def record_checkin(data):
    member = get_object_or_404(MemberProfile, member_id=data["member_id"])
    at = data.get("checked_in_at") or timezone.now()
    row, created = CheckIn.objects.get_or_create(
        member=member,
        check_in_date=at.astimezone(DHAKA).date(),
        defaults={"checked_in_at": at, "source": data.get("source", "device")},
    )
    return {
        "member_uuid": str(member.user_id),
        "member_id": member.member_id,
        "day": row.check_in_date,
        "recorded": created,
        "checked_in_at": row.checked_in_at,
    }
