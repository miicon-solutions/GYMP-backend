from django.contrib import admin

from core.admin import OperatorModelAdmin
from members.models import MemberProfile


@admin.register(MemberProfile)
class MemberProfileAdmin(OperatorModelAdmin):
    list_display = ["member_id", "user", "membership_status", "fingerprint_status"]
    search_fields = ["member_id", "user__full_name", "user__phone_e164"]
    list_filter = ["membership_status", "fingerprint_status"]
    exclude = ["device_pin_enc"]
    readonly_fields = ("id", "created_at", "updated_at", "device_pin_updated_at")
