from django.db import models

from core.models import Entity


class PaymentSession(Entity):
    tran_id = models.CharField(max_length=30, unique=True)
    member = models.ForeignKey("members.MemberProfile", on_delete=models.CASCADE)
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
        "members.MemberProfile", on_delete=models.CASCADE, related_name="payments"
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
    # Frozen at settle time for discount comparison reports (null = pre-migration).
    list_amount_taka = models.PositiveIntegerField(null=True, blank=True)
    standing_discount_taka = models.PositiveIntegerField(null=True, blank=True)
    offer_discount_taka = models.PositiveIntegerField(null=True, blank=True)
    admission_waived_taka = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, default="paid")
    paid_at = models.DateTimeField(null=True, db_index=True)
    line_items = models.JSONField(default=list)
    offer = models.ForeignKey(
        "plans.Offer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="redemptions",
    )

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


class CashPaymentRequest(Entity):
    """Member-initiated cash intent awaiting staff acknowledgment at reception."""

    member = models.ForeignKey(
        "members.MemberProfile",
        on_delete=models.CASCADE,
        related_name="cash_payment_requests",
    )
    plan = models.ForeignKey("plans.Plan", on_delete=models.PROTECT)
    kind = models.CharField(max_length=20, default="first_payment")
    amount_taka = models.PositiveIntegerField()
    pricing_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=12, default="pending")
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_cash_requests",
    )
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_requests",
    )

    class Meta(Entity.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=["first_payment", "renewal", "plan_change"]),
                name="cash_request_valid_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "accepted", "rejected", "cancelled"]),
                name="cash_request_valid_status",
            ),
            models.UniqueConstraint(
                fields=["member"],
                condition=models.Q(status="pending"),
                name="one_pending_cash_request_per_member",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "-requested_at"],
                name="cash_request_status_requested",
            ),
        ]
