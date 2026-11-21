from django.db import models

from core.models import Entity

DISCOUNTS = [(v, v) for v in ("none", "amount", "percent")]
LIMIT_SCOPES = [(v, v) for v in ("offer", "plan", "gym")]


class Plan(Entity):
    name = models.CharField(max_length=200)
    catalog_id = models.CharField(max_length=30, null=True, blank=True, unique=True)
    monthly_rate_taka = models.PositiveIntegerField()
    admission_fee_taka = models.PositiveIntegerField(default=0)
    duration_months = models.PositiveSmallIntegerField(unique=True)
    discount_type = models.CharField(max_length=8, choices=DISCOUNTS, default="none")
    discount_value = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta(Entity.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(discount_type__in=["none", "amount", "percent"]),
                name="plan_valid_discount",
            ),
            models.CheckConstraint(
                condition=~models.Q(discount_type="percent") | models.Q(discount_value__lte=100),
                name="plan_percent_limit",
            ),
            models.CheckConstraint(
                condition=~models.Q(discount_type="amount")
                | models.Q(
                    discount_value__lte=models.F("monthly_rate_taka") * models.F("duration_months")
                ),
                name="plan_amount_limit",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_months__in=[1, 3, 6, 9, 12]),
                name="plan_allowed_duration",
            ),
        ]

    def __str__(self):
        return self.name


class Offer(Entity):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="offers")
    name = models.CharField(max_length=200)
    starts_on = models.DateField()
    ends_on = models.DateField()
    waive_admission = models.BooleanField(default=False)
    extra_discount_type = models.CharField(max_length=8, choices=DISCOUNTS, default="none")
    extra_discount_value = models.PositiveIntegerField(default=0)
    max_redemptions = models.PositiveIntegerField(null=True, blank=True)
    limit_scope = models.CharField(max_length=8, choices=LIMIT_SCOPES, default="offer")
    is_active = models.BooleanField(default=True)

    class Meta(Entity.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(extra_discount_type__in=["none", "amount", "percent"]),
                name="offer_valid_discount",
            ),
            models.CheckConstraint(
                condition=~models.Q(extra_discount_type="percent")
                | models.Q(extra_discount_value__lte=100),
                name="offer_percent_limit",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")), name="offer_date_order"
            ),
            models.CheckConstraint(
                condition=models.Q(limit_scope__in=["offer", "plan", "gym"]),
                name="offer_valid_limit_scope",
            ),
            models.CheckConstraint(
                condition=models.Q(max_redemptions__isnull=True)
                | models.Q(max_redemptions__gte=1),
                name="offer_max_redemptions_positive",
            ),
        ]
        indexes = [models.Index(fields=["plan", "is_active", "starts_on", "ends_on"])]
