from django.db import transaction
from django.db.models import Case, IntegerField, Prefetch, Value, When
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from accounts.models import User
from schedules.models import ScheduledDay, SplitPlannerCycle
from workouts.models import SPLIT_CATEGORIES
from workouts.services import accessible_routines

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
        Prefetch("days", ScheduledDay.objects.select_related("assigned_routine"))
    )


def active_cycle(user, lock=False):
    rows = SplitPlannerCycle.objects.filter(user=user, is_active=True)
    cycle = (
        rows.select_for_update() if lock else cycle_queryset(user).filter(is_active=True)
    ).first()
    if not cycle:
        raise NotFound("No active split cycle. Create one first.")
    return cycle


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
    }


@transaction.atomic
def create_cycle(user, data):
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
    return cycle


@transaction.atomic
def update_cycle(user, data):
    cycle = active_cycle(user, lock=True)
    for field, value in data.items():
        setattr(cycle, field, value)
    cycle.save()
    return cycle


def _locked_day(cycle, day_index):
    if day_index >= cycle.cycle_length_days:
        raise NotFound("That day is outside the active cycle.")
    return cycle.days.select_for_update().get(day_index=day_index)


@transaction.atomic
def update_day(user, day_index, data):
    cycle = active_cycle(user, lock=True)
    day = _locked_day(cycle, day_index)
    swap_with = data.pop("swap_with_day_index", None)
    fields = ["label", "assigned_routine", "is_rest_day", "target_focus_tags"]
    if swap_with is not None:
        other = _locked_day(cycle, swap_with)
        for field in fields:
            first, second = getattr(day, field), getattr(other, field)
            setattr(day, field, second)
            setattr(other, field, first)
        for row in (day, other):
            row.save(update_fields=[*fields, "updated_at"])
    else:
        for field, value in day_values(data, day).items():
            setattr(day, field, value)
        day.save(update_fields=[*fields, "updated_at"])
    return cycle


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
        ["label", "assigned_routine", "is_rest_day", "target_focus_tags", "updated_at"],
    )
    return cycle


def today_schedule(cycle, day=None):
    day = day or timezone.localdate()
    index = cycle.day_index_for(day)
    scheduled = next((d for d in cycle.days.all() if d.day_index == index), None)
    return {"date": day, "day_index": index, "day": scheduled}
