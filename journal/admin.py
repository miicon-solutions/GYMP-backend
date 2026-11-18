from django.contrib import admin

from journal.models import GymJournalEntry


@admin.register(GymJournalEntry)
class GymJournalEntryAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "date",
        "energy_level",
        "muscle_soreness",
        "sleep_hours",
        "sleep_quality",
        "cns_drive",
    ]
    search_fields = ["user__email", "subjective_notes", "tags"]
    list_filter = ["energy_level", "muscle_soreness", "sleep_quality", "cns_drive"]
