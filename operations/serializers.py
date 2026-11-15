from rest_framework import serializers

from accounts.serializers import PhoneField
from operations.models import Activity, Cost, Holiday


class StaffInput(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    phone_e164 = PhoneField()
    is_active = serializers.BooleanField(default=True)


class StaffSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    short_id = serializers.CharField(source="staff_profile.short_id")
    name = serializers.CharField(source="full_name")
    phone_e164 = serializers.CharField()
    is_active = serializers.BooleanField()
    is_super = serializers.BooleanField(source="is_superuser")
    mfa_enrolled = serializers.SerializerMethodField()

    def get_mfa_enrolled(self, obj) -> bool:
        return bool(obj.staff_profile.mfa_enrolled_at)


class CostSerializer(serializers.ModelSerializer):
    clear_note = serializers.BooleanField(write_only=True, required=False)

    class Meta:
        model = Cost
        fields = [
            "id",
            "title",
            "category",
            "amount_taka",
            "date",
            "note",
            "is_archived",
            "created_by",
            "created_at",
            "updated_at",
            "clear_note",
        ]
        read_only_fields = ["is_archived", "created_by", "created_at", "updated_at"]

    def validate(self, attrs):
        if attrs.pop("clear_note", False):
            attrs["note"] = None
        return attrs


class ActivitySerializer(serializers.ModelSerializer):
    at = serializers.DateTimeField(source="created_at")
    admin_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Activity
        fields = [
            "id",
            "at",
            "admin_id",
            "admin_name",
            "admin_short_id",
            "area",
            "action",
            "summary_key",
            "summary_params",
        ]


class WeekdayInput(serializers.Serializer):
    weekday = serializers.IntegerField(min_value=1, max_value=7)
    is_open = serializers.BooleanField()
    open_time = serializers.TimeField(required=False, allow_null=True, format="%H:%M")
    close_time = serializers.TimeField(required=False, allow_null=True, format="%H:%M")


class WeekInput(serializers.Serializer):
    week = WeekdayInput(many=True)


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ["id", "date", "name"]


class GymHoursOutput(serializers.Serializer):
    week = WeekdayInput(many=True)
    holidays = HolidaySerializer(many=True)


class GymStatusOutput(serializers.Serializer):
    timezone = serializers.CharField()
    is_open_now = serializers.BooleanField()
    status = serializers.ChoiceField(choices=["open", "closed"])
    today_weekday = serializers.IntegerField()
    today_is_holiday = serializers.BooleanField()
    today_holiday_name = serializers.CharField(allow_null=True)
    today_is_weekly_closed = serializers.BooleanField()
    today_open_time = serializers.CharField(allow_null=True)
    today_close_time = serializers.CharField(allow_null=True)
    hours_summary = serializers.CharField()
    closed_day_label = serializers.CharField(allow_null=True)
    week = WeekdayInput(many=True)
    upcoming_holidays = HolidaySerializer(many=True)
