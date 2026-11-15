from django.contrib import admin

from core.admin import ReadOnlyAdmin
from plans.models import Offer, Plan


@admin.register(Plan)
class PlanAdmin(ReadOnlyAdmin):
    list_display = ["name", "duration_months", "is_active"]
    search_fields = ["name"]
    list_filter = ["is_active"]


@admin.register(Offer)
class OfferAdmin(ReadOnlyAdmin):
    list_display = ["name", "plan", "starts_on", "ends_on", "is_active"]
    search_fields = ["name"]
    list_filter = ["is_active"]
