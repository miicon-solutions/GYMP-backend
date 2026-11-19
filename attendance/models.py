from django.db import models

from core.models import Entity


class CheckIn(Entity):
    member = models.ForeignKey(
        "members.MemberProfile", on_delete=models.CASCADE, related_name="check_ins"
    )
    checked_in_at = models.DateTimeField(db_index=True)
    # Latest device/admin punch for this visit day (Home "Last check-in").
    # Session start stays on checked_in_at; same-day re-punches only bump this.
    last_punch_at = models.DateTimeField(null=True, blank=True, db_index=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    check_in_date = models.DateField()
    source = models.CharField(
        max_length=10, choices=[(x, x) for x in ("device", "admin", "manual")], default="device"
    )
    check_out_source = models.CharField(
        max_length=12,
        blank=True,
        default="",
        choices=[(x, x) for x in ("", "device", "admin", "manual", "auto_cap")],
    )
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    auto_closed = models.BooleanField(default=False)

    class Meta(Entity.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(source__in=["device", "admin", "manual"]),
                name="valid_checkin_source",
            ),
            models.UniqueConstraint(fields=["member", "check_in_date"], name="one_checkin_per_day"),
        ]


class CheckInPunch(Entity):
    """Every fingerprint punch for a visit day (timeline log)."""

    check_in = models.ForeignKey(CheckIn, on_delete=models.CASCADE, related_name="punches")
    punched_at = models.DateTimeField(db_index=True)
    source = models.CharField(
        max_length=10, choices=[(x, x) for x in ("device", "admin", "manual")], default="device"
    )

    class Meta(Entity.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["check_in", "punched_at"], name="unique_punch_per_checkin_time"
            ),
        ]
        ordering = ["punched_at"]


class StaffCheckIn(Entity):
    """Staff door/attendance visit day (device user id = staff short_id)."""

    staff = models.ForeignKey(
        "accounts.StaffProfile", on_delete=models.CASCADE, related_name="check_ins"
    )
    checked_in_at = models.DateTimeField(db_index=True)
    last_punch_at = models.DateTimeField(null=True, blank=True, db_index=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    check_in_date = models.DateField()
    source = models.CharField(
        max_length=10, choices=[(x, x) for x in ("device", "admin", "manual")], default="device"
    )
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta(Entity.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(source__in=["device", "admin", "manual"]),
                name="valid_staff_checkin_source",
            ),
            models.UniqueConstraint(
                fields=["staff", "check_in_date"], name="one_staff_checkin_per_day"
            ),
        ]


class StaffCheckInPunch(Entity):
    check_in = models.ForeignKey(StaffCheckIn, on_delete=models.CASCADE, related_name="punches")
    punched_at = models.DateTimeField(db_index=True)
    source = models.CharField(
        max_length=10, choices=[(x, x) for x in ("device", "admin", "manual")], default="device"
    )

    class Meta(Entity.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["check_in", "punched_at"], name="unique_punch_per_staff_checkin_time"
            ),
        ]
        ordering = ["punched_at"]
