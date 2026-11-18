from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from operations.models import Holiday, WeekdayHours
from operations.services import holiday_data, week_data
from schedules.models import ScheduledDay, SplitPlannerCycle
from schedules.services import TEMPLATES, get_day_closure_info
from workouts.models import FOCUS_TAGS, SPLIT_CATEGORIES
from workouts.serializers import (
    RoutineBriefSerializer,
    RoutineExerciseSerializer,
    UserScopedRelatedField,
)
from workouts.services import accessible_exercises, accessible_routines


class ScheduledRoutineDetailSerializer(RoutineBriefSerializer):
    items = RoutineExerciseSerializer(many=True, read_only=True)

    class Meta(RoutineBriefSerializer.Meta):
        fields = [*RoutineBriefSerializer.Meta.fields, "is_predefined", "items"]


class CustomDayExerciseInputSerializer(serializers.Serializer):
    exercise_id = UserScopedRelatedField(accessible_exercises, source="exercise")
    target_sets = serializers.IntegerField(min_value=1, max_value=20, default=3, required=False)
    target_reps_range = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default="8-12"
    )
    target_duration_seconds = serializers.IntegerField(
        min_value=0, max_value=86400, required=False, allow_null=True
    )
    target_distance_km = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=0,
        max_value=500,
        required=False,
        allow_null=True,
    )
    rest_protocol_seconds = serializers.IntegerField(
        min_value=0, max_value=900, default=90, required=False
    )
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class ScheduledDaySerializer(serializers.ModelSerializer):
    assigned_routine = ScheduledRoutineDetailSerializer(read_only=True)
    assigned_routine_id = UserScopedRelatedField(
        accessible_routines,
        source="assigned_routine",
        write_only=True,
        required=False,
        allow_null=True,
    )
    weekday = serializers.SerializerMethodField()
    date = serializers.SerializerMethodField()
    is_gym_closed = serializers.SerializerMethodField()
    closed_reason = serializers.SerializerMethodField()
    closed_note = serializers.SerializerMethodField()
    closed_note_bn = serializers.SerializerMethodField()

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
            "custom_exercises",
            "weekday",
            "date",
            "is_gym_closed",
            "closed_reason",
            "closed_note",
            "closed_note_bn",
        ]

    def _closure(self, obj):
        cache = getattr(obj, "_closure_cache", None)
        if cache is None:
            cache = get_day_closure_info(obj.cycle, obj.day_index)
            obj._closure_cache = cache
        return cache

    @extend_schema_field(serializers.IntegerField())
    def get_weekday(self, obj):
        return self._closure(obj)["weekday"]

    @extend_schema_field(serializers.DateField())
    def get_date(self, obj):
        return self._closure(obj)["date"]

    @extend_schema_field(serializers.BooleanField())
    def get_is_gym_closed(self, obj):
        return self._closure(obj)["is_gym_closed"]

    @extend_schema_field(serializers.CharField())
    def get_closed_reason(self, obj):
        return self._closure(obj)["closed_reason"]

    @extend_schema_field(serializers.CharField())
    def get_closed_note(self, obj):
        return self._closure(obj)["closed_note"]

    @extend_schema_field(serializers.CharField())
    def get_closed_note_bn(self, obj):
        return self._closure(obj)["closed_note_bn"]


class ScheduledDayUpdateSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=80, required=False, allow_blank=True)
    assigned_routine_id = UserScopedRelatedField(
        accessible_routines, source="assigned_routine", required=False, allow_null=True
    )
    is_rest_day = serializers.BooleanField(required=False)
    target_focus_tags = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False
    )
    custom_exercises = CustomDayExerciseInputSerializer(many=True, required=False)
    split_category = serializers.ChoiceField(choices=SPLIT_CATEGORIES, required=False, default="other")
    focus_tag = serializers.ChoiceField(choices=FOCUS_TAGS, required=False, default="hypertrophy")
    swap_with_day_index = serializers.IntegerField(min_value=0, max_value=27, required=False)


class SplitPlannerCycleSerializer(serializers.ModelSerializer):
    days = ScheduledDaySerializer(many=True, read_only=True)
    closed_weekdays = serializers.SerializerMethodField()
    gym_week = serializers.SerializerMethodField()
    upcoming_holidays = serializers.SerializerMethodField()

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
            "closed_weekdays",
            "gym_week",
            "upcoming_holidays",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "is_active",
            "days",
            "closed_weekdays",
            "gym_week",
            "upcoming_holidays",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField()))
    def get_closed_weekdays(self, obj):
        closed = list(WeekdayHours.objects.filter(is_open=False).values_list("weekday", flat=True))
        return closed if WeekdayHours.objects.exists() else [5]

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_gym_week(self, obj):
        return week_data()

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_upcoming_holidays(self, obj):
        return [holiday_data(h) for h in Holiday.objects.order_by("date")[:30]]


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
