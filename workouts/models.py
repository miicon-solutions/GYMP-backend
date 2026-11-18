from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import Entity
from fitness.models import WEIGHT_UNITS

MUSCLE_GROUPS = [
    ("chest", "Chest"),
    ("back", "Back"),
    ("quads", "Quads"),
    ("hamstrings", "Hamstrings"),
    ("glutes", "Glutes"),
    ("calves", "Calves"),
    ("shoulders", "Shoulders"),
    ("arms", "Arms"),
    ("core", "Core"),
    ("full_body", "Full Body"),
]
EXERCISE_CATEGORIES = [
    ("barbell", "Barbell"),
    ("dumbbell", "Dumbbell"),
    ("machine", "Machine"),
    ("cable", "Cable"),
    ("bodyweight", "Bodyweight"),
    ("cardio", "Cardio"),
]
FOCUS_TAGS = [
    ("hypertrophy", "Hypertrophy"),
    ("strength", "Strength"),
    ("power", "Power"),
    ("recovery", "Recovery"),
]
SPLIT_CATEGORIES = [
    ("push", "Push"),
    ("pull", "Pull"),
    ("legs", "Legs"),
    ("upper", "Upper"),
    ("lower", "Lower"),
    ("full_body", "Full Body"),
    ("other", "Other"),
]
SESSION_STATUSES = [
    ("in_progress", "In progress"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
]
SET_TYPES = [
    ("warmup", "Warmup"),
    ("working", "Working"),
    ("drop", "Drop"),
    ("failure", "Failure"),
]
TRACKING_TYPES = [
    ("reps", "Sets & Reps"),
    ("time", "Time (Minutes & Seconds)"),
    ("cardio", "Cardio (Time & Distance km)"),
]


class Exercise(Entity):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    muscle_group = models.CharField(max_length=12, choices=MUSCLE_GROUPS)
    target_vector = models.CharField(max_length=120, blank=True)
    # Share of the stimulus per muscle in percent, e.g. {"Pectoralis Major": 52, ...}.
    muscle_distribution = models.JSONField(default=dict, blank=True)
    category = models.CharField(max_length=12, choices=EXERCISE_CATEGORIES)
    tracking_type = models.CharField(max_length=12, choices=TRACKING_TYPES, default="reps")
    youtube_links = models.JSONField(
        default=list,
        blank=True,
        help_text="List of YouTube tutorial video links e.g. [{'title': 'Form Guide', 'url': 'https://youtube.com/watch?v=...'}]",
    )
    is_custom = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="custom_exercises",
    )

    class Meta(Entity.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["slug"], condition=Q(created_by__isnull=True), name="system_exercise_slug"
            ),
            models.UniqueConstraint(
                fields=["created_by", "slug"],
                condition=Q(created_by__isnull=False),
                name="custom_exercise_slug",
            ),
            models.CheckConstraint(
                condition=Q(is_custom=False, created_by__isnull=True)
                | Q(is_custom=True, created_by__isnull=False),
                name="exercise_custom_has_owner",
            ),
        ]

    def __str__(self):
        return self.name


class Routine(Entity):
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_predefined = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="custom_routines",
    )
    estimated_duration_minutes = models.PositiveSmallIntegerField(default=60)
    focus_tag = models.CharField(max_length=12, choices=FOCUS_TAGS, default="hypertrophy")
    split_category = models.CharField(max_length=10, choices=SPLIT_CATEGORIES, default="other")
    exercises = models.ManyToManyField(Exercise, through="RoutineExercise", related_name="+")

    class Meta(Entity.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["title"], condition=Q(created_by__isnull=True), name="system_routine_title"
            ),
            models.CheckConstraint(
                condition=Q(is_predefined=True, created_by__isnull=True)
                | Q(is_predefined=False, created_by__isnull=False),
                name="routine_predefined_no_owner",
            ),
        ]

    def __str__(self):
        return self.title


class RoutineExercise(Entity):
    routine = models.ForeignKey(Routine, on_delete=models.CASCADE, related_name="items")
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name="+")
    order = models.PositiveSmallIntegerField()
    target_sets = models.PositiveSmallIntegerField(default=3)
    target_reps_range = models.CharField(max_length=32, default="8-12")
    target_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    target_distance_km = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    rest_protocol_seconds = models.PositiveSmallIntegerField(default=90)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["routine", "order"], name="routine_exercise_order")
        ]

    def __str__(self):
        return f"{self.routine_id}#{self.order}"


class WorkoutSession(Entity):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workout_sessions"
    )
    routine = models.ForeignKey(
        Routine, on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions"
    )
    title = models.CharField(max_length=160)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=SESSION_STATUSES, default="in_progress")
    total_volume_lbs = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    estimated_calories_burned = models.PositiveIntegerField(default=0)
    rpe_average = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta(Entity.Meta):
        indexes = [models.Index(fields=["user", "-start_time"], name="session_user_start")]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status="in_progress"),
                name="one_active_workout_per_user",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["in_progress", "completed", "cancelled"]),
                name="workout_session_valid_status",
            ),
            models.CheckConstraint(
                condition=Q(end_time__isnull=True) | Q(end_time__gte=models.F("start_time")),
                name="session_end_after_start",
            ),
        ]

    def __str__(self):
        return self.title


class WorkoutSet(Entity):
    workout_session = models.ForeignKey(
        WorkoutSession, on_delete=models.CASCADE, related_name="sets"
    )
    # Denormalised owner keeps PR and analytics lookups on a single indexed table.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workout_sets"
    )
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name="sets")
    set_number = models.PositiveSmallIntegerField()
    set_type = models.CharField(max_length=8, choices=SET_TYPES, default="working")
    weight = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    weight_unit = models.CharField(max_length=3, choices=WEIGHT_UNITS, default="kg")
    weight_lbs = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    reps = models.PositiveSmallIntegerField(default=1)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    distance_km = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    rpe = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    is_pr = models.BooleanField(default=False)
    calculated_1rm = models.DecimalField(max_digits=8, decimal_places=2, help_text="Pounds")
    performed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["performed_at", "set_number"]
        indexes = [
            models.Index(fields=["user", "exercise", "performed_at"], name="set_user_exercise_time")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workout_session", "exercise", "set_number"], name="unique_set_number"
            ),
            models.CheckConstraint(condition=Q(weight__gte=0), name="set_weight_non_negative"),
            models.CheckConstraint(condition=Q(reps__gte=1), name="set_reps_positive"),
            models.CheckConstraint(
                condition=Q(rpe__isnull=True) | Q(rpe__gte=1, rpe__lte=10), name="set_rpe_range"
            ),
        ]

    def __str__(self):
        return f"{self.exercise_id} set {self.set_number}"
