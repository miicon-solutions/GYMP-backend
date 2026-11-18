from rest_framework import serializers

from schedules.models import ScheduledDay, SplitPlannerCycle
from schedules.services import TEMPLATES
from workouts.serializers import RoutineBriefSerializer, UserScopedRelatedField
from workouts.services import accessible_routines


class ScheduledDaySerializer(serializers.ModelSerializer):
    assigned_routine = RoutineBriefSerializer(read_only=True)
    assigned_routine_id = UserScopedRelatedField(
        accessible_routines,
        source="assigned_routine",
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = ScheduledDay
        fields = [
            "id",
            "day_index",
            "label",
            "assigned_routine",
            "assigned_routine_id",
            "is_rest_day",
            "target_focus_tags",
        ]


class ScheduledDayUpdateSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=80, required=False)
    assigned_routine_id = UserScopedRelatedField(
        accessible_routines, source="assigned_routine", required=False, allow_null=True
    )
    is_rest_day = serializers.BooleanField(required=False)
    target_focus_tags = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False
    )
    swap_with_day_index = serializers.IntegerField(min_value=0, max_value=27, required=False)


class SplitPlannerCycleSerializer(serializers.ModelSerializer):
    days = ScheduledDaySerializer(many=True, read_only=True)

    class Meta:
        model = SplitPlannerCycle
        fields = [
            "id",
            "name",
            "is_active",
            "mesocycle_phase",
            "cycle_length_days",
            "starts_on",
            "days",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "days", "created_at", "updated_at"]


class CreateCycleDayInput(serializers.Serializer):
    day_index = serializers.IntegerField(min_value=0, max_value=27)
    label = serializers.CharField(max_length=80, required=False)
    assigned_routine_id = UserScopedRelatedField(
        accessible_routines, source="assigned_routine", required=False, allow_null=True
    )
    is_rest_day = serializers.BooleanField(default=True)
    target_focus_tags = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False
    )


class CreateCycleInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    mesocycle_phase = serializers.CharField(max_length=160, required=False, allow_blank=True)
    cycle_length_days = serializers.IntegerField(default=7, min_value=1, max_value=28)
    starts_on = serializers.DateField(required=False)
    days = CreateCycleDayInput(many=True, required=False)


class AutoPopulateInput(serializers.Serializer):
    template = serializers.ChoiceField(choices=list(TEMPLATES.keys()), default="ppl")
    prefer_custom = serializers.BooleanField(default=True)
