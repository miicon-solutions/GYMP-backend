from django.db import models

from core.models import Entity


class CheckIn(Entity):
    member = models.ForeignKey(
        "members.MemberProfile", on_delete=models.CASCADE, related_name="check_ins"
    )
    checked_in_at = models.DateTimeField(db_index=True)
    check_in_date = models.DateField()
    source = models.CharField(
        max_length=10, choices=[(x, x) for x in ("device", "admin", "manual")], default="device"
    )

    class Meta(Entity.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(source__in=["device", "admin", "manual"]),
                name="valid_checkin_source",
            ),
            models.UniqueConstraint(fields=["member", "check_in_date"], name="one_checkin_per_day"),
        ]
