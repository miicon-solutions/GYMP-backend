from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import Entity


def current_monday():
    today = timezone.localdate()
    return today - timedelta(days=today.weekday())


class SplitPlannerCycle(Entity):
    """A repeating microcycle. Day ``n`` falls on ``starts_on + n`` modulo the cycle length.

    Seven-day cycles anchored on a Monday (the default) therefore use 0=Monday … 6=Sunday.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="split_cycles"
    )
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    mesocycle_phase = models.CharField(max_length=160, blank=True)
    cycle_length_days = models.PositiveSmallIntegerField(
        default=7, validators=[MinValueValidator(1), MaxValueValidator(28)]
    )
    starts_on = models.DateField(default=current_monday)

    class Meta(Entity.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=Q(is_active=True), name="one_active_cycle_per_user"
            ),
            models.CheckConstraint(
                condition=Q(cycle_length_days__gte=1, cycle_length_days__lte=28),
                name="cycle_length_range",
            ),
        ]

    def day_index_for(self, day):
        return (day - self.starts_on).days % self.cycle_length_days

    def __str__(self):
        return self.name


class ScheduledDay(Entity):
    cycle = models.ForeignKey(SplitPlannerCycle, on_delete=models.CASCADE, related_name="days")
    day_index = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=80, default="Rest")
    assigned_routine = models.ForeignKey(
        "workouts.Routine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scheduled_days",
    )
    is_rest_day = models.BooleanField(default=True)
    target_focus_tags = models.JSONField(default=list, blank=True)
    custom_exercises = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["day_index"]
        constraints = [
            models.UniqueConstraint(fields=["cycle", "day_index"], name="unique_cycle_day"),
            models.CheckConstraint(
                condition=Q(is_rest_day=False) | Q(assigned_routine__isnull=True),
                name="rest_day_has_no_routine",
            ),
        ]

    def __str__(self):
        return f"{self.cycle_id} day {self.day_index}: {self.label}"
