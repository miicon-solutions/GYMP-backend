from decimal import Decimal

from django.utils.text import slugify
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from workouts.calculators import TIMEFRAMES, from_lbs
from workouts.models import (
    SET_TYPES,
    TRACKING_TYPES,
    Exercise,
    Routine,
    RoutineExercise,
    WorkoutSession,
    WorkoutSet,
)
from workouts.services import (
    accessible_exercises,
    accessible_routines,
    build_session_summary,
    effective_exercise_tracking_type,
    infer_tracking_type,
)


class UserScopedRelatedField(serializers.PrimaryKeyRelatedField):
    """Primary-key field limited to rows the requesting member may reference."""

    def __init__(self, scope, **kwargs):
        self.scope = scope
        kwargs.setdefault("pk_field", serializers.UUIDField())
        super().__init__(**kwargs)

    def get_queryset(self):
        if "request" not in self.context:
            return super().get_queryset()
        return self.scope(self.context["request"].user)


class ExerciseBriefSerializer(serializers.ModelSerializer):
    tracking_type = serializers.SerializerMethodField()

    class Meta:
        model = Exercise
        fields = ["id", "name", "slug", "muscle_group", "category", "tracking_type", "youtube_links"]

    @extend_schema_field(serializers.CharField())
    def get_tracking_type(self, obj):
        if isinstance(obj, dict):
            return obj.get("tracking_type", "reps")
        return effective_exercise_tracking_type(obj)


class ExerciseSerializer(serializers.ModelSerializer):
    tracking_type = serializers.ChoiceField(choices=TRACKING_TYPES, required=False)

    class Meta:
        model = Exercise
        fields = [
            "id",
            "name",
            "slug",
            "muscle_group",
            "target_vector",
            "muscle_distribution",
            "category",
            "tracking_type",
            "youtube_links",
            "is_custom",
            "created_at",
        ]
        read_only_fields = ["slug", "is_custom", "created_at"]

    def validate_youtube_links(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("youtube_links must be a list of link objects or URLs.")
        normalized = []
        for item in value:
            if isinstance(item, str):
                url = item.strip()
                if url:
                    normalized.append({"title": "Exercise Tutorial", "url": url})
            elif isinstance(item, dict):
                url = str(item.get("url", "")).strip()
                title = str(item.get("title", "")).strip() or "Exercise Tutorial"
                if url:
                    normalized.append({"title": title, "url": url})
        return normalized

    def validate_name(self, value):
        value = value.strip()
        slug = slugify(value)[:140]
        if not slug:
            raise serializers.ValidationError("Enter a valid exercise name.")
        user = self.context["request"].user
        if user.role == "admin" and not self.initial_data.get("is_custom", False):
            clash = Exercise.objects.filter(created_by__isnull=True, slug=slug)
        else:
            clash = Exercise.objects.filter(created_by=user, slug=slug)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("An exercise with this name already exists.")
        return value

    def create(self, validated_data):
        validated_data.setdefault("slug", slugify(validated_data["name"])[:140])
        validated_data["tracking_type"] = infer_tracking_type(
            validated_data.get("name", ""),
            validated_data.get("category", ""),
            validated_data.get("tracking_type"),
        )
        return super().create(validated_data)

    def validate_muscle_distribution(self, value):
        if not value:
            return {}
        if not isinstance(value, dict) or len(value) > 12:
            raise serializers.ValidationError("Use up to 12 muscles with percentage shares.")
        cleaned = {}
        for muscle, share in value.items():
            if not isinstance(muscle, str) or not muscle.strip() or len(muscle) > 80:
                raise serializers.ValidationError("Muscle names must be short text.")
            if isinstance(share, bool) or not isinstance(share, (int, float)) or share <= 0:
                raise serializers.ValidationError("Shares must be positive numbers.")
            cleaned[muscle.strip()] = share
        if abs(sum(cleaned.values()) - 100) > 0.5:
            raise serializers.ValidationError("Shares must add up to 100.")
        return cleaned

    def save(self, **kwargs):
        if "name" in self.validated_data:
            kwargs["slug"] = slugify(self.validated_data["name"])[:140]
        if "tracking_type" not in self.validated_data and ("name" in self.validated_data or "category" in self.validated_data):
            name = self.validated_data.get("name", getattr(self.instance, "name", ""))
            cat = self.validated_data.get("category", getattr(self.instance, "category", ""))
            kwargs["tracking_type"] = infer_tracking_type(name, cat)
        return super().save(**kwargs)


class RoutineExerciseSerializer(serializers.ModelSerializer):
    exercise_id = UserScopedRelatedField(accessible_exercises, source="exercise", write_only=True)
    exercise = ExerciseBriefSerializer(read_only=True)
    order = serializers.IntegerField(min_value=1, max_value=200, required=False)

    class Meta:
        model = RoutineExercise
        fields = [
            "id",
            "exercise_id",
            "exercise",
            "order",
            "target_sets",
            "target_reps_range",
            "target_duration_seconds",
            "target_distance_km",
            "rest_protocol_seconds",
            "notes",
        ]
        extra_kwargs = {
            "target_sets": {"min_value": 1, "max_value": 20},
            "rest_protocol_seconds": {"max_value": 900},
        }


class RoutineSerializer(serializers.ModelSerializer):
    items = RoutineExerciseSerializer(many=True, required=False)

    class Meta:
        model = Routine
        fields = [
            "id",
            "title",
            "description",
            "is_predefined",
            "estimated_duration_minutes",
            "focus_tag",
            "split_category",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["is_predefined", "created_at", "updated_at"]
        extra_kwargs = {"estimated_duration_minutes": {"min_value": 5, "max_value": 360}}

    def validate_items(self, items):
        if len(items) > 40:
            raise serializers.ValidationError("A routine can hold up to 40 exercises.")
        for index, item in enumerate(items, start=1):
            item.setdefault("order", index)
        orders = [item["order"] for item in items]
        if len(set(orders)) != len(orders):
            raise serializers.ValidationError("Exercise order values must be unique.")
        return items

    def _write_items(self, routine, items):
        if items is None:
            return
        routine.items.all().delete()
        RoutineExercise.objects.bulk_create(
            RoutineExercise(routine=routine, **item) for item in items
        )

    def create(self, validated_data):
        items = validated_data.pop("items", [])
        routine = Routine.objects.create(**validated_data)
        self._write_items(routine, items)
        return routine

    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        request = self.context.get("request")
        if request and request.user.role == "admin":
            if "is_predefined" in self.initial_data:
                instance.is_predefined = self.initial_data["is_predefined"]
                if instance.is_predefined:
                    instance.created_by = None
        routine = super().update(instance, validated_data)
        self._write_items(routine, items)
        return routine


class RoutineBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Routine
        fields = ["id", "title", "focus_tag", "split_category", "estimated_duration_minutes"]


class WorkoutSetSerializer(serializers.ModelSerializer):
    exercise = ExerciseBriefSerializer(read_only=True)
    weight_kg = serializers.SerializerMethodField()
    calculated_1rm_kg = serializers.SerializerMethodField()

    class Meta:
        model = WorkoutSet
        fields = [
            "id",
            "exercise",
            "set_number",
            "set_type",
            "weight",
            "weight_unit",
            "weight_lbs",
            "weight_kg",
            "reps",
            "duration_seconds",
            "distance_km",
            "rpe",
            "is_pr",
            "calculated_1rm",
            "calculated_1rm_kg",
            "performed_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.DecimalField(max_digits=8, decimal_places=2))
    def get_weight_kg(self, obj):
        return from_lbs(obj.weight_lbs, "kg")

    @extend_schema_field(serializers.DecimalField(max_digits=8, decimal_places=2))
    def get_calculated_1rm_kg(self, obj):
        return from_lbs(obj.calculated_1rm, "kg")


class WorkoutSessionUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkoutSession
        fields = [
            "title",
            "notes",
            "status",
            "start_time",
            "end_time",
        ]


class WorkoutSessionSerializer(serializers.ModelSerializer):
    routine = RoutineBriefSerializer(read_only=True)
    sets = WorkoutSetSerializer(many=True, read_only=True)
    duration_minutes = serializers.SerializerMethodField()
    total_volume_kg = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    class Meta:
        model = WorkoutSession
        fields = [
            "id",
            "title",
            "routine",
            "status",
            "start_time",
            "end_time",
            "duration_minutes",
            "total_volume_lbs",
            "total_volume_kg",
            "estimated_calories_burned",
            "rpe_average",
            "notes",
            "sets",
            "summary",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_duration_minutes(self, obj):
        if not obj.end_time:
            return None
        return int((obj.end_time - obj.start_time).total_seconds() // 60)

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=2))
    def get_total_volume_kg(self, obj):
        return from_lbs(obj.total_volume_lbs or 0, "kg")

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_summary(self, obj):
        if getattr(self, "omit_summary", False):
            return None
        return build_session_summary(obj)


class WorkoutSessionListSerializer(WorkoutSessionSerializer):
    omit_summary = True
    set_count = serializers.IntegerField(read_only=True)
    pr_count = serializers.IntegerField(read_only=True)

    class Meta(WorkoutSessionSerializer.Meta):
        fields = [
            f for f in WorkoutSessionSerializer.Meta.fields if f not in ("sets", "summary")
        ] + [
            "set_count",
            "pr_count",
        ]
        read_only_fields = fields


class StartSessionInput(serializers.Serializer):
    routine_id = UserScopedRelatedField(
        accessible_routines, source="routine", required=False, allow_null=True
    )
    title = serializers.CharField(max_length=160, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=5000, required=False, allow_blank=True)


class LogSetInput(serializers.Serializer):
    exercise_id = UserScopedRelatedField(accessible_exercises, source="exercise")
    set_number = serializers.IntegerField(min_value=1, max_value=100, required=False)
    set_type = serializers.ChoiceField(choices=SET_TYPES, default="working")
    weight = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=0,
        max_value=2000,
        required=False,
        default=Decimal("0.00"),
    )
    weight_unit = serializers.ChoiceField(choices=["kg", "lbs"], required=False)
    reps = serializers.IntegerField(min_value=1, max_value=1000, required=False, default=1)
    duration_seconds = serializers.IntegerField(
        min_value=0, max_value=86400, required=False, allow_null=True
    )
    duration_minutes = serializers.IntegerField(
        min_value=0, max_value=1440, required=False, allow_null=True
    )
    distance_km = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=0,
        max_value=500,
        required=False,
        allow_null=True,
    )
    rpe = serializers.DecimalField(
        max_digits=3, decimal_places=1, min_value=1, max_value=10, required=False, allow_null=True
    )

    def validate(self, attrs):
        mins = attrs.pop("duration_minutes", None)
        secs = attrs.get("duration_seconds")
        if mins is not None:
            attrs["duration_seconds"] = int(mins) * 60 + int(secs or 0)
        return attrs


class SessionTotals(serializers.Serializer):
    id = serializers.UUIDField()
    total_volume_lbs = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_volume_kg = serializers.SerializerMethodField()
    estimated_calories_burned = serializers.IntegerField(required=False)
    rpe_average = serializers.DecimalField(max_digits=3, decimal_places=1, allow_null=True)

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=2))
    def get_total_volume_kg(self, obj):
        vol = obj.get("total_volume_lbs", 0) if isinstance(obj, dict) else getattr(obj, "total_volume_lbs", 0)
        return from_lbs(vol or 0, "kg")


class LogSetOutput(serializers.Serializer):
    set = WorkoutSetSerializer()
    session = SessionTotals()
    previous_best_1rm = serializers.DecimalField(
        max_digits=8, decimal_places=2, allow_null=True, help_text="Pounds, before this session"
    )


class CompleteSessionInput(serializers.Serializer):
    notes = serializers.CharField(max_length=5000, required=False, allow_blank=True)


class AnalyticsQuery(serializers.Serializer):
    timeframe = serializers.ChoiceField(choices=TIMEFRAMES, default="3m")


class DateRange(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class ChartPoint(serializers.Serializer):
    date = serializers.DateField()
    estimated_1rm = serializers.DecimalField(max_digits=8, decimal_places=2)
    estimated_1rm_kg = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)
    actual_weight = serializers.DecimalField(max_digits=8, decimal_places=2)
    actual_weight_kg = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)
    reps = serializers.IntegerField()
    duration_seconds = serializers.IntegerField(required=False)
    distance_km = serializers.DecimalField(max_digits=6, decimal_places=2, required=False)
    volume_load = serializers.DecimalField(max_digits=14, decimal_places=2)
    volume_load_kg = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)


class PRPoint(serializers.Serializer):
    value = serializers.DecimalField(max_digits=8, decimal_places=2)
    value_kg = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)
    weight = serializers.DecimalField(max_digits=8, decimal_places=2)
    weight_kg = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)
    reps = serializers.IntegerField()
    duration_seconds = serializers.IntegerField(allow_null=True, required=False)
    distance_km = serializers.DecimalField(
        max_digits=6, decimal_places=2, allow_null=True, required=False
    )
    date = serializers.DateField()


class LifetimePR(serializers.Serializer):
    estimated_1rm = PRPoint(allow_null=True)
    max_weight = PRPoint(allow_null=True)


class MuscleShare(serializers.Serializer):
    muscle = serializers.CharField()
    percentage = serializers.DecimalField(max_digits=5, decimal_places=1)
    volume_lbs = serializers.DecimalField(max_digits=14, decimal_places=2)
    volume_kg = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)


class AnalyticsOutput(serializers.Serializer):
    exercise = ExerciseBriefSerializer()
    timeframe = serializers.CharField()
    unit = serializers.CharField()
    timeframe_range = DateRange()
    chart_data = ChartPoint(many=True)
    lifetime_pr = LifetimePR()
    total_volume_lbs = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_volume_kg = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    session_count = serializers.IntegerField()
    frequency_per_week = serializers.DecimalField(max_digits=6, decimal_places=2)
    volume_by_muscle_group = MuscleShare(many=True)
