import json
import os
import subprocess
import sys
from unittest.mock import patch

import httpx
import pytest
from django.test import RequestFactory
from rest_framework.exceptions import AuthenticationFailed

from accounts import providers
from accounts.crypto import decrypt_secret, encrypt_secret, encryption_key
from core.api import BadGateway
from core.network import client_ip
from core.uploads import BoundedUploadHandler, PayloadTooLarge
from payments import gateway
from payments.models import Payment
from payments.services import create_session, handle_ipn


def response(body, status=200):
    return httpx.Response(
        status, json=body, request=httpx.Request("GET", "https://provider.invalid")
    )


@pytest.mark.parametrize("body", [{"error": 1}, {"error": "0"}, [], {}])
def test_sms_rejects_bad_payloads(settings, body):
    settings.SMS_NET_BD_API_KEY = "test-key"
    with patch("accounts.providers.httpx.post", return_value=response(body)):
        with pytest.raises(BadGateway):
            providers.send_sms("+8801712345678", "123456")


def test_sms_form_and_timeout(settings):
    settings.SMS_NET_BD_API_KEY = "test-key"
    settings.SMS_NET_BD_SENDER_ID = "test-sender"
    with patch("accounts.providers.httpx.post", return_value=response({"error": 0})) as post:
        providers.send_sms("+8801712345678", "123456")
        assert post.call_args.kwargs["data"]["to"] == "8801712345678"
        assert post.call_args.kwargs["data"]["sender_id"] == "test-sender"
        assert post.call_args.kwargs["timeout"] == 10
    with patch("accounts.providers.httpx.post", side_effect=httpx.ReadTimeout("timeout")):
        with pytest.raises(BadGateway):
            providers.send_sms("+8801712345678", "123456")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"APIConnect": []},
        {"APIConnect": "DONE", "element": [None]},
        {"APIConnect": "DONE", "element": "bad"},
    ],
)
def test_gateway_query_malformed(settings, body):
    with patch("payments.gateway.call", return_value=body):
        with pytest.raises(BadGateway):
            gateway.query("tran")


def test_gateway_query_prefers_success():
    body = {
        "APIConnect": "DONE",
        "element": [{"status": "FAILED"}, {"status": "VALID", "tran_id": "tran"}],
    }
    with patch("payments.gateway.call", return_value=body):
        assert gateway.query("tran")["status"] == "VALID"
    with patch("payments.gateway.call", return_value={"APIConnect": "DONE", "element": []}):
        assert gateway.query("tran")["status"] == "PENDING"


def test_gateway_credentials_and_network_failure(settings):
    settings.SSLCOMMERZ_STORE_ID = "test-store"
    settings.SSLCOMMERZ_STORE_PASSWD = "test-password"
    with patch("payments.gateway.httpx.Client") as cls:
        client = cls.return_value.__enter__.return_value
        client.get.return_value = response({"status": "VALID"})
        assert gateway.validate("validation")["status"] == "VALID"
        assert client.get.call_args.kwargs["params"]["store_passwd"] == "test-password"
        client.get.side_effect = httpx.ReadTimeout("unavailable")
        with pytest.raises(BadGateway):
            gateway.validate("validation")
    settings.SSLCOMMERZ_STORE_ID = ""
    with pytest.raises(BadGateway):
        gateway.query("tran")


@pytest.mark.parametrize(
    "identity",
    [
        {
            "uid": "u",
            "email": "a@example.com",
            "email_verified": False,
            "firebase": {"sign_in_provider": "google.com"},
        },
        {
            "uid": "u",
            "email": "a@example.com",
            "email_verified": True,
            "firebase": {"sign_in_provider": "password"},
        },
        {"email_verified": True, "firebase": {"sign_in_provider": "google.com"}},
    ],
)
def test_firebase_rejects_other_providers_unverified_and_incomplete(identity, settings):
    settings.FIREBASE_CREDENTIALS_FILE = "/not-read.json"
    with (
        patch("accounts.providers.firebase_app"),
        patch("firebase_admin.auth.verify_id_token", return_value=identity),
    ):
        with pytest.raises(AuthenticationFailed):
            providers.verify_google("id-token")


def test_firebase_verifies_revocation(settings):
    settings.FIREBASE_CREDENTIALS_FILE = "/not-read.json"
    identity = {
        "uid": "u",
        "email": "a@example.com",
        "email_verified": True,
        "firebase": {"sign_in_provider": "google.com"},
    }
    with (
        patch("accounts.providers.firebase_app"),
        patch("firebase_admin.auth.verify_id_token", return_value=identity) as verifier,
    ):
        assert providers.verify_google("id-token") == identity
        assert verifier.call_args.kwargs["check_revoked"] is True


@pytest.mark.parametrize(
    "key", ["x" * 32, "00" * 32, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="]
)
def test_secret_encryption_supported_key_encodings(settings, key):
    settings.TOTP_ENCRYPTION_KEY = key
    assert len(encryption_key()) == 32
    encrypted = encrypt_secret("TOTPSECRET")
    assert encrypted != "TOTPSECRET"
    assert decrypt_secret(encrypted) == "TOTPSECRET"


def test_upload_handler_stops_before_storage():
    handler = BoundedUploadHandler()
    handler.new_file("photo", "file.jpg", "image/jpeg", None)
    assert handler.receive_data_chunk(b"x" * 1024, 0) == b"x" * 1024
    with pytest.raises(PayloadTooLarge):
        handler.receive_data_chunk(b"x" * (5 * 1024 * 1024), 1024)


def test_proxy_headers_only_trusted_when_configured(settings):
    request = RequestFactory().get(
        "/", REMOTE_ADDR="192.0.2.10", HTTP_X_FORWARDED_FOR="203.0.113.1"
    )
    assert client_ip(request) == "192.0.2.10"
    settings.TRUSTED_PROXY_IPS = ["192.0.2.10"]
    assert client_ip(request) == "203.0.113.1"
    request.META["HTTP_X_FORWARDED_FOR"] = "bad"
    assert client_ip(request) == "192.0.2.10"


def production_env():
    return {
        **os.environ,
        "APP_ENV": "prod",
        "DEBUG": "false",
        "DJANGO_SECRET_KEY": "private-test-django-key-that-is-long-enough",
        "JWT_SECRET": "private-test-jwt-key-that-is-long-enough",
        "TOTP_ENCRYPTION_KEY": "00" * 32,
        "FIREBASE_CREDENTIALS_FILE": "/not-read.json",
        "SMS_NET_BD_API_KEY": "dummy",
        "SSLCOMMERZ_STORE_ID": "dummy",
        "SSLCOMMERZ_STORE_PASSWD": "dummy",
        "ATTENDANCE_DEVICE_KEY": "dummy",
        "PUBLIC_BASE_URL": "https://example.test",
        "WEB_APP_BASE_URL": "https://example.test",
        "OTP_DEV_BYPASS": "true",
        "EMAIL_DEV_BYPASS": "true",
    }


def test_production_starts_without_firebase():
    env = production_env()
    env.pop("FIREBASE_CREDENTIALS_FILE", None)
    env.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config import settings as s; print(repr(s.FIREBASE_CREDENTIALS_FILE))",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "''"


def test_production_forces_bypasses_off():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json;from config import settings as s;print(json.dumps([s.OTP_DEV_BYPASS,s.EMAIL_DEV_BYPASS,s.SSLCOMMERZ_SANDBOX]))",
        ],
        env=production_env(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [False, False, False]


@pytest.mark.parametrize(
    "key",
    [
        "local-only-development-jwt-secret-change-before-deploy",
        "local-only-development-secret-change-before-deploy",
    ],
)
def test_production_rejects_published_keys(key):
    env = production_env()
    env["JWT_SECRET"] = key
    result = subprocess.run(
        [sys.executable, "-c", "from config import settings"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "private secret" in result.stderr


@pytest.mark.django_db
def test_browser_login_throttled_and_csrf_preserved(client):
    for _ in range(10):
        assert (
            client.post(
                "/admin/login/", {"username": "+8801712345678", "password": "wrong"}
            ).status_code
            == 200
        )
    denied = client.post("/admin/login/", {"username": "+8801712345678", "password": "wrong"})
    assert denied.status_code == 429 and "Retry-After" in denied
    from django.test import Client

    csrf_client = Client(enforce_csrf_checks=True)
    assert (
        csrf_client.post("/admin/login/", {"username": "anything", "password": "wrong"}).status_code
        == 403
    )


@pytest.mark.django_db
def test_negative_callback_is_confirmed_server_side(member, plan):
    p = member.member_profile
    p.profile_complete = True
    p.save()
    s = create_session(member, {"kind": "first_purchase", "plan_id": plan.pk, "checkout": "sdk"})
    with patch("payments.gateway.query", return_value={"status": "PENDING", "tran_id": s.tran_id}):
        handle_ipn({"tran_id": s.tran_id, "status": "FAILED"})
    s.refresh_from_db()
    assert s.status == "pending"
    result = {
        "status": "VALID",
        "tran_id": s.tran_id,
        "val_id": "valid",
        "amount": str(s.amount_taka),
        "currency": "BDT",
        "risk_level": "0",
    }
    with patch("payments.gateway.query", return_value=result):
        handle_ipn({"tran_id": s.tran_id, "status": "CANCELLED"})
    assert Payment.objects.count() == 1
    s.refresh_from_db()
    assert s.status == "paid"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "result",
    [
        {"status": "INVALID"},
        {"status": "FAILED", "tran_id": "unrelated"},
        {
            "status": "VALID",
            "tran_id": "unrelated",
            "val_id": "unrelated-valid-id",
            "amount": "2500.00",
            "currency": "BDT",
        },
    ],
)
def test_forged_positive_callback_cannot_fail_another_checkout(member, plan, result):
    p = member.member_profile
    p.profile_complete = True
    p.save()
    session = create_session(
        member, {"kind": "first_purchase", "plan_id": plan.pk, "checkout": "sdk"}
    )
    from rest_framework.exceptions import ValidationError

    with patch("payments.gateway.validate", return_value=result):
        try:
            handle_ipn(
                {"tran_id": session.tran_id, "status": "VALID", "val_id": "attacker-supplied"}
            )
        except ValidationError:
            pass
    session.refresh_from_db()
    assert session.status == "pending"
    assert not Payment.objects.exists()


def test_proxy_scheme_only_trusted_when_configured(settings):
    from core.middleware import TrustedProxyMiddleware

    request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.10", HTTP_X_FORWARDED_PROTO="https")
    middleware = TrustedProxyMiddleware(lambda request: request.is_secure())
    assert middleware(request) is False
    settings.TRUSTED_PROXY_IPS = ["192.0.2.10"]
    assert middleware(request) is True


@pytest.mark.django_db
def test_invalid_phone_errors_use_field_lists(client):
    response = client.post(
        "/api/v1/auth/otp/send/", {"phone_e164": "invalid", "purpose": "onboarding"}, format="json"
    )
    assert response.status_code == 400
    assert isinstance(response.data["phone_e164"], list)
    assert response.data["phone_e164"][0] == "Enter a valid phone number."


@pytest.mark.django_db
def test_non_ascii_totp_rejected_as_validation_error(client):
    response = client.post(
        "/api/v1/auth/admin/unlock/",
        {"phone_e164": "+8801712345678", "totp_code": "১২৩৪৫৬"},
        format="json",
    )
    assert response.status_code == 400
