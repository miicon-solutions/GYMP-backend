from django.contrib import admin

from core.admin import OperatorModelAdmin
from plans.models import Offer, Plan


@admin.register(Plan)
class PlanAdmin(OperatorModelAdmin):
    list_display = ["name", "duration_months", "is_active"]
    search_fields = ["name"]
    list_filter = ["is_active"]


@admin.register(Offer)
class OfferAdmin(OperatorModelAdmin):
    list_display = [
        "name",
        "plan",
        "starts_on",
        "ends_on",
        "waive_admission",
        "max_redemptions",
        "limit_scope",
        "is_active",
    ]
    search_fields = ["name"]
    list_filter = ["is_active", "limit_scope", "waive_admission"]
