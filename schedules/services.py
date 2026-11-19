from datetime import timedelta

from django.db import transaction
from django.db.models import Case, IntegerField, Prefetch, Value, When
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from accounts.models import User
from operations.models import Holiday, WeekdayHours
from operations.services import DAY_LABELS, DHAKA
from schedules.models import ScheduledDay, SplitPlannerCycle
from workouts.models import SPLIT_CATEGORIES, Routine, RoutineExercise
from workouts.services import accessible_routines, effective_exercise_tracking_type

REST = None
# Seven-day patterns; other cycle lengths repeat or truncate the pattern.
TEMPLATES = {
    "ppl": ["push", "pull", "legs", REST, "push", "pull", "legs"],  # PPLRPPL
    "upper_lower": ["upper", "lower", REST, "upper", "lower", REST, REST],
    "full_body": ["full_body", REST, "full_body", REST, "full_body", REST, REST],
    "ppl_upper_lower": ["push", "pull", "legs", REST, "upper", "lower", REST],
}
CATEGORY_LABELS = dict(SPLIT_CATEGORIES)
REST_DEFAULTS = {"label": "Rest", "target_focus_tags": ["recovery"]}


def cycle_queryset(user):
    return SplitPlannerCycle.objects.filter(user=user).prefetch_related(
        Prefetch(
            "days",
            ScheduledDay.objects.select_related("assigned_routine").prefetch_related(
                Prefetch(
                    "assigned_routine__items",
                    RoutineExercise.objects.select_related("exercise").order_by("order"),
                )
            ),
        )
    )


def active_cycle(user, lock=False):
    rows = SplitPlannerCycle.objects.filter(user=user, is_active=True)
    cycle = (
        rows.select_for_update() if lock else cycle_queryset(user).filter(is_active=True)
    ).first()
    if not cycle:
        cycle = create_cycle(
            user,
            {
                "name": "7-Day Progressive Split Cycle",
                "mesocycle_phase": "Hypertrophy & Strength Phase",
                "cycle_length_days": 7,
            },
        )
        if lock:
            cycle = SplitPlannerCycle.objects.select_for_update().get(pk=cycle.pk)
        else:
            cycle = cycle_queryset(user).get(pk=cycle.pk)
    return cycle


def get_day_closure_info(cycle: SplitPlannerCycle, day_index: int) -> dict:
    """Return gym closed-day status and note for a cycle day (Suggestion 8)."""
    today_dhaka = timezone.now().astimezone(DHAKA).date()
    monday = today_dhaka - timedelta(days=today_dhaka.weekday())
    starts_on = cycle.starts_on or monday
    # Map day_index 0..6 onto the current week starting from starts_on weekday
    weekday = ((starts_on.weekday() + day_index) % 7) + 1  # 1=Mon .. 5=Fri .. 7=Sun
    offset_from_monday = weekday - 1
    target_date = monday + timedelta(days=offset_from_monday)

    closed_weekdays = set(
        WeekdayHours.objects.filter(is_open=False).values_list("weekday", flat=True)
    )
    if not WeekdayHours.objects.exists():
        closed_weekdays = {5}

    holiday = Holiday.objects.filter(date=target_date).first()
    is_weekly_closed = weekday in closed_weekdays
    is_closed = bool(holiday or is_weekly_closed)
    if holiday:
        reason = holiday.name or "Gym Holiday"
    elif is_weekly_closed:
        reason = f"{DAY_LABELS[weekday - 1]} Closed"
    else:
        reason = ""

    return {
        "weekday": weekday,
        "date": target_date,
        "is_gym_closed": is_closed,
        "closed_reason": reason,
        "closed_note": (
            "Gym is closed today. You can still plan a home workout." if is_closed else ""
        ),
        "closed_note_bn": (
            "আজ জিম বন্ধ। আপনি তবুও বাসায় ওয়ার্কআউট করার পরিকল্পনা করতে পারেন।"
            if is_closed
            else ""
        ),
    }


def day_values(data, current=None):
    """Normalise a day assignment: rest days never carry a routine."""
    routine = data.get("assigned_routine", current.assigned_routine if current else None)
    is_rest = data.get("is_rest_day", routine is None)
    if is_rest:
        routine = None
    if routine is not None:
        default_label = routine.title[:80]
        default_tags = [routine.focus_tag, routine.split_category]
    elif is_rest:
        default_label, default_tags = REST_DEFAULTS["label"], REST_DEFAULTS["target_focus_tags"]
    else:
        default_label, default_tags = "Training", []
    return {
        "assigned_routine": routine,
        "is_rest_day": is_rest,
        "label": data.get("label") or default_label,
        "target_focus_tags": data.get("target_focus_tags", default_tags),
        "custom_exercises": [] if is_rest else data.get("custom_exercises", current.custom_exercises if current else []),
    }


def _build_custom_day_routine(user, day: ScheduledDay, label: str, custom_items: list, split_category: str = "other", focus_tag: str = "hypertrophy") -> tuple[Routine, list[dict]]:
    """Create or update a user-owned custom Routine for a specific day in the Routine Planner (Suggestion 7)."""
    routine_title = (label or f"Custom Day {day.day_index + 1}").strip()[:110]
    existing = day.assigned_routine
    if existing and not existing.is_predefined and existing.created_by_id == user.id:
        routine = existing
        routine.title = routine_title
        routine.split_category = split_category or routine.split_category
        routine.focus_tag = focus_tag or routine.focus_tag
        routine.save(update_fields=["title", "split_category", "focus_tag", "updated_at"])
        routine.items.all().delete()
    else:
        routine = Routine.objects.create(
            title=routine_title,
            description=f"Custom day routine for Day {day.day_index + 1}",
            is_predefined=False,
            created_by=user,
            estimated_duration_minutes=max(15, len(custom_items) * 12),
            focus_tag=focus_tag or "hypertrophy",
            split_category=split_category or "other",
        )

    serialized_custom = []
    bulk_rows = []
    for idx, item in enumerate(custom_items, start=1):
        ex = item.get("exercise")
        if not ex:
            continue
        track = effective_exercise_tracking_type(ex)
        sets = int(item.get("target_sets") or 3)
        dur_sec = item.get("target_duration_seconds")
        dist_km = item.get("target_distance_km")
        reps_range = (item.get("target_reps_range") or "").strip()
        if not reps_range:
            if track == "cardio":
                mins = (int(dur_sec) // 60) if dur_sec else 20
                reps_range = f"{mins}m" + (f" • {dist_km}km" if dist_km else "")
            elif track == "time":
                secs = int(dur_sec or 60)
                reps_range = f"{secs // 60}m {secs % 60}s" if secs >= 60 else f"{secs}s"
            else:
                reps_range = "8-12"
        rest_sec = int(item.get("rest_protocol_seconds") or 90)
        notes = (item.get("notes") or "").strip()

        bulk_rows.append(
            RoutineExercise(
                routine=routine,
                exercise=ex,
                order=idx,
                target_sets=sets,
                target_reps_range=reps_range[:32],
                target_duration_seconds=dur_sec,
                target_distance_km=dist_km,
                rest_protocol_seconds=rest_sec,
                notes=notes,
            )
        )
        serialized_custom.append(
            {
                "exercise_id": str(ex.id),
                "exercise_name": ex.name,
                "muscle_group": ex.muscle_group,
                "category": ex.category,
                "tracking_type": track,
                "target_sets": sets,
                "target_reps_range": reps_range[:32],
                "target_duration_seconds": dur_sec,
                "target_distance_km": float(dist_km) if dist_km is not None else None,
                "rest_protocol_seconds": rest_sec,
                "notes": notes,
            }
        )
    if bulk_rows:
        RoutineExercise.objects.bulk_create(bulk_rows)
    return routine, serialized_custom


@transaction.atomic
def create_cycle(user, data):
    data = dict(data)
    User.objects.select_for_update().get(pk=user.pk)  # Serialise cycle swaps per member.
    SplitPlannerCycle.objects.filter(user=user, is_active=True).update(
        is_active=False, updated_at=timezone.now()
    )
    days = {day["day_index"]: day for day in data.pop("days", [])}
    cycle = SplitPlannerCycle.objects.create(user=user, is_active=True, **data)
    ScheduledDay.objects.bulk_create(
        ScheduledDay(cycle=cycle, day_index=index, **day_values(days.get(index, {})))
        for index in range(cycle.cycle_length_days)
    )
    return cycle_queryset(user).get(pk=cycle.pk)


@transaction.atomic
def update_cycle(user, data):
    cycle = active_cycle(user, lock=True)
    for field, value in data.items():
        setattr(cycle, field, value)
    cycle.save()
    return cycle_queryset(user).get(pk=cycle.pk)


def _locked_day(cycle, day_index):
    if day_index >= cycle.cycle_length_days:
        raise NotFound("That day is outside the active cycle.")
    return cycle.days.select_for_update().get(day_index=day_index)


@transaction.atomic
def update_day(user, day_index, data):
    data = dict(data)
    cycle = active_cycle(user, lock=True)
    day = _locked_day(cycle, day_index)
    swap_with = data.pop("swap_with_day_index", None)
    custom_items = data.pop("custom_exercises", None)
    split_cat = data.pop("split_category", "other")
    focus_tag = data.pop("focus_tag", "hypertrophy")

    fields = ["label", "assigned_routine", "is_rest_day", "target_focus_tags", "custom_exercises"]
    if swap_with is not None:
        other = _locked_day(cycle, swap_with)
        for field in fields:
            first, second = getattr(day, field), getattr(other, field)
            setattr(day, field, second)
            setattr(other, field, first)
        for row in (day, other):
            row.save(update_fields=[*fields, "updated_at"])
    else:
        if custom_items is not None and not data.get("is_rest_day", False):
            label = data.get("label") or day.label or f"Custom Day {day_index + 1}"
            if label == "Rest":
                label = f"Custom Day {day_index + 1}"
            routine, serialized_custom = _build_custom_day_routine(
                user,
                day,
                label,
                custom_items,
                split_category=split_cat,
                focus_tag=focus_tag,
            )
            data["assigned_routine"] = routine
            data["is_rest_day"] = False
            data["label"] = label
            data["custom_exercises"] = serialized_custom
        for field, value in day_values(data, day).items():
            setattr(day, field, value)
        day.save(update_fields=[*fields, "updated_at"])
    return cycle_queryset(user).get(pk=cycle.pk)


@transaction.atomic
def auto_populate(user, template, prefer_custom=True):
    cycle = active_cycle(user, lock=True)
    pattern = TEMPLATES[template]
    slots = [pattern[i % len(pattern)] for i in range(cycle.cycle_length_days)]
    needed = {slot for slot in slots if slot is not REST}
    custom_rank = Case(
        When(created_by__isnull=False, then=Value(0 if prefer_custom else 1)),
        default=Value(1 if prefer_custom else 0),
        output_field=IntegerField(),
    )
    candidates = {}
    for routine in (
        accessible_routines(user)
        .filter(split_category__in=needed)
        .order_by(custom_rank, "created_at", "title")
    ):
        candidates.setdefault(routine.split_category, []).append(routine)
    missing = sorted(needed - candidates.keys())
    if missing:
        names = ", ".join(CATEGORY_LABELS[m] for m in missing)
        raise ValidationError({"template": f"No routine available for: {names}."})
    used, now = {}, timezone.now()
    days = {d.day_index: d for d in cycle.days.select_for_update()}
    for index, slot in enumerate(slots):
        if slot is REST:
            values = day_values({"is_rest_day": True})
        else:
            options = candidates[slot]
            routine = options[used.get(slot, 0) % len(options)]
            used[slot] = used.get(slot, 0) + 1
            values = day_values(
                {
                    "assigned_routine": routine,
                    "is_rest_day": False,
                    "label": f"{CATEGORY_LABELS[slot]} {routine.get_focus_tag_display()}",
                }
            )
        for field, value in values.items():
            setattr(days[index], field, value)
        days[index].updated_at = now
    ScheduledDay.objects.bulk_update(
        days.values(),
        ["label", "assigned_routine", "is_rest_day", "target_focus_tags", "custom_exercises", "updated_at"],
    )
    return cycle_queryset(user).get(pk=cycle.pk)


def today_schedule(cycle, day=None):
    day = day or timezone.localdate()
    index = cycle.day_index_for(day)
    scheduled = next((d for d in cycle.days.all() if d.day_index == index), None)
    return {"date": day, "day_index": index, "day": scheduled}
