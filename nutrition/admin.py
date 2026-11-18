from django.contrib import admin

from nutrition.models import CookingVariation, HydrationLog, MealLog, Recipe


class CookingVariationInline(admin.TabularInline):
    model = CookingVariation
    extra = 1


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "is_predefined",
        "base_calories",
        "base_protein_g",
        "base_carbs_g",
        "base_fat_g",
    ]
    search_fields = ["title"]
    list_filter = ["is_predefined"]
    inlines = [CookingVariationInline]


@admin.register(MealLog)
class MealLogAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "logged_at",
        "meal_slot",
        "custom_name",
        "calories",
        "protein_g",
        "status",
    ]
    search_fields = ["user__email", "custom_name"]
    list_filter = ["meal_slot", "status"]


@admin.register(HydrationLog)
class HydrationLogAdmin(admin.ModelAdmin):
    list_display = ["user", "date", "intake_amount_ml", "logged_at"]
    search_fields = ["user__email"]
    list_filter = ["date"]
