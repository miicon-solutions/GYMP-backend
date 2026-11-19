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
    checked_out_at = serializers.DateTimeField(required=False)
    action = serializers.ChoiceField(choices=["check_in", "check_out"], default="check_in", required=False)
    source = serializers.ChoiceField(choices=["device", "admin", "manual"], default="device")


class MemberSessionAdjustInput(serializers.Serializer):
    date = serializers.DateField(required=False)
    action = serializers.ChoiceField(
        choices=["check_out", "adjust_duration"], default="adjust_duration", required=False
    )
    duration_minutes = serializers.IntegerField(min_value=5, max_value=360, required=False)
    checked_out_at = serializers.DateTimeField(required=False)


class AttendanceSessionItemSerializer(serializers.Serializer):
    date = serializers.DateField()
    checked_in_at = serializers.DateTimeField()
    checked_out_at = serializers.DateTimeField(allow_null=True)
    duration_minutes = serializers.IntegerField()
    auto_closed = serializers.BooleanField()
    check_out_source = serializers.CharField(allow_blank=True)
    is_active_session = serializers.BooleanField()


class MotivationInsightSerializer(serializers.Serializer):
    category = serializers.CharField()
    title = serializers.CharField()
    title_bn = serializers.CharField()
    body = serializers.CharField()
    body_bn = serializers.CharField()
    tone = serializers.CharField()


class MotivationStatusSerializer(serializers.Serializer):
    current_streak = serializers.IntegerField()
    longest_streak = serializers.IntegerField()
    protected_rest_days = serializers.IntegerField()
    days_since_last_activity = serializers.IntegerField(allow_null=True)
    today_is_protected = serializers.BooleanField()
    today_protection_reason = serializers.CharField(allow_blank=True)
    today_protection_reason_bn = serializers.CharField(allow_blank=True)
    avatar_mood = serializers.CharField()
    avatar_name = serializers.CharField()
    headline = serializers.CharField()
    headline_bn = serializers.CharField()
    subheadline = serializers.CharField()
    subheadline_bn = serializers.CharField()
    notifications_enabled = serializers.BooleanField()
    notification_frequency = serializers.CharField()
    workouts_this_week = serializers.IntegerField()
    prs_this_month = serializers.IntegerField()
    insights = MotivationInsightSerializer(many=True)


class MonthOutput(serializers.Serializer):
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    attended_days = serializers.ListField(child=serializers.DateField())
    visit_count = serializers.IntegerField()
    closed_weekday = serializers.IntegerField()
    today_minutes = serializers.IntegerField(required=False)
    week_minutes = serializers.IntegerField(required=False)
    week_hours = serializers.FloatField(required=False)
    auto_cap_minutes = serializers.IntegerField(required=False)
    sessions = AttendanceSessionItemSerializer(many=True, required=False)
    motivation = MotivationStatusSerializer(required=False)


class CheckInOutput(serializers.Serializer):
    member_uuid = serializers.UUIDField()
    member_id = serializers.CharField()
    day = serializers.DateField()
    recorded = serializers.BooleanField()
    checked_in_at = serializers.DateTimeField()
    last_punch_at = serializers.DateTimeField(required=False)
    checked_out_at = serializers.DateTimeField(allow_null=True, required=False)
    duration_minutes = serializers.IntegerField(allow_null=True, required=False)
    exit_only_record = serializers.BooleanField(required=False)
