from django.urls import path
from django.utils import timezone
from drf_spectacular.utils import OpenApiExample, PolymorphicProxySerializer

from accounts import serializers as s
from accounts import services
from accounts.crypto import digest
from accounts.models import RefreshSession
from core.endpoints import endpoint


def logout(request, data):
    RefreshSession.objects.filter(token_hash=digest(data["refresh_token"]), revoked_at=None).update(
        revoked_at=timezone.now()
    )


_OTP_SEND_EXAMPLES = [
    OpenApiExample(
        "Onboarding OTP",
        value={"phone_e164": "+8801712345678", "purpose": "onboarding"},
        request_only=True,
    ),
]
_OTP_SEND_RESPONSE = [
    OpenApiExample(
        "OTP session created",
        value={
            "otp_session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "expires_in_sec": 300,
            "resend_after_sec": 24,
            "dev_bypass": True,
        },
        response_only=True,
    ),
]
_OTP_VERIFY_EXAMPLES = [
    OpenApiExample(
        "Verify OTP",
        value={
            "otp_session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "code": "000000",
        },
        request_only=True,
    ),
]
_TOKEN_RESPONSE = [
    OpenApiExample(
        "Authenticated",
        value={
            "access_token": "<jwt>",
            "refresh_token": "<opaque>",
            "token_type": "Bearer",
            "expires_in_sec": 3600,
            "member": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "member_id": "PF-0001",
                "phone_e164": "+8801712345678",
                "full_name": "",
                "email": None,
                "signed_in_with_google": False,
                "profile_complete": False,
                "membership_status": "none",
            },
        },
        response_only=True,
    ),
]
_REFRESH_EXAMPLES = [
    OpenApiExample(
        "Rotate refresh",
        value={"refresh_token": "<opaque refresh token>"},
        request_only=True,
    ),
]


urlpatterns = [
    path(
        "resolve-phone/",
        endpoint(
            "auth_resolve_phone",
            response=s.PhoneOutput,
            handler=lambda r, d: services.resolve_phone(d["phone_e164"]),
            request=s.PhoneInput,
            tags=["auth"],
            examples=[
                OpenApiExample(
                    "Resolve phone",
                    value={"phone_e164": "+8801712345678"},
                    request_only=True,
                ),
            ],
        ),
    ),
    path(
        "otp/send/",
        endpoint(
            "auth_otp_send",
            response=s.OTPOutput,
            handler=lambda r, d: services.send_otp(d, r.user),
            request=s.OTPInput,
            tags=["auth"],
            examples=_OTP_SEND_EXAMPLES + _OTP_SEND_RESPONSE,
        ),
    ),
    path(
        "otp/verify/",
        endpoint(
            "auth_otp_verify",
            response=PolymorphicProxySerializer(
                component_name="OTPVerification",
                serializers=[s.TokenOutput, s.ProofOutput],
                resource_type_field_name=None,
            ),
            handler=lambda r, d: services.verify_otp(d, r.user),
            request=s.VerifyInput,
            tags=["auth"],
            examples=_OTP_VERIFY_EXAMPLES + _TOKEN_RESPONSE,
        ),
    ),
    path(
        "google/",
        endpoint(
            "auth_google",
            response=PolymorphicProxySerializer(
                component_name="GoogleSignIn",
                serializers=[s.GooglePendingOutput, s.GoogleOutput],
                resource_type_field_name="status",
            ),
            handler=lambda r, d: services.google_login(d["id_token"]),
            request=s.GoogleInput,
            tags=["auth"],
            examples=[
                OpenApiExample(
                    "Google id_token",
                    value={"id_token": "<firebase-or-google-id-token>"},
                    request_only=True,
                ),
            ],
        ),
    ),
    path(
        "google/link-phone/",
        endpoint(
            "auth_google_link_phone",
            response=s.TokenOutput,
            handler=lambda r, d: services.link_google_phone(d),
            request=s.GoogleLinkInput,
            tags=["auth"],
        ),
    ),
    path(
        "admin/unlock/",
        endpoint(
            "auth_admin_unlock",
            response=s.TokenOutput,
            handler=lambda r, d: services.mfa_action(d, "unlock"),
            request=s.UnlockInput,
            tags=["auth"],
            examples=[
                OpenApiExample(
                    "Staff unlock",
                    value={"phone_e164": "+8801700000000", "totp_code": "123456"},
                    request_only=True,
                ),
            ],
        ),
    ),
    path(
        "admin/mfa/setup/",
        endpoint(
            "auth_admin_mfa_setup",
            response=s.MFAOutput,
            handler=lambda r, d: services.mfa_action(d, "setup"),
            request=s.SetupInput,
            tags=["auth"],
        ),
    ),
    path(
        "admin/mfa/confirm/",
        endpoint(
            "auth_admin_mfa_confirm",
            response=s.TokenOutput,
            handler=lambda r, d: services.mfa_action(d, "confirm"),
            request=s.ConfirmInput,
            tags=["auth"],
        ),
    ),
    path(
        "register/",
        endpoint(
            "auth_register",
            response=s.AuthTokenOutput,
            handler=lambda r, d: services.register_user(d),
            request=s.RegisterInput,
            status=201,
            tags=["auth"],
        ),
    ),
    path(
        "login/",
        endpoint(
            "auth_login",
            response=s.AuthTokenOutput,
            handler=lambda r, d: services.login_user(d),
            request=s.LoginInput,
            tags=["auth"],
        ),
    ),
    path(
        "refresh/",
        endpoint(
            "auth_refresh",
            response=s.TokenOutput,
            handler=lambda r, d: services.rotate_refresh(d["refresh_token"]),
            request=s.RefreshInput,
            tags=["auth"],
            examples=_REFRESH_EXAMPLES + _TOKEN_RESPONSE,
        ),
    ),
    path(
        "logout/",
        endpoint(
            "auth_logout",
            logout,
            request=s.RefreshInput,
            status=204,
            response=None,
            tags=["auth"],
            examples=_REFRESH_EXAMPLES,
        ),
    ),
]
