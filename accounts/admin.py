from django.contrib import admin

from accounts.models import StaffProfile, User
from core.admin import ReadOnlyAdmin


@admin.register(User)
class UserAdmin(ReadOnlyAdmin):
    fields = [
        "id",
        "phone_e164",
        "full_name",
        "email",
        "role",
        "is_active",
        "is_staff",
        "is_superuser",
        "created_at",
    ]
    list_display = ["phone_e164", "full_name", "role", "is_active", "is_staff"]
    list_filter = ["role", "is_active", "is_staff"]
    search_fields = ["phone_e164", "full_name", "email"]


@admin.register(StaffProfile)
class StaffAdmin(ReadOnlyAdmin):
    fields = ["id", "user", "short_id", "mfa_enrolled_at", "created_at"]
    list_display = ["short_id", "user", "mfa_enrolled_at"]
    search_fields = ["short_id", "user__full_name", "user__phone_e164"]
