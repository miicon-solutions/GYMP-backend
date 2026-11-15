from django.conf import settings
from django.db import models

from core.models import Entity


class Cost(Entity):
    title = models.CharField(max_length=200)
    category = models.CharField(
        max_length=20,
        choices=[(x, x) for x in ("rent", "utilities", "salary", "equipment", "other")],
    )
    amount_taka = models.PositiveIntegerField()
    date = models.DateField(db_index=True)
    note = models.TextField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)


class Activity(Entity):
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    admin_name = models.CharField(max_length=200)
    admin_short_id = models.CharField(max_length=24)
    area = models.CharField(max_length=20, db_index=True)
    action = models.CharField(max_length=20)
    summary_key = models.CharField(max_length=100)
    summary_params = models.JSONField(default=dict)


class WeekdayHours(models.Model):
    weekday = models.PositiveSmallIntegerField(primary_key=True)
    is_open = models.BooleanField(default=True)
    open_time = models.TimeField(null=True, blank=True)
    close_time = models.TimeField(null=True, blank=True)

    class Meta:
        ordering = ["weekday"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(weekday__gte=1, weekday__lte=7), name="valid_weekday"
            ),
            models.CheckConstraint(
                condition=models.Q(is_open=False, open_time__isnull=True, close_time__isnull=True)
                | models.Q(
                    is_open=True,
                    open_time__isnull=False,
                    close_time__isnull=False,
                    open_time__lt=models.F("close_time"),
                ),
                name="valid_open_hours",
            ),
        ]


class Holiday(Entity):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=200, null=True, blank=True)
