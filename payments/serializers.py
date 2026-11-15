from rest_framework import serializers

from payments.models import Payment, PaymentSession


class SessionInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["first_purchase", "renew", "change_plan"])
    plan_id = serializers.UUIDField()
    checkout = serializers.ChoiceField(choices=["sdk", "hosted"], default="hosted")


class PlanInput(serializers.Serializer):
    plan_id = serializers.UUIDField()


class SessionSerializer(serializers.ModelSerializer):
    plan_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = PaymentSession
        fields = ["tran_id", "kind", "plan_id", "amount_taka", "status", "gateway_url", "paid_at"]


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
