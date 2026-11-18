from django.contrib import admin

from fitness.models import AnthropometryLog, FitnessProfile


@admin.register(FitnessProfile)
class FitnessProfileAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "experience_level",
        "preferred_units",
        "daily_calorie_target",
        "daily_water_target_ml",
    ]
    search_fields = ["user__email", "user__phone_e164", "user__full_name"]
    list_filter = ["experience_level", "preferred_units"]


@admin.register(AnthropometryLog)
class AnthropometryLogAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "logged_at",
        "weight",
        "weight_unit",
        "body_fat_percentage",
        "waist_inches",
    ]
    search_fields = ["user__email", "user__phone_e164"]
    list_filter = ["weight_unit"]
