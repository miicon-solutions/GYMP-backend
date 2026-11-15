from rest_framework import serializers

from payments.serializers import PaymentSerializer


class RevenueQuery(serializers.Serializer):
    def to_internal_value(self, data):
        if data.get("dates", "").strip():
            data = data.copy()
            data["range"] = "dates"
        return super().to_internal_value(data)

    range = serializers.ChoiceField(
        choices=["day", "week", "month", "overall", "custom", "dates"], default="month"
    )
    date = serializers.DateField(required=False)
    from_date = serializers.DateField(required=False)
    to = serializers.DateField(required=False)
    dates = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    member_id = serializers.UUIDField(required=False)
    channel = serializers.ChoiceField(choices=["all", "cash", "sslcommerz"], default="all")
    limit = serializers.IntegerField(default=50, min_value=1, max_value=100)

    def get_fields(self):
        fields = super().get_fields()
        fields["from"] = fields.pop("from_date")
        return fields


class RevenuePaymentOutput(PaymentSerializer):
    class Meta(PaymentSerializer.Meta):
        fields = PaymentSerializer.Meta.fields + ["member_id", "member_display_id", "member_name"]

    member_id = serializers.UUIDField()
    member_display_id = serializers.CharField()
    member_name = serializers.CharField()


class RevenuePoint(serializers.Serializer):
    bucket = serializers.CharField()
    amount_taka = serializers.IntegerField()
    count = serializers.IntegerField()


class RevenueOutput(serializers.Serializer):
    range = serializers.CharField()
    from_date = serializers.DateField(allow_null=True)
    to = serializers.DateField(allow_null=True)
    total_taka = serializers.IntegerField()
    payment_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    by_channel = serializers.DictField(child=serializers.IntegerField())
    by_plan = serializers.DictField(child=serializers.IntegerField())
    series = RevenuePoint(many=True)
    payments = RevenuePaymentOutput(many=True)

    def get_fields(self):
        fields = super().get_fields()
        fields["from"] = fields.pop("from_date")
        return fields
