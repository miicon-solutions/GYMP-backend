from django.contrib import admin

from core.admin import ReadOnlyAdmin
from payments.models import Payment, PaymentSession


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ["member", "channel", "amount_taka", "paid_at"]
    search_fields = ["member__member_id", "tran_id"]
    list_filter = ["channel", "status"]


@admin.register(PaymentSession)
class PaymentSessionAdmin(ReadOnlyAdmin):
    list_display = ["tran_id", "member", "amount_taka", "status"]
    search_fields = ["tran_id", "member__member_id"]
    list_filter = ["status"]
    exclude = ["session_key", "val_id", "bank_tran_id", "pricing_snapshot"]
