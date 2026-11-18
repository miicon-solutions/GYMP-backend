from rest_framework import serializers

from journal.models import (
    CNS_DRIVE_CHOICES,
    SLEEP_QUALITY_CHOICES,
    GymJournalEntry,
)
from workouts.models import WorkoutSession
from workouts.serializers import UserScopedRelatedField
from workouts.services import session_queryset


class LinkedSessionBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkoutSession
        fields = ["id", "title", "status", "total_volume_lbs", "rpe_average"]


class GymJournalEntrySerializer(serializers.ModelSerializer):
    linked_workout_session = LinkedSessionBriefSerializer(read_only=True)

    class Meta:
        model = GymJournalEntry
        fields = [
            "id",
            "date",
            "linked_workout_session",
            "energy_level",
            "muscle_soreness",
            "sleep_hours",
            "sleep_quality",
            "cns_drive",
            "subjective_notes",
            "protocol_adjustments",
            "tags",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class GymJournalEntryInputSerializer(serializers.Serializer):
    date = serializers.DateField(required=False)
    linked_workout_session_id = UserScopedRelatedField(
        session_queryset, source="linked_workout_session", required=False, allow_null=True
    )
    energy_level = serializers.IntegerField(default=3, min_value=1, max_value=5)
    muscle_soreness = serializers.IntegerField(default=3, min_value=1, max_value=5)
    sleep_hours = serializers.DecimalField(
        default=8.0, max_digits=4, decimal_places=1, min_value=0, max_value=24
    )
    sleep_quality = serializers.ChoiceField(choices=SLEEP_QUALITY_CHOICES, default="nominal")
    cns_drive = serializers.ChoiceField(choices=CNS_DRIVE_CHOICES, default="normal")
    subjective_notes = serializers.CharField(required=False, allow_blank=True, max_length=10000)
    protocol_adjustments = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    tags = serializers.ListField(child=serializers.CharField(max_length=50), required=False)
