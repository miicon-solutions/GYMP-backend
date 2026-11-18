from datetime import datetime, time
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import (
    Avg,
    DecimalField,
    ExpressionWrapper,
    F,
    Max,
    Min,
    Q,
    Sum,
)
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.api import Conflict
from fitness.services import get_profile
from workouts.calculators import epley_1rm, quantize, timeframe_start, to_lbs
from workouts.models import Exercise, Routine, WorkoutSession, WorkoutSet

VOLUME = ExpressionWrapper(
    F("weight_lbs") * F("reps"), output_field=DecimalField(max_digits=14, decimal_places=2)
)


def accessible_exercises(user):
    return Exercise.objects.filter(Q(created_by__isnull=True) | Q(created_by=user))


def accessible_routines(user):
    return Routine.objects.filter(Q(created_by__isnull=True) | Q(created_by=user))


def counted_sets(user):
    """Sets that count toward PRs, volume, and analytics: no warmups, no cancelled sessions."""
    return (
        WorkoutSet.objects.filter(user=user)
        .exclude(set_type="warmup")
        .exclude(workout_session__status="cancelled")
    )


def session_queryset(user):
    return WorkoutSession.objects.filter(user=user).select_related("routine")


def locked_session(user, pk):
    return get_object_or_404(WorkoutSession.objects.select_for_update(), pk=pk, user=user)


def require_active(session):
    if session.status != "in_progress":
        raise Conflict("This workout is no longer in progress.")


@transaction.atomic
def start_session(user, data):
    routine = data.get("routine")
    title = data.get("title") or (routine.title if routine else "Quick Workout")
    if WorkoutSession.objects.filter(user=user, status="in_progress").exists():
        raise Conflict("Finish or cancel your active workout first.")
    try:
        with transaction.atomic():
            return WorkoutSession.objects.create(
                user=user, routine=routine, title=title, notes=data.get("notes", "")
            )
    except IntegrityError as exc:  # Concurrent start; the partial unique index decides.
        raise Conflict("Finish or cancel your active workout first.") from exc


def refresh_session_totals(session):
    totals = session.sets.exclude(set_type="warmup").aggregate(volume=Sum(VOLUME), rpe=Avg("rpe"))
    session.total_volume_lbs = quantize(totals["volume"] or 0)
    session.rpe_average = quantize(totals["rpe"], "0.1") if totals["rpe"] is not None else None
    session.save(update_fields=["total_volume_lbs", "rpe_average", "updated_at"])


def refresh_prs(session, exercise_id):
    """Flag at most one PR set per exercise: the session's best 1RM if it beats prior history.

    History is every counted set performed before this session started; with no history the
    first performance is a baseline rather than a PR. Live logging and completion share this
    rule, so the flag a member sees mid-workout is the flag that is kept.
    """
    prior = (
        counted_sets(session.user)
        .filter(exercise_id=exercise_id, performed_at__lt=session.start_time)
        .exclude(workout_session=session)
        .aggregate(best=Max("calculated_1rm"))["best"]
    )
    rows = session.sets.filter(exercise_id=exercise_id)
    best = rows.exclude(set_type="warmup").order_by("-calculated_1rm", "performed_at").first()
    pr_id = best.pk if best and prior is not None and best.calculated_1rm > prior else None
    rows.exclude(pk=pr_id).filter(is_pr=True).update(is_pr=False)
    if pr_id:
        rows.filter(pk=pr_id).update(is_pr=True)
    return prior


@transaction.atomic
def log_set(user, session_id, data):
    session = locked_session(user, session_id)
    require_active(session)
    exercise = data["exercise"]
    unit = data.get("weight_unit") or get_profile(user).weight_unit
    set_number = data.get("set_number")
    if set_number is None:
        last = session.sets.filter(exercise=exercise).aggregate(n=Max("set_number"))["n"]
        set_number = (last or 0) + 1
    elif session.sets.filter(exercise=exercise, set_number=set_number).exists():
        raise ValidationError({"set_number": "This set number is already logged."})
    weight_lbs = to_lbs(data["weight"], unit)
    row = WorkoutSet.objects.create(
        workout_session=session,
        user=user,
        exercise=exercise,
        set_number=set_number,
        set_type=data.get("set_type", "working"),
        weight=data["weight"],
        weight_unit=unit,
        weight_lbs=weight_lbs,
        reps=data["reps"],
        rpe=data.get("rpe"),
        calculated_1rm=epley_1rm(weight_lbs, data["reps"]),
    )
    previous_best = refresh_prs(session, exercise.pk)
    refresh_session_totals(session)
    row.refresh_from_db()
    return session, row, previous_best


@transaction.atomic
def delete_set(user, session_id, set_id):
    session = locked_session(user, session_id)
    require_active(session)
    row = get_object_or_404(session.sets, pk=set_id)
    exercise_id = row.exercise_id
    row.delete()
    refresh_prs(session, exercise_id)
    refresh_session_totals(session)
    return session


@transaction.atomic
def complete_session(user, session_id, data):
    session = locked_session(user, session_id)
    require_active(session)
    for exercise_id in session.sets.values_list("exercise_id", flat=True).distinct():
        refresh_prs(session, exercise_id)
    refresh_session_totals(session)
    session.status = "completed"
    session.end_time = max(timezone.now(), session.start_time)
    if "notes" in data:
        session.notes = data["notes"]
    session.save(update_fields=["status", "end_time", "notes", "updated_at"])
    return session


@transaction.atomic
def cancel_session(user, session_id):
    session = locked_session(user, session_id)
    require_active(session)
    session.status = "cancelled"
    session.end_time = max(timezone.now(), session.start_time)
    session.save(update_fields=["status", "end_time", "updated_at"])
    session.sets.filter(is_pr=True).update(is_pr=False)
    return session


def _day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _set_brief(row):
    if not row:
        return None
    return {
        "value": row.calculated_1rm,
        "weight": row.weight_lbs,
        "reps": row.reps,
        "date": timezone.localdate(row.performed_at),
    }


def muscle_split(exercise, total_volume):
    distribution = exercise.muscle_distribution or {
        exercise.target_vector or exercise.get_muscle_group_display(): 100
    }
    distribution = {muscle: Decimal(str(share)) for muscle, share in distribution.items()}
    share_total = sum(distribution.values()) or 1
    return [
        {
            "muscle": muscle,
            "percentage": quantize(share * 100 / share_total, "0.1"),
            "volume_lbs": quantize(total_volume * share / share_total),
        }
        for muscle, share in sorted(distribution.items(), key=lambda item: -item[1])
    ]


def exercise_analytics(user, exercise_id, timeframe):
    exercise = get_object_or_404(accessible_exercises(user), pk=exercise_id)
    base = counted_sets(user).filter(exercise=exercise)
    today = timezone.localdate()
    first = base.aggregate(first=Min("performed_at"))["first"]
    start = timeframe_start(timeframe, today, timezone.localdate(first) if first else None)
    rows = base.filter(performed_at__gte=_day_start(start)).order_by("performed_at")
    days, sessions, total_volume = {}, set(), 0
    for row in rows.only(
        "performed_at", "weight_lbs", "reps", "calculated_1rm", "workout_session_id"
    ):
        day = timezone.localdate(row.performed_at)
        volume = row.weight_lbs * row.reps
        total_volume += volume
        sessions.add(row.workout_session_id)
        point = days.setdefault(day, {"date": day, "volume_load": 0, "estimated_1rm": -1})
        point["volume_load"] += volume
        if row.calculated_1rm > point["estimated_1rm"]:
            point.update(
                estimated_1rm=row.calculated_1rm, actual_weight=row.weight_lbs, reps=row.reps
            )
    weeks = max(1, ((today - start).days + 1) / 7)
    return {
        "exercise": exercise,
        "timeframe": timeframe,
        "unit": "lbs",
        "timeframe_range": {"start_date": start, "end_date": today},
        "chart_data": list(days.values()),
        "lifetime_pr": {
            "estimated_1rm": _set_brief(base.order_by("-calculated_1rm", "performed_at").first()),
            "max_weight": _set_brief(base.order_by("-weight_lbs", "-reps", "performed_at").first()),
        },
        "total_volume_lbs": quantize(total_volume),
        "session_count": len(sessions),
        "frequency_per_week": quantize(len(sessions) / weeks),
        "volume_by_muscle_group": muscle_split(exercise, total_volume),
    }
