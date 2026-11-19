from django.contrib import admin

from attendance.models import CheckIn
from core.admin import OperatorModelAdmin


@admin.register(CheckIn)
class CheckInAdmin(OperatorModelAdmin):
    list_display = ["member", "checked_in_at", "source"]
    search_fields = ["member__member_id"]
    list_filter = ["source"]
