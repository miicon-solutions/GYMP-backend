from django.contrib import admin

from attendance.models import CheckIn
from core.admin import ReadOnlyAdmin


@admin.register(CheckIn)
class CheckInAdmin(ReadOnlyAdmin):
    list_display = ["member", "checked_in_at", "source"]
    search_fields = ["member__member_id"]
    list_filter = ["source"]
