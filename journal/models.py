from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import Entity

SLEEP_QUALITY_CHOICES = [
    ("deep_rem", "Deep REM"),
    ("nominal", "Nominal"),
    ("restless", "Restless"),
]
CNS_DRIVE_CHOICES = [
    ("fired_up", "Fired Up"),
    ("normal", "Normal"),
    ("fatigued", "Fatigued"),
]


class GymJournalEntry(Entity):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="journal_entries"
    )
    date = models.DateField(default=timezone.localdate)
    linked_workout_session = models.ForeignKey(
        "workouts.WorkoutSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_entries",
    )
    energy_level = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    muscle_soreness = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    sleep_hours = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=8.0,
        validators=[MinValueValidator(0), MaxValueValidator(24)],
    )
    sleep_quality = models.CharField(
        max_length=12, choices=SLEEP_QUALITY_CHOICES, default="nominal"
    )
    cns_drive = models.CharField(max_length=12, choices=CNS_DRIVE_CHOICES, default="normal")
    subjective_notes = models.TextField(
        blank=True, help_text="Markdown text for notes, joint feel, warmup effectiveness"
    )
    protocol_adjustments = models.TextField(
        blank=True, help_text="Cues or load modulations for the next session"
    )
    tags = models.JSONField(default=list, blank=True, help_text='["#PR", "#LegDay", "#Deload"]')

    class Meta(Entity.Meta):
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="unique_user_daily_journal"),
            models.CheckConstraint(
                condition=Q(energy_level__gte=1, energy_level__lte=5), name="valid_energy_level"
            ),
            models.CheckConstraint(
                condition=Q(muscle_soreness__gte=1, muscle_soreness__lte=5),
                name="valid_muscle_soreness",
            ),
            models.CheckConstraint(
                condition=Q(sleep_hours__gte=0, sleep_hours__lte=24), name="valid_sleep_hours"
            ),
        ]

    def __str__(self):
        return f"{self.user_id} - {self.date} (Energy: {self.energy_level}/5)"
