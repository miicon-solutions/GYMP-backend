from django.contrib import admin

from core.admin import OperatorModelAdmin
from payments.models import CashPaymentRequest, Payment, PaymentSession


@admin.register(Payment)
class PaymentAdmin(OperatorModelAdmin):
    list_display = ["member", "channel", "amount_taka", "paid_at"]
    search_fields = ["member__member_id", "tran_id"]
    list_filter = ["channel", "status"]


@admin.register(PaymentSession)
class PaymentSessionAdmin(OperatorModelAdmin):
    list_display = ["tran_id", "member", "amount_taka", "status"]
    search_fields = ["tran_id", "member__member_id"]
    list_filter = ["status"]
    exclude = ["session_key", "val_id", "bank_tran_id", "pricing_snapshot"]


@admin.register(CashPaymentRequest)
class CashPaymentRequestAdmin(OperatorModelAdmin):
    list_display = ["member", "plan", "amount_taka", "status", "requested_at"]
    search_fields = ["member__member_id", "member__user__full_name"]
    list_filter = ["status", "kind"]
    exclude = ["pricing_snapshot"]
