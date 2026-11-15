from django.urls import path
from django.utils import timezone
from drf_spectacular.utils import PolymorphicProxySerializer

from accounts import serializers as s
from accounts import services
from accounts.crypto import digest
from accounts.models import RefreshSession
from core.endpoints import endpoint


def logout(request, data):
    RefreshSession.objects.filter(token_hash=digest(data["refresh_token"]), revoked_at=None).update(
        revoked_at=timezone.now()
    )


urlpatterns = [
    path(
        "resolve-phone/",
        endpoint(
            "auth_resolve_phone",
            response=s.PhoneOutput,
            handler=lambda r, d: services.resolve_phone(d["phone_e164"]),
            request=s.PhoneInput,
        ),
    ),
    path(
        "otp/send/",
        endpoint(
            "auth_otp_send",
            response=s.OTPOutput,
            handler=lambda r, d: services.send_otp(d, r.user),
            request=s.OTPInput,
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
        ),
    ),
    path(
        "google/link-phone/",
        endpoint(
            "auth_google_link_phone",
            response=s.TokenOutput,
            handler=lambda r, d: services.link_google_phone(d),
            request=s.GoogleLinkInput,
        ),
    ),
    path(
        "admin/unlock/",
        endpoint(
            "auth_admin_unlock",
            response=s.TokenOutput,
            handler=lambda r, d: services.mfa_action(d, "unlock"),
            request=s.UnlockInput,
        ),
    ),
    path(
        "admin/mfa/setup/",
        endpoint(
            "auth_admin_mfa_setup",
            response=s.MFAOutput,
            handler=lambda r, d: services.mfa_action(d, "setup"),
            request=s.SetupInput,
        ),
    ),
    path(
        "admin/mfa/confirm/",
        endpoint(
            "auth_admin_mfa_confirm",
            response=s.TokenOutput,
            handler=lambda r, d: services.mfa_action(d, "confirm"),
            request=s.ConfirmInput,
        ),
    ),
    path(
        "refresh/",
        endpoint(
            "auth_refresh",
            response=s.TokenOutput,
            handler=lambda r, d: services.rotate_refresh(d["refresh_token"]),
            request=s.RefreshInput,
        ),
    ),
    path(
        "logout/",
        endpoint("auth_logout", logout, request=s.RefreshInput, status=204, response=None),
    ),
]
