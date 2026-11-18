from django.contrib import admin

from workouts.models import Exercise, Routine, RoutineExercise, WorkoutSession, WorkoutSet


class RoutineExerciseInline(admin.TabularInline):
    model = RoutineExercise
    extra = 1


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "muscle_group", "category", "is_custom", "created_by"]
    search_fields = ["name", "target_vector"]
    list_filter = ["muscle_group", "category", "is_custom"]


@admin.register(Routine)
class RoutineAdmin(admin.ModelAdmin):
    list_display = ["title", "split_category", "focus_tag", "is_predefined", "created_by"]
    search_fields = ["title", "description"]
    list_filter = ["split_category", "focus_tag", "is_predefined"]
    inlines = [RoutineExerciseInline]


class WorkoutSetInline(admin.TabularInline):
    model = WorkoutSet
    extra = 0
    readonly_fields = ["calculated_1rm", "is_pr"]


@admin.register(WorkoutSession)
class WorkoutSessionAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "user",
        "status",
        "start_time",
        "end_time",
        "total_volume_lbs",
        "rpe_average",
    ]
    search_fields = ["title", "user__email", "user__phone_e164"]
    list_filter = ["status"]
    inlines = [WorkoutSetInline]


@admin.register(WorkoutSet)
class WorkoutSetAdmin(admin.ModelAdmin):
    list_display = [
        "workout_session",
        "exercise",
        "set_number",
        "set_type",
        "weight",
        "reps",
        "calculated_1rm",
        "is_pr",
    ]
    search_fields = ["exercise__name", "user__email"]
    list_filter = ["set_type", "is_pr"]
