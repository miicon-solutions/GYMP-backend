from datetime import timedelta
from unittest.mock import patch

import jwt
import pyotp
import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from accounts.crypto import decrypt_secret, digest, issue_jwt
from accounts.models import Challenge, RefreshSession, User
from accounts.services import begin_mfa, issue_tokens, rotate_refresh, send_otp
from core.api import BadGateway

pytestmark = pytest.mark.django_db
BASE = "/api/v1/auth/"


def send(client, phone="+8801712345678", purpose="onboarding", **extra):
    return client.post(
        BASE + "otp/send/", {"phone_e164": phone, "purpose": purpose, **extra}, format="json"
    )


def test_onboarding_tokens_refresh_and_logout(client):
    response = send(client)
    assert response.status_code == 200
    assert response.data["dev_bypass"] is True
    otp = response.data["otp_session_id"]
    row = Challenge.objects.get(pk=otp)
    assert row.code_hash == digest(f"{otp}:000000")
    login = client.post(
        BASE + "otp/verify/", {"otp_session_id": otp, "code": "000000"}, format="json"
    )
    assert login.status_code == 200
    assert login.data["member"]["profile_complete"] is False
    assert RefreshSession.objects.get().token_hash == digest(login.data["refresh_token"])
    assert (
        client.post(
            BASE + "otp/verify/", {"otp_session_id": otp, "code": "000000"}, format="json"
        ).status_code
        == 400
    )
    refresh = client.post(
        BASE + "refresh/", {"refresh_token": login.data["refresh_token"]}, format="json"
    )
    assert refresh.status_code == 200
    assert refresh.data["refresh_token"] != login.data["refresh_token"]
    assert (
        client.post(
            BASE + "refresh/", {"refresh_token": login.data["refresh_token"]}, format="json"
        ).status_code
        == 401
    )
    assert (
        client.post(
            BASE + "logout/", {"refresh_token": refresh.data["refresh_token"]}, format="json"
        ).status_code
        == 204
    )
    assert (
        client.post(
            BASE + "refresh/", {"refresh_token": refresh.data["refresh_token"]}, format="json"
        ).status_code
        == 401
    )


def test_otp_attempts_persist(client):
    otp = send(client).data["otp_session_id"]
    for _ in range(5):
        assert (
            client.post(
                BASE + "otp/verify/", {"otp_session_id": otp, "code": "999999"}, format="json"
            ).status_code
            == 400
        )
    assert Challenge.objects.get(pk=otp).attempts == 5
    response = client.post(
        BASE + "otp/verify/", {"otp_session_id": otp, "code": "000000"}, format="json"
    )
    assert response.status_code == 429
    assert "Retry-After" in response


def test_otp_expiration_resend_and_cross_role(client, staff):
    assert send(client, staff.phone_e164).status_code == 409
    assert (
        client.post(BASE + "resolve-phone/", {"phone_e164": staff.phone_e164}, format="json").data[
            "kind"
        ]
        == "staff"
    )
    response = send(client)
    assert send(client).status_code == 429
    row = Challenge.objects.get(pk=response.data["otp_session_id"])
    row.expires_at = timezone.now() - timedelta(seconds=1)
    row.save()
    assert (
        client.post(
            BASE + "otp/verify/", {"otp_session_id": str(row.pk), "code": "000000"}, format="json"
        ).status_code
        == 400
    )
    staff.is_active = False
    staff.save()
    assert (
        client.post(
            BASE + "resolve-phone/", {"phone_e164": staff.phone_e164}, format="json"
        ).status_code
        == 403
    )


@pytest.mark.parametrize("phone", ["01712345678", "+8801212345678", "bad", "+8811712345678"])
def test_invalid_phone(client, phone):
    assert send(client, phone).status_code == 400


def test_phone_change_actor_binding(client, member, other_member):
    client.force_authenticate(member)
    current = send(client, member.phone_e164, "confirmCurrentPhone")
    assert current.status_code == 200
    otp = current.data["otp_session_id"]
    client.force_authenticate(other_member)
    assert (
        client.post(
            BASE + "otp/verify/", {"otp_session_id": otp, "code": "000000"}, format="json"
        ).status_code
        == 404
    )
    client.force_authenticate(member)
    proof = client.post(
        BASE + "otp/verify/", {"otp_session_id": otp, "code": "000000"}, format="json"
    ).data["phone_proof_token"]
    newer = send(client, "+8801312345678", "changePhone", current_phone_proof=proof)
    assert newer.status_code == 200
    changed = client.post(
        BASE + "otp/verify/",
        {"otp_session_id": newer.data["otp_session_id"], "code": "000000"},
        format="json",
    )
    assert changed.status_code == 200
    token = changed.data["phone_proof_token"]
    response = client.post(
        "/api/v1/member/profile/phone/change/", {"phone_proof_token": token}, format="json"
    )
    assert response.status_code == 200
    assert response.data["phone_e164"] == "+8801312345678"
    assert (
        client.post(
            "/api/v1/member/profile/phone/change/", {"phone_proof_token": token}, format="json"
        ).status_code
        == 400
    )
    client.force_authenticate(None)
    client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
    assert client.get("/api/v1/member/profile/").status_code == 401


def test_scoped_otp_requires_auth(client, member):
    assert send(client, member.phone_e164, "confirmCurrentPhone").status_code == 401
    assert (
        send(
            client, "+8801312345678", "adminLinkMemberPhone", target_member_id=str(member.pk)
        ).status_code
        == 403
    )


def test_admin_phone_link_bound_to_actor_and_target(client, staff, super_admin, member):
    client.force_authenticate(staff)
    pending = send(
        client, "+8801312345678", "adminLinkMemberPhone", target_member_id=str(member.pk)
    )
    assert pending.status_code == 200
    body = {"otp_session_id": pending.data["otp_session_id"], "code": "000000"}
    assert client.post(BASE + "otp/verify/", body, format="json").status_code == 400
    client.force_authenticate(super_admin)
    assert (
        client.post(f"/api/v1/admin/members/{member.pk}/phone/", body, format="json").status_code
        == 404
    )
    client.force_authenticate(staff)
    response = client.post(f"/api/v1/admin/members/{member.pk}/phone/", body, format="json")
    assert response.status_code == 200
    assert response.data["phone_e164"] == "+8801312345678"


def test_google_onboarding_and_link(client, member, settings):
    settings.FIREBASE_CREDENTIALS_FILE = "/configured.json"
    identity = {"uid": "google-1", "email": "test@example.com", "name": "Google Member"}
    with patch("accounts.providers.verify_google", return_value=identity):
        google = client.post(BASE + "google/", {"id_token": "opaque"}, format="json")
        assert google.status_code == 200 and google.data["status"] == "needsPhoneLink"
        otp = send(client).data["otp_session_id"]
        response = client.post(
            BASE + "google/link-phone/",
            {
                "google_session_id": google.data["google_session_id"],
                "otp_session_id": otp,
                "code": "000000",
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.data["member"]["signed_in_with_google"] is True
        again = client.post(BASE + "google/", {"id_token": "opaque"}, format="json")
        assert again.data["status"] == "authenticated"
        assert User.objects.filter(role="member").count() == 1


def test_google_hidden_without_firebase(client, member, settings):
    settings.FIREBASE_CREDENTIALS_FILE = ""
    config = client.get("/api/v1/public/config/")
    assert config.status_code == 200
    assert config.data == {"google_sign_in": False}
    denied = client.post(BASE + "google/", {"id_token": "opaque"}, format="json")
    assert denied.status_code == 404
    assert denied.data["detail"] == "Google sign-in is not available."
    link = client.post(
        BASE + "google/link-phone/",
        {
            "google_session_id": "00000000-0000-0000-0000-000000000001",
            "otp_session_id": "00000000-0000-0000-0000-000000000002",
            "code": "000000",
        },
        format="json",
    )
    assert link.status_code == 404
    client.force_authenticate(member)
    profile = client.post(
        "/api/v1/member/profile/link-google/", {"id_token": "opaque"}, format="json"
    )
    assert profile.status_code == 404
    assert profile.data["detail"] == "Google sign-in is not available."
    settings.FIREBASE_CREDENTIALS_FILE = "/configured.json"
    assert client.get("/api/v1/public/config/").data == {"google_sign_in": True}


def test_google_link_conflict_and_inactive(client, member, other_member):
    identity = {"uid": "linked", "email": "linked@example.com", "name": "Linked"}
    other_member.firebase_uid = identity["uid"]
    other_member.email = identity["email"]
    other_member.save()
    client.force_authenticate(member)
    with patch("accounts.providers.verify_google", return_value=identity):
        assert (
            client.post(
                "/api/v1/member/profile/link-google/", {"id_token": "opaque"}, format="json"
            ).status_code
            == 409
        )
    client.force_authenticate(None)
    other_member.is_active = False
    other_member.save()
    with patch("accounts.providers.verify_google", return_value=identity):
        assert (
            client.post(BASE + "google/", {"id_token": "opaque"}, format="json").status_code == 403
        )


def test_mfa_setup_confirm_replay_and_unlock(client, staff):
    setup = begin_mfa(staff)
    body = {"phone_e164": staff.phone_e164, "setup_token": setup["setup_token"]}
    response = client.post(BASE + "admin/mfa/setup/", body, format="json")
    assert response.status_code == 200
    secret = response.data["secret_base32"]
    staff.staff_profile.refresh_from_db()
    assert secret not in staff.staff_profile.totp_secret_encrypted
    assert decrypt_secret(staff.staff_profile.totp_secret_encrypted) == secret
    body["totp_code"] = pyotp.TOTP(secret).now()
    assert client.post(BASE + "admin/mfa/confirm/", body, format="json").status_code == 200
    assert (
        client.post(
            BASE + "admin/unlock/",
            {"phone_e164": staff.phone_e164, "totp_code": body["totp_code"]},
            format="json",
        ).status_code
        == 401
    )
    staff.staff_profile.refresh_from_db()
    staff.staff_profile.totp_last_step -= 2
    staff.staff_profile.save()
    assert (
        client.post(
            BASE + "admin/unlock/",
            {"phone_e164": staff.phone_e164, "totp_code": body["totp_code"]},
            format="json",
        ).status_code
        == 200
    )
    assert client.post(BASE + "admin/mfa/confirm/", body, format="json").status_code == 400


def test_mfa_unenrolled_and_expired_setup(client, staff):
    assert (
        client.post(
            BASE + "admin/unlock/",
            {"phone_e164": staff.phone_e164, "totp_code": "123456"},
            format="json",
        ).status_code
        == 403
    )
    setup = begin_mfa(staff)
    p = staff.staff_profile
    p.setup_expires_at = timezone.now() - timedelta(seconds=1)
    p.save()
    assert (
        client.post(
            BASE + "admin/mfa/setup/",
            {"phone_e164": staff.phone_e164, "setup_token": setup["setup_token"]},
            format="json",
        ).status_code
        == 400
    )


def test_access_token_validation(client, member):
    token = issue_jwt(member)
    client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
    assert client.get("/api/v1/member/profile/").status_code == 200
    member.is_active = False
    member.save()
    assert client.get("/api/v1/member/profile/").status_code == 401
    claims = {
        "sub": str(member.pk),
        "typ": "access",
        "iat": timezone.now(),
        "exp": timezone.now() - timedelta(seconds=1),
    }
    expired = jwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")
    client.credentials(HTTP_AUTHORIZATION="Bearer " + expired)
    assert client.get("/api/v1/member/profile/").status_code == 401
    client.credentials(HTTP_AUTHORIZATION="Basic invalid")
    assert client.get("/api/v1/member/profile/").status_code == 401


def test_refresh_expired_or_inactive(member):
    pair = issue_tokens(member)
    RefreshSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(AuthenticationFailed):
        rotate_refresh(pair["refresh_token"])
    pair = issue_tokens(member)
    member.is_active = False
    member.save()
    with pytest.raises(AuthenticationFailed):
        rotate_refresh(pair["refresh_token"])


def test_sms_failure_invalidates_challenge(settings):
    settings.OTP_DEV_BYPASS = False
    with patch("accounts.providers.send_sms", side_effect=BadGateway()):
        with pytest.raises(BadGateway):
            send_otp({"phone_e164": "+8801712345678", "purpose": "onboarding"})
    assert Challenge.objects.get().consumed_at is not None


def test_signup_member_id_is_temporary():
    from accounts.services import new_member

    first = new_member("+8801712555666")
    second = new_member("+8801712555667")
    assert first.member_profile.member_id == "PFT-000001"
    assert second.member_profile.member_id == "PFT-000002"
