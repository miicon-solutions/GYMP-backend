import re

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from journal.models import GymJournalEntry
from workouts.models import WorkoutSession

TAG_PATTERN = re.compile(r"#[A-Za-z0-9_]+")


def extract_tags(text, explicit_tags=None):
    found = set()
    if text:
        for match in TAG_PATTERN.findall(text):
            found.add(match.strip())
    if explicit_tags:
        for tag in explicit_tags:
            tag = str(tag).strip()
            if not tag.startswith("#"):
                tag = f"#{tag}"
            found.add(tag)
    return sorted(list(found))


def list_entries(user, tag=None):
    qs = GymJournalEntry.objects.filter(user=user).select_related("linked_workout_session")
    if tag:
        tag_val = tag.strip()
        if not tag_val.startswith("#"):
            tag_val = f"#{tag_val}"
        qs = qs.filter(tags__icontains=tag_val)
    return qs


def get_entry(user, pk):
    return get_object_or_404(
        GymJournalEntry.objects.filter(user=user).select_related("linked_workout_session"), pk=pk
    )


@transaction.atomic
def get_or_create_today(user, target_date=None):
    target_date = target_date or timezone.localdate()
    entry = (
        GymJournalEntry.objects.filter(user=user, date=target_date)
        .select_related("linked_workout_session")
        .first()
    )
    if not entry:
        # Check if there was a workout session today
        session = (
            WorkoutSession.objects.filter(user=user, start_time__date=target_date)
            .order_by("-start_time")
            .first()
        )
        entry = GymJournalEntry.objects.create(
            user=user,
            date=target_date,
            linked_workout_session=session,
            energy_level=3,
            muscle_soreness=3,
            sleep_hours=8.0,
            sleep_quality="nominal",
            cns_drive="normal",
            subjective_notes="",
            protocol_adjustments="",
            tags=[],
        )
    return entry


@transaction.atomic
def save_entry(user, data, instance=None):
    data = dict(data)
    notes = data.get("subjective_notes", instance.subjective_notes if instance else "")
    explicit_tags = data.get("tags", instance.tags if instance else [])
    data["tags"] = extract_tags(notes, explicit_tags)

    session = data.get("linked_workout_session")
    if session and session.user_id != user.id:
        from rest_framework.exceptions import ValidationError

        raise ValidationError(
            {"linked_workout_session": "Workout session belongs to another user."}
        )

    if instance:
        for field, value in data.items():
            setattr(instance, field, value)
        instance.save()
        return instance
    else:
        target_date = data.get("date", timezone.localdate())
        entry, created = GymJournalEntry.objects.get_or_create(
            user=user, date=target_date, defaults=data
        )
        if not created:
            for field, value in data.items():
                setattr(entry, field, value)
            entry.save()
        return entry
