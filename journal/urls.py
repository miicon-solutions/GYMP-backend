from django.urls import path

from journal.views import (
    JournalEntryDetailView,
    JournalEntryListView,
    JournalEntryTodayView,
)

urlpatterns = [
    path("entries/", JournalEntryListView.as_view(), name="journal-entry-list"),
    path("entries/today/", JournalEntryTodayView.as_view(), name="journal-entry-today"),
    path(
        "entries/<uuid:pk>/",
        JournalEntryDetailView.as_view(),
        name="journal-entry-detail",
    ),
]
