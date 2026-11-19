from rest_framework import serializers

from accounts.crypto import normalize_phone


class PhoneField(serializers.CharField):
    def to_internal_value(self, data):
        try:
            return normalize_phone(super().to_internal_value(data))
        except serializers.ValidationError as exc:
            raise serializers.ValidationError("Enter a valid phone number.") from exc


class PhoneInput(serializers.Serializer):
    phone_e164 = PhoneField()


class OTPInput(PhoneInput):
    purpose = serializers.ChoiceField(
        choices=["onboarding", "confirmCurrentPhone", "changePhone", "adminLinkMemberPhone"]
    )
    current_phone_proof = serializers.CharField(required=False, max_length=2000)
    target_member_id = serializers.UUIDField(required=False)


class VerifyInput(serializers.Serializer):
    otp_session_id = serializers.UUIDField()
    code = serializers.RegexField(r"^[0-9]{6}$")


class GoogleInput(serializers.Serializer):
    id_token = serializers.CharField(max_length=12000)


class GoogleLinkInput(VerifyInput):
    google_session_id = serializers.UUIDField()


class RefreshInput(serializers.Serializer):
    refresh_token = serializers.CharField(max_length=128)


class SetupInput(PhoneInput):
    setup_token = serializers.CharField(max_length=128)


class UnlockInput(PhoneInput):
    totp_code = serializers.RegexField(r"^[0-9]{6}$")


class ConfirmInput(SetupInput, UnlockInput):
    pass


class ProofInput(serializers.Serializer):
    phone_proof_token = serializers.CharField(max_length=2000)


class MemberOutput(serializers.Serializer):
    id = serializers.UUIDField()
    member_id = serializers.CharField()
    phone_e164 = serializers.CharField()
    full_name = serializers.CharField(allow_blank=True)
    email = serializers.EmailField(allow_null=True)
    signed_in_with_google = serializers.BooleanField()
    profile_complete = serializers.BooleanField()
    membership_status = serializers.CharField()


class StaffOutput(serializers.Serializer):
    id = serializers.UUIDField()
    short_id = serializers.CharField()
    name = serializers.CharField()
    phone_e164 = serializers.CharField()
    is_super = serializers.BooleanField()
    is_active = serializers.BooleanField()
    mfa_enrolled = serializers.BooleanField()
    permissions = serializers.ListField(child=serializers.CharField(), required=False)


class TokenOutput(serializers.Serializer):
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()
    token_type = serializers.CharField()
    expires_in_sec = serializers.IntegerField()
    member = MemberOutput(required=False)
    staff = StaffOutput(required=False)


class PhoneOutput(PhoneInput):
    kind = serializers.ChoiceField(choices=["unknown", "member", "staff"])
    staff_short_id = serializers.CharField(required=False)
    mfa_enrolled = serializers.BooleanField(required=False)


class OTPOutput(PhoneInput):
    otp_session_id = serializers.UUIDField()
    purpose = serializers.CharField()
    expires_in_sec = serializers.IntegerField()
    resend_after_sec = serializers.IntegerField()
    dev_bypass = serializers.BooleanField()


class ProofOutput(ProofInput):
    proof_kind = serializers.CharField()
    phone_e164 = serializers.CharField()


class GooglePendingOutput(serializers.Serializer):
    status = serializers.ChoiceField(choices=["needsPhoneLink"])
    google_session_id = serializers.UUIDField(required=False)
    email = serializers.EmailField(required=False)
    full_name = serializers.CharField(required=False)


class GoogleOutput(TokenOutput):
    status = serializers.ChoiceField(choices=["authenticated"])


class MFAOutput(PhoneInput):
    secret_base32 = serializers.CharField()
    otpauth_uri = serializers.CharField()
    issuer = serializers.CharField()
    account_name = serializers.CharField()


class MFAEnrollOutput(serializers.Serializer):
    staff_id = serializers.UUIDField()
    setup_token = serializers.CharField()
    expires_in_sec = serializers.IntegerField()


class RegisterInput(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6)
    full_name = serializers.CharField(required=False, allow_blank=True, default="")
    phone_e164 = serializers.CharField(required=False, allow_blank=True)


class LoginInput(serializers.Serializer):
    email = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)
    phone_e164 = serializers.CharField(required=False, allow_blank=True)


class AuthTokenOutput(TokenOutput):
    access = serializers.CharField(required=False)
    refresh = serializers.CharField(required=False)
