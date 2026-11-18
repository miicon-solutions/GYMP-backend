from django.contrib import admin

from schedules.models import ScheduledDay, SplitPlannerCycle


class ScheduledDayInline(admin.TabularInline):
    model = ScheduledDay
    extra = 0


@admin.register(SplitPlannerCycle)
class SplitPlannerCycleAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "user",
        "is_active",
        "cycle_length_days",
        "mesocycle_phase",
        "starts_on",
    ]
    search_fields = ["name", "user__email"]
    list_filter = ["is_active"]
    inlines = [ScheduledDayInline]
