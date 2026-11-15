from django.contrib import admin

from core.admin import ReadOnlyAdmin
from operations.models import Activity, Cost, Holiday, WeekdayHours


@admin.register(Cost)
class CostAdmin(ReadOnlyAdmin):
    list_display = ["title", "amount_taka", "date", "is_archived"]
    search_fields = ["title"]
    list_filter = ["category", "is_archived"]


@admin.register(Activity)
class ActivityAdmin(ReadOnlyAdmin):
    list_display = ["admin_name", "area", "action", "created_at"]
    search_fields = ["admin_name", "summary_key"]
    list_filter = ["area", "action"]


@admin.register(WeekdayHours)
class WeekdayHoursAdmin(ReadOnlyAdmin):
    list_display = ["weekday", "is_open", "open_time", "close_time"]
    search_fields = []
    list_filter = ["is_open"]


@admin.register(Holiday)
class HolidayAdmin(ReadOnlyAdmin):
    list_display = ["date", "name"]
    search_fields = ["name"]
    list_filter = []
