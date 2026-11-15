from django.utils import timezone
from rest_framework import serializers


class MonthInput(serializers.Serializer):
    year = serializers.IntegerField(min_value=2020, max_value=2100, required=False)
    month = serializers.IntegerField(min_value=1, max_value=12, required=False)

    def validate(self, attrs):
        attrs.setdefault("year", timezone.localdate().year)
        attrs.setdefault("month", timezone.localdate().month)
        return attrs


class CheckInInput(serializers.Serializer):
    member_id = serializers.CharField(max_length=24)
    checked_in_at = serializers.DateTimeField(required=False)
    source = serializers.ChoiceField(choices=["device", "admin", "manual"], default="device")


class MonthOutput(serializers.Serializer):
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    attended_days = serializers.ListField(child=serializers.DateField())
    visit_count = serializers.IntegerField()
    closed_weekday = serializers.IntegerField()


class CheckInOutput(serializers.Serializer):
    member_uuid = serializers.UUIDField()
    member_id = serializers.CharField()
    day = serializers.DateField()
    recorded = serializers.BooleanField()
    checked_in_at = serializers.DateTimeField()
