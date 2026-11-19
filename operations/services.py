import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.crypto import normalize_phone
from accounts.identifiers import next_display
from accounts.models import StaffProfile, User
from core.api import Conflict, require_admin
from operations.models import Activity, Cost, Holiday, WeekdayHours

DHAKA = ZoneInfo("Asia/Dhaka")
DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def record(actor, area, action, key, params=None):
    require_admin(actor)
    return Activity.objects.create(
        admin=actor,
        admin_name=actor.full_name,
        admin_short_id=actor.staff_profile.short_id,
        area=area,
        action=action,
        summary_key=key,
        summary_params={
            re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", key).lower(): value
            for key, value in (params or {}).items()
        },
    )


@transaction.atomic
def save_staff(actor, data, instance=None):
    from accounts.staff_permissions import normalize_permissions

    require_admin(actor, True)
    created = instance is None
    if instance:
        instance = User.objects.select_for_update().get(pk=instance.pk, role="admin")
        if instance.is_superuser and (
            data.get("phone_e164", instance.phone_e164) != instance.phone_e164
            or data.get("is_active") is False
        ):
            raise PermissionDenied(
                "Cannot change the super admin phone or deactivate this account."
            )
    phone = normalize_phone(data.get("phone_e164", instance.phone_e164 if instance else ""))
    if User.objects.filter(phone_e164=phone).exclude(pk=getattr(instance, "pk", None)).exists():
        raise Conflict("Phone number is already registered.")
    perms_provided = "permissions" in data
    permissions = normalize_permissions(data.get("permissions")) if perms_provided else None
    if not instance:
        instance = User.objects.create_user(
            phone, role="admin", full_name=data["name"], is_active=data.get("is_active", True)
        )
        StaffProfile.objects.create(
            user=instance,
            short_id=next_display("staff"),
            permissions=permissions if permissions is not None else [],
        )
    else:
        instance.full_name = data.get("name", instance.full_name)
        instance.phone_e164 = phone
        instance.is_active = data.get("is_active", instance.is_active)
        instance.save()
        if permissions is not None and not instance.is_superuser:
            profile = instance.staff_profile
            profile.permissions = permissions
            profile.save(update_fields=["permissions", "updated_at"])
    record(
        actor,
        "staff",
        "create" if created else "update",
        "adminActivityStaffCreated" if created else "adminActivityStaffUpdated",
        {"name": instance.full_name, "shortId": instance.staff_profile.short_id},
    )
    return instance


@transaction.atomic
def set_staff_active(actor, user, active):
    require_admin(actor, True)
    user = User.objects.select_for_update().get(pk=user.pk, role="admin")
    if user.is_superuser and not active:
        raise PermissionDenied("Cannot deactivate the super admin.")
    if user.is_active != active:
        user.is_active = active
        user.save()
        record(
            actor,
            "staff",
            "activate" if active else "deactivate",
            "adminActivityStaffActivated" if active else "adminActivityStaffDeactivated",
            {"name": user.full_name, "shortId": user.staff_profile.short_id},
        )
    return user


@transaction.atomic
def delete_staff(actor, user):
    require_admin(actor, True)
    user = User.objects.select_for_update().get(pk=user.pk, role="admin")
    if user.is_superuser:
        raise PermissionDenied("Cannot remove the super admin.")
    record(
        actor,
        "staff",
        "delete",
        "adminActivityStaffDeleted",
        {"name": user.full_name, "shortId": user.staff_profile.short_id},
    )
    user.staff_profile.delete()
    user.delete()


@transaction.atomic
def save_cost(actor, data, instance=None):
    require_admin(actor)
    created = instance is None
    if instance:
        instance = Cost.objects.select_for_update().get(pk=instance.pk)
        for key, value in data.items():
            setattr(instance, key, value)
        instance.save()
    else:
        instance = Cost.objects.create(created_by=actor, **data)
    record(
        actor,
        "cost",
        "create" if created else "update",
        "adminActivityCostCreated" if created else "adminActivityCostUpdated",
        {"title": instance.title},
    )
    return instance


@transaction.atomic
def mutate_cost(actor, cost, action):
    require_admin(actor)
    cost = Cost.objects.select_for_update().get(pk=cost.pk)
    if action == "archive":
        cost.is_archived = True
        cost.save()
    else:
        cost.delete()
    record(
        actor,
        "cost",
        action,
        "adminActivityCostArchived" if action == "archive" else "adminActivityCostDeleted",
        {"title": cost.title},
    )
    return cost


def week_data():
    return [
        {
            "weekday": d,
            "is_open": r.is_open if r else False,
            "open_time": r.open_time.strftime("%H:%M") if r and r.open_time else None,
            "close_time": r.close_time.strftime("%H:%M") if r and r.close_time else None,
        }
        for d, r in ((d, WeekdayHours.objects.filter(pk=d).first()) for d in range(1, 8))
    ]


def holiday_data(row):
    return {"id": str(row.pk), "date": row.date.isoformat(), "name": row.name}


@transaction.atomic
def put_week(actor, data):
    require_admin(actor)
    if len(data) != 7 or {d["weekday"] for d in data} != set(range(1, 8)):
        raise ValidationError({"week": "Include all seven weekdays exactly once."})
    for d in data:
        opened, closed = d.get("open_time"), d.get("close_time")
        if d["is_open"] and (opened is None or closed is None or opened >= closed):
            raise ValidationError({"week": "Opening time must be before closing time."})
        WeekdayHours.objects.update_or_create(
            weekday=d["weekday"],
            defaults={
                "is_open": d["is_open"],
                "open_time": opened if d["is_open"] else None,
                "close_time": closed if d["is_open"] else None,
            },
        )
    record(actor, "gym", "update", "adminActivityGymHoursUpdated")
    return {
        "week": week_data(),
        "holidays": [holiday_data(h) for h in Holiday.objects.order_by("date")],
    }


@transaction.atomic
def save_holiday(actor, data, instance=None):
    require_admin(actor)
    created = instance is None
    if instance:
        for key, value in data.items():
            setattr(instance, key, value)
        instance.save()
    else:
        instance = Holiday.objects.create(**data)
    record(
        actor,
        "gym",
        "create" if created else "update",
        "adminActivityGymHolidayCreated" if created else "adminActivityGymHolidayUpdated",
        {"date": instance.date.isoformat(), "name": instance.name or ""},
    )
    return instance


@transaction.atomic
def delete_holiday(actor, instance):
    require_admin(actor)
    instance.delete()
    record(
        actor,
        "gym",
        "delete",
        "adminActivityGymHolidayDeleted",
        {"date": instance.date.isoformat(), "name": instance.name or ""},
    )


def hours_summary(week):
    by_day = {d["weekday"]: d for d in week}
    groups = []
    for index, day in enumerate([6, 7, 1, 2, 3, 4, 5]):
        row = by_day[day]
        if not row["is_open"] or not row["open_time"] or not row["close_time"]:
            continue
        if (
            groups
            and groups[-1]["last"] == index - 1
            and groups[-1]["times"] == (row["open_time"], row["close_time"])
        ):
            groups[-1]["days"].append(day)
            groups[-1]["last"] = index
        else:
            groups.append(
                {"last": index, "days": [day], "times": (row["open_time"], row["close_time"])}
            )
    if not groups:
        return "Closed"
    group = max(groups, key=lambda g: len(g["days"]))
    start, end = [datetime.strptime(t, "%H:%M").strftime("%I:%M %p") for t in group["times"]]
    labels = [DAY_LABELS[d - 1] for d in group["days"]]
    days = labels[0] if len(labels) == 1 else f"{labels[0]} – {labels[-1]}"
    return f"{start} – {end} ({days})"


def gym_status(now=None):
    now = (now or timezone.now()).astimezone(DHAKA)
    week = week_data()
    today = week[now.isoweekday() - 1]
    holiday = Holiday.objects.filter(date=now.date()).first()
    upcoming = Holiday.objects.filter(date__gte=now.date()).order_by("date")[:30]
    opened = bool(
        not holiday
        and today["is_open"]
        and today["open_time"]
        and today["open_time"] <= now.strftime("%H:%M") < today["close_time"]
    )
    return {
        "timezone": "Asia/Dhaka",
        "is_open_now": opened,
        "status": "open" if opened else "closed",
        "today_weekday": now.isoweekday(),
        "today_is_holiday": bool(holiday),
        "today_holiday_name": holiday.name if holiday else None,
        "today_is_weekly_closed": not bool(holiday) and not today["is_open"],
        "today_open_time": today["open_time"] if not holiday and today["is_open"] else None,
        "today_close_time": today["close_time"] if not holiday and today["is_open"] else None,
        "hours_summary": hours_summary(week),
        "closed_day_label": (holiday.name or "Holiday")
        if holiday
        else (f"{DAY_LABELS[now.weekday()]} Closed" if not today["is_open"] else None),
        "week": week,
        "upcoming_holidays": [holiday_data(h) for h in upcoming],
    }


def seed_hours():
    for weekday in range(1, 8):
        WeekdayHours.objects.get_or_create(
            weekday=weekday,
            defaults={
                "is_open": weekday != 5,
                "open_time": time(6) if weekday != 5 else None,
                "close_time": time(22) if weekday != 5 else None,
            },
        )
