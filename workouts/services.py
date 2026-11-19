import uuid
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
from fitness.services import get_effective_body_data, get_profile
from workouts.calculators import epley_1rm, from_lbs, quantize, timeframe_start, to_lbs
from workouts.models import Exercise, Routine, WorkoutSession, WorkoutSet

VOLUME = ExpressionWrapper(
    F("weight_lbs") * F("reps"), output_field=DecimalField(max_digits=14, decimal_places=2)
)

CARDIO_KEYWORDS = (
    "running",
    "treadmill",
    "cycling",
    "stationary bike",
    "bike",
    "rowing",
    "elliptical",
    "sprint",
    "jogging",
    "stairmaster",
    "cardio",
)
TIMED_KEYWORDS = (
    "plank",
    "wall sit",
    "dead hang",
    "l-sit",
    "hold",
    "carry",
    "farmer",
    "jump rope",
    "battle rope",
    "hollow body",
)


def infer_tracking_type(name: str, category: str = "", explicit: str | None = None) -> str:
    n = (name or "").lower()
    cat = (category or "").lower()
    if explicit in ("time", "cardio"):
        return explicit
    if cat == "cardio" or any(k in n for k in CARDIO_KEYWORDS):
        return "cardio"
    if any(k in n for k in TIMED_KEYWORDS):
        return "time"
    return explicit if explicit in ("reps", "time", "cardio") else "reps"


def effective_exercise_tracking_type(exercise: Exercise) -> str:
    if exercise.tracking_type in ("time", "cardio"):
        return exercise.tracking_type
    return infer_tracking_type(exercise.name, exercise.category, exercise.tracking_type)


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


def calculate_session_calories(session: WorkoutSession) -> int:
    """Estimate calories burned for a workout session using synced body data (Suggestion 4 & 6)."""
    body = get_effective_body_data(session.user)
    weight_kg = float(body["weight_kg"] or 70.0)
    sets = list(session.sets.select_related("exercise").all())
    if not sets:
        if session.end_time and session.start_time:
            mins = max(1.0, (session.end_time - session.start_time).total_seconds() / 60.0)
            return max(10, int(round((4.5 * 3.5 * weight_kg / 200.0) * mins)))
        return 0

    total_cals = 0.0
    for s in sets:
        track = effective_exercise_tracking_type(s.exercise)
        dur_sec = int(s.duration_seconds or 0)
        dist_km = float(s.distance_km or 0.0)
        if track == "cardio" or dist_km > 0:
            if dist_km > 0:
                total_cals += dist_km * weight_kg * 0.95
            elif dur_sec > 0:
                mins = dur_sec / 60.0
                total_cals += (8.0 * 3.5 * weight_kg / 200.0) * mins
            else:
                total_cals += (7.0 * 3.5 * weight_kg / 200.0) * 5.0
        elif track == "time" or (dur_sec > 0 and float(s.weight_lbs or 0) == 0):
            mins = max(0.5, dur_sec / 60.0)
            total_cals += (4.5 * 3.5 * weight_kg / 200.0) * (mins + 1.0)
        else:
            w_kg = float(from_lbs(s.weight_lbs, "kg"))
            rpe_mult = 1.15 if (s.rpe and float(s.rpe) >= 8.0) else 1.0
            base_set_cals = (5.0 * 3.5 * weight_kg / 200.0) * 2.2 * rpe_mult
            work_cals = w_kg * int(s.reps or 1) * 0.018
            total_cals += base_set_cals + work_cals

    return max(15, int(round(total_cals)))


def refresh_session_totals(session):
    totals = session.sets.exclude(set_type="warmup").aggregate(volume=Sum(VOLUME), rpe=Avg("rpe"))
    session.total_volume_lbs = quantize(totals["volume"] or 0)
    session.rpe_average = quantize(totals["rpe"], "0.1") if totals["rpe"] is not None else None
    session.estimated_calories_burned = calculate_session_calories(session)
    session.save(
        update_fields=[
            "total_volume_lbs",
            "rpe_average",
            "estimated_calories_burned",
            "updated_at",
        ]
    )


def refresh_prs(session, exercise_id):
    """Flag at most one PR set per exercise: the session's best 1RM/performance if it beats prior history."""
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
    track_type = effective_exercise_tracking_type(exercise)
    unit = data.get("weight_unit") or get_profile(user).weight_unit
    set_number = data.get("set_number")
    if set_number is None:
        last = session.sets.filter(exercise=exercise).aggregate(n=Max("set_number"))["n"]
        set_number = (last or 0) + 1
    elif session.sets.filter(exercise=exercise, set_number=set_number).exists():
        raise ValidationError({"set_number": "This set number is already logged."})

    weight_val = data.get("weight") if data.get("weight") is not None else Decimal("0.00")
    reps_val = int(data.get("reps") or 1)
    duration_sec = data.get("duration_seconds")
    distance_km = data.get("distance_km")

    weight_lbs = to_lbs(weight_val, unit)
    if track_type == "cardio" or (distance_km is not None and Decimal(str(distance_km)) > 0):
        d_km = Decimal(str(distance_km or 0))
        d_sec = Decimal(str(duration_sec or 0))
        calc_score = quantize(d_km * Decimal("100") + (d_sec / Decimal("60")))
    elif track_type == "time" or (duration_sec is not None and duration_sec > 0 and weight_val == 0):
        calc_score = quantize(Decimal(str(duration_sec or 0)))
    else:
        calc_score = epley_1rm(weight_lbs, reps_val)

    row = WorkoutSet.objects.create(
        workout_session=session,
        user=user,
        exercise=exercise,
        set_number=set_number,
        set_type=data.get("set_type", "working"),
        weight=weight_val,
        weight_unit=unit,
        weight_lbs=weight_lbs,
        reps=max(1, reps_val),
        duration_seconds=duration_sec,
        distance_km=distance_km,
        rpe=data.get("rpe"),
        calculated_1rm=calc_score,
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
    session.status = "completed"
    session.end_time = max(timezone.now(), session.start_time)
    if "notes" in data:
        session.notes = data["notes"]
    session.save(update_fields=["status", "end_time", "notes", "updated_at"])
    refresh_session_totals(session)
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


def _status_tag(curr: float, base: float, tol: float = 0.01) -> str:
    if curr > base + tol:
        return "improved"
    if curr < base - tol:
        return "dropped"
    return "same"


def _aggregate_session_exercise_metrics(session: WorkoutSession) -> dict:
    sets = [s for s in session.sets.select_related("exercise").all() if s.set_type != "warmup"]
    if not sets:
        sets = list(session.sets.select_related("exercise").all())
    by_ex: dict[str, dict] = {}
    total_vol_kg = 0.0
    total_sets = 0
    total_reps = 0
    total_dur_sec = 0
    total_dist_km = 0.0

    for s in sets:
        ex = s.exercise
        eid = str(ex.id)
        track = effective_exercise_tracking_type(ex)
        w_kg = float(from_lbs(s.weight_lbs, "kg"))
        reps = int(s.reps or 0)
        dur = int(s.duration_seconds or 0)
        dist = float(s.distance_km or 0.0)
        vol_kg = w_kg * reps

        total_vol_kg += vol_kg
        total_sets += 1
        total_reps += reps
        total_dur_sec += dur
        total_dist_km += dist

        entry = by_ex.setdefault(
            eid,
            {
                "exercise_id": eid,
                "exercise_name": ex.name,
                "tracking_type": track,
                "max_weight_kg": 0.0,
                "max_reps": 0,
                "total_reps": 0,
                "sets": 0,
                "volume_kg": 0.0,
                "duration_seconds": 0,
                "distance_km": 0.0,
            },
        )
        entry["sets"] += 1
        entry["total_reps"] += reps
        entry["max_reps"] = max(entry["max_reps"], reps)
        entry["max_weight_kg"] = max(entry["max_weight_kg"], round(w_kg, 2))
        entry["volume_kg"] = round(entry["volume_kg"] + vol_kg, 2)
        entry["duration_seconds"] += dur
        entry["distance_km"] = round(entry["distance_km"] + dist, 2)

    return {
        "volume_kg": round(total_vol_kg, 2),
        "sets": total_sets,
        "reps": total_reps,
        "duration_seconds": total_dur_sec,
        "distance_km": round(total_dist_km, 2),
        "by_exercise": by_ex,
    }


def _build_mode_comparison(curr_agg: dict, past_aggs: list[tuple[WorkoutSession, dict]], mode: str) -> dict:
    if not past_aggs:
        return {
            "mode": mode,
            "has_baseline": False,
            "baseline_date": None,
            "sessions_compared": 0,
            "volume_kg": {"current": curr_agg["volume_kg"], "baseline": 0.0, "diff": 0.0, "status": "same"},
            "sets": {"current": curr_agg["sets"], "baseline": 0, "diff": 0, "status": "same"},
            "reps": {"current": curr_agg["reps"], "baseline": 0, "diff": 0, "status": "same"},
            "exercises": [
                {
                    "exercise_id": ex["exercise_id"],
                    "exercise_name": ex["exercise_name"],
                    "tracking_type": ex["tracking_type"],
                    "weight_kg": {"current": ex["max_weight_kg"], "baseline": 0.0, "diff": 0.0, "status": "new"},
                    "reps": {"current": ex["max_reps"], "baseline": 0, "diff": 0, "status": "new"},
                    "sets": {"current": ex["sets"], "baseline": 0, "diff": 0, "status": "new"},
                    "duration_seconds": {"current": ex["duration_seconds"], "baseline": 0, "diff": 0, "status": "new"},
                    "distance_km": {"current": ex["distance_km"], "baseline": 0.0, "diff": 0.0, "status": "new"},
                    "overall_status": "new",
                }
                for ex in curr_agg["by_exercise"].values()
            ],
        }

    if mode == "last_session":
        base_sess, base_agg = past_aggs[0]
        base_date = timezone.localdate(base_sess.start_time)
        base_vol = base_agg["volume_kg"]
        base_sets = base_agg["sets"]
        base_reps = base_agg["reps"]
    elif mode == "personal_best":
        base_date = timezone.localdate(past_aggs[0][0].start_time)
        base_vol = max(a["volume_kg"] for _, a in past_aggs)
        base_sets = max(a["sets"] for _, a in past_aggs)
        base_reps = max(a["reps"] for _, a in past_aggs)
    else:  # average
        base_date = timezone.localdate(past_aggs[0][0].start_time)
        n = len(past_aggs)
        base_vol = round(sum(a["volume_kg"] for _, a in past_aggs) / n, 2)
        base_sets = round(sum(a["sets"] for _, a in past_aggs) / n, 1)
        base_reps = round(sum(a["reps"] for _, a in past_aggs) / n, 1)

    ex_comparisons = []
    for eid, curr_ex in curr_agg["by_exercise"].items():
        matching_past = [a["by_exercise"][eid] for _, a in past_aggs if eid in a["by_exercise"]]
        if not matching_past:
            ex_comparisons.append(
                {
                    "exercise_id": eid,
                    "exercise_name": curr_ex["exercise_name"],
                    "tracking_type": curr_ex["tracking_type"],
                    "weight_kg": {"current": curr_ex["max_weight_kg"], "baseline": 0.0, "diff": 0.0, "status": "new"},
                    "reps": {"current": curr_ex["max_reps"], "baseline": 0, "diff": 0, "status": "new"},
                    "sets": {"current": curr_ex["sets"], "baseline": 0, "diff": 0, "status": "new"},
                    "duration_seconds": {"current": curr_ex["duration_seconds"], "baseline": 0, "diff": 0, "status": "new"},
                    "distance_km": {"current": curr_ex["distance_km"], "baseline": 0.0, "diff": 0.0, "status": "new"},
                    "overall_status": "new",
                }
            )
            continue

        if mode == "last_session":
            b_ex = matching_past[0]
            b_w = b_ex["max_weight_kg"]
            b_r = b_ex["max_reps"]
            b_s = b_ex["sets"]
            b_dur = b_ex["duration_seconds"]
            b_dist = b_ex["distance_km"]
        elif mode == "personal_best":
            b_w = max(x["max_weight_kg"] for x in matching_past)
            b_r = max(x["max_reps"] for x in matching_past)
            b_s = max(x["sets"] for x in matching_past)
            b_dur = max(x["duration_seconds"] for x in matching_past)
            b_dist = max(x["distance_km"] for x in matching_past)
        else:
            m = len(matching_past)
            b_w = round(sum(x["max_weight_kg"] for x in matching_past) / m, 2)
            b_r = round(sum(x["max_reps"] for x in matching_past) / m, 1)
            b_s = round(sum(x["sets"] for x in matching_past) / m, 1)
            b_dur = round(sum(x["duration_seconds"] for x in matching_past) / m)
            b_dist = round(sum(x["distance_km"] for x in matching_past) / m, 2)

        w_stat = _status_tag(curr_ex["max_weight_kg"], b_w)
        r_stat = _status_tag(curr_ex["max_reps"], b_r)
        s_stat = _status_tag(curr_ex["sets"], b_s)
        dur_stat = _status_tag(curr_ex["duration_seconds"], b_dur)
        dist_stat = _status_tag(curr_ex["distance_km"], b_dist)

        track = curr_ex["tracking_type"]
        if track == "cardio":
            overall = dist_stat if curr_ex["distance_km"] > 0 else dur_stat
        elif track == "time":
            overall = dur_stat
        else:
            if w_stat == "improved" or (w_stat == "same" and (r_stat == "improved" or s_stat == "improved")):
                overall = "improved"
            elif w_stat == "dropped" or (w_stat == "same" and r_stat == "dropped" and s_stat == "dropped"):
                overall = "dropped"
            else:
                overall = "same"

        ex_comparisons.append(
            {
                "exercise_id": eid,
                "exercise_name": curr_ex["exercise_name"],
                "tracking_type": track,
                "weight_kg": {
                    "current": curr_ex["max_weight_kg"],
                    "baseline": b_w,
                    "diff": round(curr_ex["max_weight_kg"] - b_w, 2),
                    "status": w_stat,
                },
                "reps": {
                    "current": curr_ex["max_reps"],
                    "baseline": b_r,
                    "diff": round(curr_ex["max_reps"] - b_r, 1),
                    "status": r_stat,
                },
                "sets": {
                    "current": curr_ex["sets"],
                    "baseline": b_s,
                    "diff": round(curr_ex["sets"] - b_s, 1),
                    "status": s_stat,
                },
                "duration_seconds": {
                    "current": curr_ex["duration_seconds"],
                    "baseline": b_dur,
                    "diff": int(curr_ex["duration_seconds"] - b_dur),
                    "status": dur_stat,
                },
                "distance_km": {
                    "current": curr_ex["distance_km"],
                    "baseline": b_dist,
                    "diff": round(curr_ex["distance_km"] - b_dist, 2),
                    "status": dist_stat,
                },
                "overall_status": overall,
            }
        )

    return {
        "mode": mode,
        "has_baseline": True,
        "baseline_date": base_date,
        "sessions_compared": len(past_aggs),
        "volume_kg": {
            "current": curr_agg["volume_kg"],
            "baseline": base_vol,
            "diff": round(curr_agg["volume_kg"] - base_vol, 2),
            "status": _status_tag(curr_agg["volume_kg"], base_vol),
        },
        "sets": {
            "current": curr_agg["sets"],
            "baseline": base_sets,
            "diff": round(curr_agg["sets"] - base_sets, 1),
            "status": _status_tag(curr_agg["sets"], base_sets),
        },
        "reps": {
            "current": curr_agg["reps"],
            "baseline": base_reps,
            "diff": round(curr_agg["reps"] - base_reps, 1),
            "status": _status_tag(curr_agg["reps"], base_reps),
        },
        "exercises": ex_comparisons,
    }


def build_session_summary(session: WorkoutSession) -> dict:
    """Build post-workout summary with estimated calories and past session comparisons (Suggestion 4)."""
    body = get_effective_body_data(session.user)
    cals = session.estimated_calories_burned or calculate_session_calories(session)
    curr_agg = _aggregate_session_exercise_metrics(session)

    past_qs = (
        WorkoutSession.objects.filter(
            user=session.user,
            status="completed",
            start_time__lt=session.start_time,
        )
        .exclude(pk=session.pk)
        .prefetch_related("sets__exercise")
        .order_by("-start_time")
    )
    if session.routine_id:
        same_routine = list(past_qs.filter(routine_id=session.routine_id)[:15])
        past_sessions = same_routine if same_routine else list(past_qs[:15])
    else:
        same_title = list(past_qs.filter(title__iexact=session.title)[:15])
        past_sessions = same_title if same_title else list(past_qs[:15])

    past_aggs = [(ps, _aggregate_session_exercise_metrics(ps)) for ps in past_sessions]

    return {
        "estimated_calories_burned": cals,
        "is_calorie_estimate": True,
        "body_weight_kg_used": body["weight_kg"],
        "has_body_data": body["has_body_data"],
        "default_comparison_mode": "last_session",
        "comparisons": {
            "last_session": _build_mode_comparison(curr_agg, past_aggs, "last_session"),
            "personal_best": _build_mode_comparison(curr_agg, past_aggs, "personal_best"),
            "average": _build_mode_comparison(curr_agg, past_aggs, "average"),
        },
    }


def _day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _set_brief(row):
    if not row:
        return None
    return {
        "value": row.calculated_1rm,
        "value_kg": from_lbs(row.calculated_1rm, "kg"),
        "weight": row.weight_lbs,
        "weight_kg": from_lbs(row.weight_lbs, "kg"),
        "reps": row.reps,
        "duration_seconds": row.duration_seconds,
        "distance_km": row.distance_km,
        "date": timezone.localdate(row.performed_at),
    }


def muscle_split(exercise, total_volume):
    distribution = exercise.muscle_distribution or {
        exercise.target_vector or exercise.get_muscle_group_display(): 100
    }
    distribution = {muscle: Decimal(str(share)) for muscle, share in distribution.items()}
    share_total = sum(distribution.values()) or 1
    total_vol_kg = from_lbs(total_volume, "kg")
    return [
        {
            "muscle": muscle,
            "percentage": quantize(share * 100 / share_total, "0.1"),
            "volume_lbs": quantize(total_volume * share / share_total),
            "volume_kg": quantize(total_vol_kg * share / share_total),
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
    days, sessions, total_volume = {}, set(), Decimal("0.00")
    for row in rows.only(
        "performed_at",
        "weight_lbs",
        "reps",
        "duration_seconds",
        "distance_km",
        "calculated_1rm",
        "workout_session_id",
    ):
        day = timezone.localdate(row.performed_at)
        volume = row.weight_lbs * row.reps
        total_volume += volume
        sessions.add(row.workout_session_id)
        point = days.setdefault(
            day,
            {
                "date": day,
                "volume_load": Decimal("0.00"),
                "volume_load_kg": Decimal("0.00"),
                "estimated_1rm": Decimal("-1.00"),
                "estimated_1rm_kg": Decimal("0.00"),
                "actual_weight": Decimal("0.00"),
                "actual_weight_kg": Decimal("0.00"),
                "reps": 0,
                "duration_seconds": 0,
                "distance_km": Decimal("0.00"),
            },
        )
        point["volume_load"] += volume
        point["volume_load_kg"] = from_lbs(point["volume_load"], "kg")
        point["duration_seconds"] += int(row.duration_seconds or 0)
        point["distance_km"] += Decimal(str(row.distance_km or 0))
        if row.calculated_1rm > point["estimated_1rm"]:
            point.update(
                estimated_1rm=row.calculated_1rm,
                estimated_1rm_kg=from_lbs(row.calculated_1rm, "kg"),
                actual_weight=row.weight_lbs,
                actual_weight_kg=from_lbs(row.weight_lbs, "kg"),
                reps=row.reps,
            )
    weeks = max(1, ((today - start).days + 1) / 7)
    return {
        "exercise": exercise,
        "timeframe": timeframe,
        "unit": "kg",
        "timeframe_range": {"start_date": start, "end_date": today},
        "chart_data": list(days.values()),
        "lifetime_pr": {
            "estimated_1rm": _set_brief(base.order_by("-calculated_1rm", "performed_at").first()),
            "max_weight": _set_brief(base.order_by("-weight_lbs", "-reps", "performed_at").first()),
        },
        "total_volume_lbs": quantize(total_volume),
        "total_volume_kg": from_lbs(total_volume, "kg"),
        "session_count": len(sessions),
        "frequency_per_week": quantize(len(sessions) / weeks),
        "volume_by_muscle_group": muscle_split(exercise, total_volume),
    }


def overall_analytics(user, timeframe):
    """Aggregate strength & volume analytics across ALL workouts (Suggestion 3)."""
    base = counted_sets(user).select_related("exercise")
    today = timezone.localdate()
    first = base.aggregate(first=Min("performed_at"))["first"]
    start = timeframe_start(timeframe, today, timezone.localdate(first) if first else None)
    rows = base.filter(performed_at__gte=_day_start(start)).order_by("performed_at")

    days, sessions, total_volume = {}, set(), Decimal("0.00")
    muscle_volumes_lbs: dict[str, Decimal] = {}

    for row in rows:
        day = timezone.localdate(row.performed_at)
        volume = row.weight_lbs * row.reps
        total_volume += volume
        sessions.add(row.workout_session_id)

        # Accumulate muscle group volume across all exercises
        ex = row.exercise
        dist = ex.muscle_distribution or {ex.target_vector or ex.get_muscle_group_display(): 100}
        dist_dec = {m: Decimal(str(s)) for m, s in dist.items()}
        share_sum = sum(dist_dec.values()) or Decimal("1")
        for m_name, share in dist_dec.items():
            muscle_volumes_lbs[m_name] = muscle_volumes_lbs.get(m_name, Decimal("0")) + (
                volume * share / share_sum
            )

        point = days.setdefault(
            day,
            {
                "date": day,
                "volume_load": Decimal("0.00"),
                "volume_load_kg": Decimal("0.00"),
                "estimated_1rm": Decimal("-1.00"),
                "estimated_1rm_kg": Decimal("0.00"),
                "actual_weight": Decimal("0.00"),
                "actual_weight_kg": Decimal("0.00"),
                "reps": 0,
                "duration_seconds": 0,
                "distance_km": Decimal("0.00"),
            },
        )
        point["volume_load"] += volume
        point["volume_load_kg"] = from_lbs(point["volume_load"], "kg")
        point["reps"] += int(row.reps or 0)
        point["duration_seconds"] += int(row.duration_seconds or 0)
        point["distance_km"] += Decimal(str(row.distance_km or 0))
        if row.calculated_1rm > point["estimated_1rm"]:
            point.update(
                estimated_1rm=row.calculated_1rm,
                estimated_1rm_kg=from_lbs(row.calculated_1rm, "kg"),
                actual_weight=row.weight_lbs,
                actual_weight_kg=from_lbs(row.weight_lbs, "kg"),
            )

    total_m_vol = sum(muscle_volumes_lbs.values()) or Decimal("1")
    muscle_shares = [
        {
            "muscle": m,
            "percentage": quantize(v * 100 / total_m_vol, "0.1"),
            "volume_lbs": quantize(v),
            "volume_kg": from_lbs(v, "kg"),
        }
        for m, v in sorted(muscle_volumes_lbs.items(), key=lambda item: -item[1])[:8]
    ]

    weeks = max(1, ((today - start).days + 1) / 7)
    virtual_exercise = {
        "id": uuid.UUID("00000000-0000-0000-0000-000000000000"),
        "name": "All Workouts (Overall)",
        "slug": "all-workouts",
        "muscle_group": "full_body",
        "category": "barbell",
        "tracking_type": "reps",
        "youtube_links": [],
    }
    return {
        "exercise": virtual_exercise,
        "timeframe": timeframe,
        "unit": "kg",
        "timeframe_range": {"start_date": start, "end_date": today},
        "chart_data": list(days.values()),
        "lifetime_pr": {
            "estimated_1rm": _set_brief(base.order_by("-calculated_1rm", "performed_at").first()),
            "max_weight": _set_brief(base.order_by("-weight_lbs", "-reps", "performed_at").first()),
        },
        "total_volume_lbs": quantize(total_volume),
        "total_volume_kg": from_lbs(total_volume, "kg"),
        "session_count": len(sessions),
        "frequency_per_week": quantize(len(sessions) / weeks),
        "volume_by_muscle_group": muscle_shares,
    }
