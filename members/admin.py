from django.contrib import admin

from core.admin import ReadOnlyAdmin
from members.models import MemberProfile


@admin.register(MemberProfile)
class MemberProfileAdmin(ReadOnlyAdmin):
    list_display = ["member_id", "user", "membership_status", "fingerprint_status"]
    search_fields = ["member_id", "user__full_name", "user__phone_e164"]
    list_filter = ["membership_status", "fingerprint_status"]
