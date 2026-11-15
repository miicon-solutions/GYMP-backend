from django.db import models

from core.models import Entity


class PaymentSession(Entity):
    tran_id = models.CharField(max_length=30, unique=True)
    member = models.ForeignKey("members.MemberProfile", on_delete=models.PROTECT)
    plan = models.ForeignKey("plans.Plan", on_delete=models.PROTECT)
    kind = models.CharField(max_length=20)
    amount_taka = models.PositiveIntegerField()
    status = models.CharField(max_length=12, default="pending")
    pricing_snapshot = models.JSONField(default=dict)
    gateway_url = models.URLField(max_length=2000, blank=True)
    session_key = models.CharField(max_length=200, blank=True)
    val_id = models.CharField(max_length=200, blank=True)
    bank_tran_id = models.CharField(max_length=200, blank=True)
    paid_at = models.DateTimeField(null=True)

    class Meta(Entity.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=["first_purchase", "renew", "change_plan"]),
                name="session_valid_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "paid", "failed", "cancelled"]),
                name="session_valid_status",
            ),
            models.CheckConstraint(
                condition=~models.Q(tran_id=""), name="session_nonempty_transaction"
            ),
        ]
        indexes = [
            models.Index(
                fields=["member", "kind"],
                condition=models.Q(status="pending"),
                name="pending_member_sessions",
            )
        ]


class Payment(Entity):
    member = models.ForeignKey(
        "members.MemberProfile", on_delete=models.PROTECT, related_name="payments"
    )
    plan = models.ForeignKey("plans.Plan", on_delete=models.PROTECT)
    tran_id = models.CharField(max_length=30, null=True, blank=True, unique=True)
    catalog_id = models.CharField(max_length=30, null=True, blank=True)
    channel = models.CharField(
        max_length=12, choices=[("cash", "Cash"), ("sslcommerz", "SSLCommerz")]
    )
    kind = models.CharField(max_length=20)
    is_first_payment = models.BooleanField(default=False)
    amount_taka = models.PositiveIntegerField()
    status = models.CharField(max_length=12, default="paid")
    paid_at = models.DateTimeField(null=True, db_index=True)
    line_items = models.JSONField(default=list)

    class Meta(Entity.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(channel__in=["cash", "sslcommerz"]), name="payment_valid_channel"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["paid", "failed"]), name="payment_valid_status"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=[
                        "first_purchase",
                        "renew",
                        "change_plan",
                        "first_payment",
                        "renewal",
                        "plan_change",
                    ]
                ),
                name="payment_valid_kind",
            ),
        ]
        indexes = [
            models.Index(fields=["member", "-paid_at"]),
            models.Index(fields=["status", "channel", "paid_at"]),
        ]
