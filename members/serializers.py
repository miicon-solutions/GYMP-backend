import unicodedata

from rest_framework import serializers

from accounts.serializers import MemberOutput, PhoneField
from operations.serializers import GymStatusOutput
from payments.serializers import PaymentSerializer


class BloodGroupField(serializers.ChoiceField):
    def to_internal_value(self, data):
        return super().to_internal_value(str(data).replace("−", "-"))


class ProfileInput(serializers.Serializer):
    full_name = serializers.CharField(min_length=2, max_length=50)
    emergency_name = serializers.CharField(min_length=2, max_length=50)
    emergency_relationship = serializers.ChoiceField(
        choices=["parent", "spouse", "sibling", "friend", "other"]
    )
    emergency_phone_e164 = PhoneField()
    blood_group = BloodGroupField(
        choices=["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "Unknown"]
    )

    def validate(self, attrs):
        for field in ("full_name", "emergency_name"):
            name = attrs[field]
            if not name[0].isalpha() or any(
                not (unicodedata.category(c)[0] in "LM" or c.isspace() or c in "'.-") for c in name
            ):
                raise serializers.ValidationError({field: "Enter a valid name."})
            attrs[field] = name
        return attrs


class PhotoInput(serializers.Serializer):
    photo = serializers.FileField()


class FingerprintInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=["pending", "ready", "failed"])


class ProfileOutput(MemberOutput):
    emergency_name = serializers.CharField(allow_blank=True)
    emergency_relationship = serializers.CharField(allow_blank=True)
    emergency_phone_e164 = serializers.CharField(allow_blank=True)
    blood_group = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


class PlanBrief(serializers.Serializer):
    id = serializers.UUIDField()
    catalog_id = serializers.CharField(allow_null=True)
    name = serializers.CharField()


class AdminMemberOutput(ProfileOutput):
    fingerprint_status = serializers.CharField()
    plan = PlanBrief(allow_null=True)
    expires_on = serializers.DateField(allow_null=True)
    last_paid_at = serializers.DateTimeField(allow_null=True)


class RecoveryOutput(serializers.Serializer):
    sent = serializers.BooleanField()
    dev_bypass = serializers.BooleanField(required=False)


class DashboardOutput(GymStatusOutput):
    member_id = serializers.CharField()
    full_name = serializers.CharField()
    plan = PlanBrief(allow_null=True)
    status = serializers.CharField()
    expires_on = serializers.DateField(allow_null=True)
    days_left = serializers.IntegerField(allow_null=True)
    visits_this_month = serializers.IntegerField()
    last_check_in_at = serializers.DateTimeField(allow_null=True)
    fingerprint_status = serializers.CharField()
    gym_status = serializers.CharField()
    payment_preview = PaymentSerializer(many=True)
    has_unread_notifications = serializers.BooleanField()

    def get_fields(self):
        fields = super().get_fields()
        fields.pop("today_weekday", None)
        return fields
