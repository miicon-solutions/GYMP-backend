from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from attendance.models import CheckIn
from fitness.services import get_profile
from members.models import MemberProfile
from members.services import owned_profile
from operations.models import Holiday, WeekdayHours
from operations.services import DHAKA
from schedules.models import SplitPlannerCycle
from workouts.models import WorkoutSession, WorkoutSet

AUTO_SESSION_CAP_MINUTES = 120


def resolve_visit_duration(checkin: CheckIn, now=None) -> tuple[int, bool]:
    """Calculate visit duration in minutes and auto-end missed exit scans after 2 hours (120m)."""
    now = now or timezone.now()
    if checkin.checked_out_at is not None:
        if checkin.duration_minutes is not None:
            return int(checkin.duration_minutes), False
        mins = max(1, min(720, int((checkin.checked_out_at - checkin.checked_in_at).total_seconds() // 60)))
        checkin.duration_minutes = mins
        checkin.save(update_fields=["duration_minutes", "updated_at"])
        return mins, False

    elapsed = max(0, int((now - checkin.checked_in_at).total_seconds() // 60))
    today_dhaka = now.astimezone(DHAKA).date()
    if elapsed >= AUTO_SESSION_CAP_MINUTES or checkin.check_in_date < today_dhaka:
        checkin.checked_out_at = checkin.checked_in_at + timedelta(minutes=AUTO_SESSION_CAP_MINUTES)
        checkin.duration_minutes = AUTO_SESSION_CAP_MINUTES
        checkin.auto_closed = True
        checkin.check_out_source = "auto_cap"
        checkin.save(
            update_fields=[
                "checked_out_at",
                "duration_minutes",
                "auto_closed",
                "check_out_source",
                "updated_at",
            ]
        )
        return AUTO_SESSION_CAP_MINUTES, False

    return max(1, elapsed), True


def _get_protected_day_info(day, closed_weekdays: set[int], holiday_names: dict, active_cycle, rest_indices: set[int]):
    """Determine if a date is excused/protected (gym closed, holiday, or Routine Planner rest day)."""
    if day in holiday_names:
        h_name = holiday_names[day] or "Gym Holiday"
        return True, f"Gym closed ({h_name})", f"জিম বন্ধ ({h_name})"
    if day.isoweekday() in closed_weekdays:
        return True, "Gym weekly closed day", "জিমের সাপ্তাহিক বন্ধের দিন"
    if active_cycle and active_cycle.day_index_for(day) in rest_indices:
        return True, "Planned rest day (Routine Planner)", "পরিকল্পিত বিশ্রামের দিন (রুটিন প্ল্যানার)"
    return False, "", ""


def build_motivation_payload(user, member_profile: MemberProfile | None = None, now=None) -> dict:
    """Build Duolingo-style motivation avatar state, protected streak, and personal insights (Suggestion 1)."""
    now = now or timezone.now()
    today_dhaka = now.astimezone(DHAKA).date()
    mp = member_profile or getattr(user, "member_profile", None)
    fp = get_profile(user)

    closed_weekdays = set(
        WeekdayHours.objects.filter(is_open=False).values_list("weekday", flat=True)
    )
    if not WeekdayHours.objects.exists():
        closed_weekdays = {5}

    lookback_start = today_dhaka - timedelta(days=365)
    holiday_names = {
        h.date: h.name
        for h in Holiday.objects.filter(date__gte=lookback_start, date__lte=today_dhaka + timedelta(days=7))
    }

    active_cycle = (
        SplitPlannerCycle.objects.filter(user=user, is_active=True)
        .prefetch_related("days")
        .first()
    )
    rest_indices = set()
    today_scheduled_label = ""
    if active_cycle:
        for d in active_cycle.days.all():
            if d.is_rest_day:
                rest_indices.add(d.day_index)
            if d.day_index == active_cycle.day_index_for(today_dhaka):
                today_scheduled_label = "Rest Day" if d.is_rest_day else (d.label or "Training")

    attended_dates = set()
    if mp:
        attended_dates.update(
            mp.check_ins.filter(check_in_date__gte=lookback_start).values_list(
                "check_in_date", flat=True
            )
        )
    workout_dates = {
        s.start_time.astimezone(DHAKA).date()
        for s in WorkoutSession.objects.filter(
            user=user, status="completed", start_time__date__gte=lookback_start
        ).only("start_time")
    }
    active_dates = attended_dates | workout_dates

    # Calculate current streak (walking backwards from today; protected days never break a streak!)
    current_streak = 0
    protected_rest_days = 0
    cursor = today_dhaka
    for _ in range(365):
        if cursor in active_dates:
            current_streak += 1
        elif cursor == today_dhaka:
            # Today is still ongoing; don't break yesterday's streak
            pass
        else:
            is_prot, _, _ = _get_protected_day_info(
                cursor, closed_weekdays, holiday_names, active_cycle, rest_indices
            )
            if is_prot:
                if current_streak > 0 or (today_dhaka - cursor).days <= 7:
                    protected_rest_days += 1
            else:
                break
        cursor -= timedelta(days=1)

    # Calculate longest streak over the past year using the same protected-day rules
    longest_streak = current_streak
    if active_dates:
        earliest = min(active_dates)
        run = 0
        d = earliest
        while d <= today_dhaka:
            if d in active_dates:
                run += 1
                longest_streak = max(longest_streak, run)
            else:
                is_prot, _, _ = _get_protected_day_info(
                    d, closed_weekdays, holiday_names, active_cycle, rest_indices
                )
                if not is_prot and d < today_dhaka:
                    run = 0
            d += timedelta(days=1)

    days_since_last = (today_dhaka - max(active_dates)).days if active_dates else None
    today_is_protected, prot_reason_en, prot_reason_bn = _get_protected_day_info(
        today_dhaka, closed_weekdays, holiday_names, active_cycle, rest_indices
    )

    week_start = today_dhaka - timedelta(days=today_dhaka.weekday())
    workouts_this_week = WorkoutSession.objects.filter(
        user=user, status="completed", start_time__date__gte=week_start
    ).count()
    prs_this_month = WorkoutSet.objects.filter(
        user=user,
        is_pr=True,
        performed_at__year=today_dhaka.year,
        performed_at__month=today_dhaka.month,
    ).count()

    trained_today = today_dhaka in active_dates
    first_name = (user.full_name or "").strip().split(" ")[0] or "Athlete"

    # Determine Avatar Mood & Headline
    if trained_today and (current_streak >= 3 or prs_this_month > 0):
        avatar_mood = "on_fire"
        headline = f"Unstoppable, {first_name}! {current_streak}-day active streak!"
        headline_bn = f"অপ্রতিরোধ্য, {first_name}! আপনার {current_streak} দিনের অ্যাক্টিভ স্ট্রিক চলছে!"
        subheadline = "You showed up today and kept your momentum burning bright."
        subheadline_bn = "আপনি আজ জিমে এসেছেন এবং আপনার ধারাবাহিকতা অক্ষুণ্ণ রেখেছেন।"
    elif trained_today:
        avatar_mood = "proud"
        headline = f"Great work showing up today, {first_name}!"
        headline_bn = f"আজ জিমে আসার জন্য দারুণ অভিনন্দন, {first_name}!"
        subheadline = f"Current streak: {current_streak} day{'s' if current_streak != 1 else ''}. Every session counts!"
        subheadline_bn = f"বর্তমান স্ট্রিক: {current_streak} দিন। প্রতিটি সেশনই আপনাকে লক্ষ্যের কাছে নিয়ে যায়!"
    elif today_is_protected:
        avatar_mood = "resting"
        headline = f"Streak Shield Active ({current_streak}-day streak safe!)"
        headline_bn = f"স্ট্রিক শিল্ড চালু আছে ({current_streak} দিনের স্ট্রিক সুরক্ষিত!)"
        subheadline = f"{prot_reason_en}. Rest and recovery never break your streak!"
        subheadline_bn = f"{prot_reason_bn}। পরিকল্পিত বিশ্রাম বা জিম বন্ধের দিনে আপনার স্ট্রিক ভাঙবে না!"
    elif days_since_last is not None and days_since_last >= 3 and current_streak == 0:
        avatar_mood = "missed_you"
        headline = f"We missed you at the gym, {first_name}!"
        headline_bn = f"জিমে আপনাকে মিস করছি, {first_name}!"
        subheadline = (
            f"It's been {days_since_last} days since your last session. Even a 30-minute workout today restarts your streak!"
        )
        subheadline_bn = (
            f"আপনার শেষ সেশনের পর {days_since_last} দিন কেটে গেছে। আজ মাত্র ৩০ মিনিটের একটি ওয়ার্কআউট দিয়েই আবার নতুন স্ট্রিক শুরু করুন!"
        )
    else:
        avatar_mood = "encouraging"
        headline = (
            f"Keep your {current_streak}-day streak alive today, {first_name}!"
            if current_streak > 0
            else f"Ready to kick off a new gym streak today, {first_name}?"
        )
        headline_bn = (
            f"আজ আপনার {current_streak} দিনের স্ট্রিক ধরে রাখুন, {first_name}!"
            if current_streak > 0
            else f"আজই কি নতুন জিম স্ট্রিক শুরু করতে প্রস্তুত, {first_name}?"
        )
        subheadline = (
            f"Today's plan: {today_scheduled_label}."
            if today_scheduled_label
            else "Check in at the scanner or log a workout to build your streak."
        )
        subheadline_bn = (
            f"আজকের রুটিন: {today_scheduled_label}।"
            if today_scheduled_label
            else "স্ট্রিক বাড়াতে জিমে চেক-ইন করুন অথবা একটি ওয়ার্কআউট লগ করুন।"
        )

    insights = [
        {
            "category": "streak",
            "title": f"{current_streak}-Day Streak (Best: {longest_streak})",
            "title_bn": f"{current_streak} দিনের স্ট্রিক (সর্বোচ্চ: {longest_streak})",
            "body": (
                f"Planned rest days and gym closed days automatically protect your streak ({protected_rest_days} rest/closed days bridged)."
            ),
            "body_bn": (
                f"রুটিন প্ল্যানারের বিশ্রামের দিন এবং জিম বন্ধের দিনগুলো আপনার স্ট্রিক সুরক্ষিত রাখে ({protected_rest_days}টি বিশ্রাম/বন্ধের দিন যুক্ত)।"
            ),
            "tone": "success" if current_streak > 0 else "info",
        },
        {
            "category": "workouts",
            "title": f"{workouts_this_week} Workouts This Week • {prs_this_month} PRs This Month",
            "title_bn": f"এই সপ্তাহে {workouts_this_week}টি ওয়ার্কআউট • এই মাসে {prs_this_month}টি নতুন রেকর্ড (PR)",
            "body": (
                "Amazing strength progression! Keep logging your sets and timed exercises."
                if workouts_this_week > 0
                else "Log your next workout session to track estimated calories and strength gains."
            ),
            "body_bn": (
                "দারুণ শক্তির অগ্রগতি! আপনার সেট এবং টাইমড ব্যায়ামগুলো নিয়মিত লগ করুন।"
                if workouts_this_week > 0
                else "ক্যালোরি ও শক্তির উন্নতি ট্র্যাক করতে আপনার পরবর্তী ওয়ার্কআউট লগ করুন।"
            ),
            "tone": "success" if workouts_this_week > 0 else "neutral",
        },
    ]
    if today_scheduled_label:
        insights.append(
            {
                "category": "routine",
                "title": f"Today's Routine: {today_scheduled_label}",
                "title_bn": f"আজকের রুটিন: {today_scheduled_label}",
                "body": (
                    "Today is a scheduled recovery day — rest up guilt-free without losing your streak!"
                    if today_is_protected
                    else f"Your Routine Planner has '{today_scheduled_label}' lined up for today."
                ),
                "body_bn": (
                    "আজ আপনার নির্ধারিত বিশ্রামের দিন — স্ট্রিক হারানোর চিন্তা ছাড়াই বিশ্রাম নিন!"
                    if today_is_protected
                    else f"আপনার রুটিন প্ল্যানারে আজ '{today_scheduled_label}' নির্ধারিত আছে।"
                ),
                "tone": "info",
            }
        )

    if fp.motivation_frequency == "minimal":
        insights = insights[:1]
    elif fp.motivation_frequency == "off" or not fp.motivation_notifications_enabled:
        insights = []

    return {
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "protected_rest_days": protected_rest_days,
        "days_since_last_activity": days_since_last,
        "today_is_protected": today_is_protected,
        "today_protection_reason": prot_reason_en,
        "today_protection_reason_bn": prot_reason_bn,
        "avatar_mood": avatar_mood,
        "avatar_name": "Coach Tiger",
        "headline": headline,
        "headline_bn": headline_bn,
        "subheadline": subheadline,
        "subheadline_bn": subheadline_bn,
        "notifications_enabled": fp.motivation_notifications_enabled,
        "notification_frequency": fp.motivation_frequency,
        "workouts_this_week": workouts_this_week,
        "prs_this_month": prs_this_month,
        "insights": insights,
    }


def month_attendance(user, year, month):
    p = owned_profile(user)
    now = timezone.now()
    today_dhaka = now.astimezone(DHAKA).date()
    week_start = today_dhaka - timedelta(days=today_dhaka.weekday())

    month_checkins = list(
        p.check_ins.filter(check_in_date__year=year, check_in_date__month=month).order_by(
            "check_in_date"
        )
    )
    days = [c.check_in_date for c in month_checkins]
    sessions = []
    for c in month_checkins:
        dur, is_active = resolve_visit_duration(c, now=now)
        sessions.append(
            {
                "date": c.check_in_date,
                "checked_in_at": c.checked_in_at,
                "checked_out_at": c.checked_out_at,
                "duration_minutes": dur,
                "auto_closed": c.auto_closed,
                "check_out_source": c.check_out_source,
                "is_active_session": is_active,
            }
        )

    # Calculate today's time spent and this week's total time spent (Suggestion 2)
    week_checkins = list(
        p.check_ins.filter(check_in_date__gte=week_start, check_in_date__lte=today_dhaka)
    )
    today_minutes = 0
    week_minutes = 0
    for c in week_checkins:
        dur, _ = resolve_visit_duration(c, now=now)
        week_minutes += dur
        if c.check_in_date == today_dhaka:
            today_minutes += dur

    closed = WeekdayHours.objects.filter(is_open=False).order_by("weekday").first()
    return {
        "year": year,
        "month": month,
        "attended_days": days,
        "visit_count": len(days),
        "closed_weekday": closed.weekday if closed else 5,
        "today_minutes": today_minutes,
        "week_minutes": week_minutes,
        "week_hours": round(week_minutes / 60.0, 2),
        "auto_cap_minutes": AUTO_SESSION_CAP_MINUTES,
        "sessions": sessions,
        "motivation": build_motivation_payload(user, member_profile=p, now=now),
    }


@transaction.atomic
def record_checkout(data):
    """Record-only exit scan. Exit is never blocked behind a scan or membership status (Suggestion 2)."""
    member = get_object_or_404(
        MemberProfile.objects.select_for_update(), member_id=data["member_id"]
    )
    at = data.get("checked_out_at") or data.get("checked_in_at") or timezone.now()
    day = at.astimezone(DHAKA).date()
    source = data.get("source", "device")

    row = CheckIn.objects.filter(member=member, check_in_date=day).first()
    if row:
        row.checked_out_at = max(at, row.checked_in_at)
        raw_mins = max(1, int((row.checked_out_at - row.checked_in_at).total_seconds() // 60))
        row.duration_minutes = min(raw_mins, 480)
        row.auto_closed = False
        row.check_out_source = source
        row.save(
            update_fields=[
                "checked_out_at",
                "duration_minutes",
                "auto_closed",
                "check_out_source",
                "updated_at",
            ]
        )
    else:
        # Record-only exit when arrival scan was missed
        in_at = at - timedelta(minutes=60)
        row = CheckIn.objects.create(
            member=member,
            check_in_date=day,
            checked_in_at=in_at,
            checked_out_at=at,
            source=source,
            check_out_source=source,
            duration_minutes=60,
            auto_closed=False,
        )

    return {
        "member_uuid": str(member.user_id),
        "member_id": member.member_id,
        "day": row.check_in_date,
        "recorded": True,
        "checked_in_at": row.checked_in_at,
        "checked_out_at": row.checked_out_at,
        "duration_minutes": row.duration_minutes,
        "exit_only_record": True,
    }


@transaction.atomic
def record_checkin(data):
    if data.get("action") == "check_out" or data.get("checked_out_at"):
        return record_checkout(data)
    member = get_object_or_404(
        MemberProfile.objects.select_for_update(), member_id=data["member_id"]
    )
    if member.membership_status in {"none", "pending_payment"}:
        raise PermissionDenied("Membership payment is required before checking in.")
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
        "checked_out_at": row.checked_out_at,
        "duration_minutes": row.duration_minutes,
    }


@transaction.atomic
def member_adjust_session(user, data):
    """Allow a member to manually end their gym session or correct session duration if they forgot to scan on exit."""
    p = owned_profile(user)
    now = timezone.now()
    target_date = data.get("date") or now.astimezone(DHAKA).date()
    row = CheckIn.objects.select_for_update().filter(member=p, check_in_date=target_date).first()
    if not row:
        raise NotFound("No gym visit found for that date to adjust.")

    action = data.get("action", "adjust_duration")
    if action == "check_out" and "duration_minutes" not in data:
        out_at = data.get("checked_out_at") or now
        if out_at <= row.checked_in_at:
            out_at = row.checked_in_at + timedelta(minutes=60)
        mins = max(5, min(360, int((out_at - row.checked_in_at).total_seconds() // 60)))
        row.checked_out_at = row.checked_in_at + timedelta(minutes=mins)
        row.duration_minutes = mins
    else:
        mins = data.get("duration_minutes")
        if not mins:
            raise ValidationError({"duration_minutes": "Specify the time spent in minutes (5–360)."})
        row.duration_minutes = int(mins)
        row.checked_out_at = row.checked_in_at + timedelta(minutes=int(mins))

    row.auto_closed = False
    row.check_out_source = "manual"
    row.save(
        update_fields=[
            "checked_out_at",
            "duration_minutes",
            "auto_closed",
            "check_out_source",
            "updated_at",
        ]
    )
    return month_attendance(user, target_date.year, target_date.month)
