from rest_framework import serializers

from plans.models import Offer, Plan
from plans.services import active_offer, pricing


class OfferSerializer(serializers.ModelSerializer):
    plan_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Offer
        fields = [
            "id",
            "plan_id",
            "name",
            "starts_on",
            "ends_on",
            "waive_admission",
            "extra_discount_type",
            "extra_discount_value",
            "is_active",
        ]


class PlanSerializer(serializers.ModelSerializer):
    duration_months = serializers.ChoiceField(choices=[1, 3, 6, 9, 12])
    catalog_id = serializers.CharField(read_only=True, allow_null=True)
    renewal_taka = serializers.IntegerField(read_only=True)
    period_coverage_taka = serializers.IntegerField(read_only=True)
    effective_renewal_taka = serializers.IntegerField(read_only=True)
    effective_first_payment_taka = serializers.IntegerField(read_only=True)
    first_payment_taka = serializers.IntegerField(read_only=True)
    active_offer = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = [
            "id",
            "name",
            "catalog_id",
            "monthly_rate_taka",
            "admission_fee_taka",
            "duration_months",
            "discount_type",
            "discount_value",
            "is_active",
            "renewal_taka",
            "period_coverage_taka",
            "effective_renewal_taka",
            "effective_first_payment_taka",
            "first_payment_taka",
            "active_offer",
        ]

    def get_active_offer(self, obj) -> dict | None:
        offer = active_offer(obj)
        return OfferSerializer(offer).data if offer else None

    def to_representation(self, instance):
        result = super().to_representation(instance)
        result.update(pricing(instance))
        return result


class PlanInput(PlanSerializer):
    """Writable plan fields; computed values cannot be supplied by clients."""

    def validate(self, attrs):
        if "catalog_id" in self.initial_data:
            raise serializers.ValidationError(
                {"catalog_id": "Catalog plans cannot be created through this API."}
            )
        if not self.partial:
            for key, value in {
                "discount_type": "none",
                "discount_value": 0,
                "admission_fee_taka": 0,
                "is_active": True,
            }.items():
                attrs.setdefault(key, value)
        return attrs


class OfferInput(OfferSerializer):
    def validate(self, attrs):
        if not self.partial:
            for key, value in {
                "extra_discount_type": "none",
                "extra_discount_value": 0,
                "waive_admission": False,
                "is_active": True,
            }.items():
                attrs.setdefault(key, value)
        return attrs
