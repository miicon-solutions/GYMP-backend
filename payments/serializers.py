from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from payments.models import CashPaymentRequest, Payment, PaymentSession


class SessionInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["first_purchase", "renew", "change_plan"])
    plan_id = serializers.UUIDField()
    checkout = serializers.ChoiceField(choices=["sdk", "hosted"], default="hosted")


class PlanInput(serializers.Serializer):
    plan_id = serializers.UUIDField()


class SessionSerializer(serializers.ModelSerializer):
    plan_id = serializers.UUIDField(read_only=True)
    admission_waived = serializers.SerializerMethodField()

    class Meta:
        model = PaymentSession
        fields = [
            "tran_id",
            "kind",
            "plan_id",
            "amount_taka",
            "status",
            "gateway_url",
            "paid_at",
            "admission_waived",
        ]

    @extend_schema_field(serializers.BooleanField())
    def get_admission_waived(self, obj):
        snap = obj.pricing_snapshot or {}
        return bool(snap.get("admission_waived"))


class PaymentSerializer(serializers.ModelSerializer):
    plan_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "tran_id",
            "channel",
            "plan_id",
            "catalog_id",
            "kind",
            "is_first_payment",
            "amount_taka",
            "status",
            "paid_at",
            "line_items",
        ]


class IPNInput(serializers.Serializer):
    tran_id = serializers.CharField(max_length=30)
    val_id = serializers.CharField(required=False, allow_blank=True, max_length=200)
    status = serializers.CharField(max_length=30)


class CashPreviewOutput(serializers.Serializer):
    kind = serializers.CharField()
    amount_taka = serializers.IntegerField()
    new_expires_on = serializers.DateField()
    plan_id = serializers.UUIDField()
    catalog_id = serializers.CharField(allow_null=True)
    requires_admission = serializers.BooleanField(required=False)


class CashRequestStatusFilter(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["pending", "accepted", "rejected", "cancelled"],
        required=False,
        default="pending",
    )


class CashPaymentRequestSerializer(serializers.ModelSerializer):
    plan_id = serializers.UUIDField(read_only=True)
    payment_id = serializers.UUIDField(read_only=True, allow_null=True)
    # Admin member routes key on User UUID (same as AdminMemberOutput.id /
    # notify_staff_cash_request), not MemberProfile.pk.
    member_id = serializers.UUIDField(source="member.user_id", read_only=True)
    member_display_id = serializers.CharField(source="member.member_id", read_only=True)
    member_name = serializers.CharField(source="member.user.full_name", read_only=True)
    member_phone_e164 = serializers.CharField(source="member.user.phone_e164", read_only=True)
    catalog_id = serializers.SerializerMethodField()
    admission_waived = serializers.SerializerMethodField()
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        model = CashPaymentRequest
        fields = [
            "id",
            "member_id",
            "member_display_id",
            "member_name",
            "member_phone_e164",
            "plan_id",
            "plan_name",
            "catalog_id",
            "kind",
            "amount_taka",
            "status",
            "requested_at",
            "resolved_at",
            "payment_id",
            "admission_waived",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_catalog_id(self, obj):
        snap = obj.pricing_snapshot or {}
        return snap.get("catalog_id") or obj.plan.catalog_id

    @extend_schema_field(serializers.BooleanField())
    def get_admission_waived(self, obj):
        snap = obj.pricing_snapshot or {}
        return bool(snap.get("admission_waived"))


class MemberCashPaymentRequestSerializer(serializers.ModelSerializer):
    plan_id = serializers.UUIDField(read_only=True)
    payment_id = serializers.UUIDField(read_only=True, allow_null=True)
    catalog_id = serializers.SerializerMethodField()
    admission_waived = serializers.SerializerMethodField()

    class Meta:
        model = CashPaymentRequest
        fields = [
            "id",
            "plan_id",
            "catalog_id",
            "kind",
            "amount_taka",
            "status",
            "requested_at",
            "resolved_at",
            "payment_id",
            "admission_waived",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_catalog_id(self, obj):
        snap = obj.pricing_snapshot or {}
        return snap.get("catalog_id") or obj.plan.catalog_id

    @extend_schema_field(serializers.BooleanField())
    def get_admission_waived(self, obj):
        snap = obj.pricing_snapshot or {}
        return bool(snap.get("admission_waived"))
