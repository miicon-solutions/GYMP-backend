import django_filters

from workouts.models import (
    EXERCISE_CATEGORIES,
    FOCUS_TAGS,
    MUSCLE_GROUPS,
    SESSION_STATUSES,
    SPLIT_CATEGORIES,
    Exercise,
    Routine,
    WorkoutSession,
)


class ExerciseFilter(django_filters.FilterSet):
    muscle_group = django_filters.MultipleChoiceFilter(choices=MUSCLE_GROUPS)
    category = django_filters.MultipleChoiceFilter(choices=EXERCISE_CATEGORIES)

    class Meta:
        model = Exercise
        fields = ["muscle_group", "category", "is_custom"]


class RoutineFilter(django_filters.FilterSet):
    focus_tag = django_filters.MultipleChoiceFilter(choices=FOCUS_TAGS)
    split_category = django_filters.MultipleChoiceFilter(choices=SPLIT_CATEGORIES)
    max_duration = django_filters.NumberFilter(
        field_name="estimated_duration_minutes", lookup_expr="lte"
    )

    class Meta:
        model = Routine
        fields = ["focus_tag", "split_category", "is_predefined"]


class SessionFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=SESSION_STATUSES)
    date_from = django_filters.DateFilter(field_name="start_time", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="start_time", lookup_expr="date__lte")
    routine = django_filters.UUIDFilter(field_name="routine_id")

    class Meta:
        model = WorkoutSession
        fields = ["status", "routine"]
