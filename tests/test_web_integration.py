from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from payments.models import Payment, PaymentSession
from plans.models import Offer, Plan

pytestmark = pytest.mark.django_db


def test_public_catalog_is_anonymous_active_pricing_only(client, plan):
    plan.is_active = True
    plan.save()
    Plan.objects.create(name="Hidden", duration_months=3, monthly_rate_taka=500, is_active=False)
    today = timezone.localdate()
    Offer.objects.create(
        plan=plan,
        name="Admission offer",
        starts_on=today,
        ends_on=today + timedelta(days=1),
        waive_admission=True,
    )
    response = client.get("/api/v1/public/plans/", HTTP_AUTHORIZATION="Bearer invalid")
    assert response.status_code == 200
    assert set(response.data) == {"next", "previous", "results"}
    assert len(response.data["results"]) == 1
    row = response.data["results"][0]
    assert row["id"] == str(plan.id)
    assert row["effective_first_payment_taka"] == row["effective_renewal_taka"] == 1500
    assert row["active_offer"]["name"] == "Admission offer"
    assert not ({"member_id", "phone_e164", "email"} & row.keys())
    assert client.post("/api/v1/public/plans/", {}).status_code == 405


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("outcome", ["success", "fail", "cancel"])
def test_trusted_web_payment_handoff_never_settles(settings, method, outcome):
    settings.WEB_APP_BASE_URL = "https://fitness.example.com"
    # Gateways can POST cross-site. This endpoint only redirects; it cannot settle payments.
    client = APIClient(enforce_csrf_checks=True)
    response = getattr(client, method)(
        f"/payments/return/{outcome}/?next=https://evil.example", {"tran_id": "GYMA-test-123"}
    )
    assert response.status_code == 302
    target = urlparse(response["Location"])
    assert target.scheme == "https" and target.netloc == "fitness.example.com"
    assert target.path == f"/payments/return/{outcome}"
    assert parse_qs(target.query) == {"tran_id": ["GYMA-test-123"]}
    assert response["Cache-Control"] == "no-store"
    assert not Payment.objects.exists() and not PaymentSession.objects.exists()


def test_web_return_rejects_unknown_outcome_and_encodes_reference(settings, client):
    settings.WEB_APP_BASE_URL = "https://fitness.example.com"
    assert client.get("/payments/return/unknown/").status_code == 404
    reference = "<script>&next=https://evil.example"
    response = client.get("/payments/return/success/", {"tran_id": reference})
    assert parse_qs(urlparse(response["Location"]).query) == {"tran_id": [reference[:30]]}
    assert "<script>" not in response["Location"]
    assert client.put("/payments/return/success/", {}).status_code == 405


def test_return_fallback_when_web_app_is_not_configured(settings, client):
    settings.WEB_APP_BASE_URL = ""
    response = client.post("/payments/return/success/", {"tran_id": "GYMA-test"})
    assert response.status_code == 200
    assert b"GYMA-test" in response.content
    assert not Payment.objects.exists()


def test_corrupt_png_returns_validation_error(client, member):
    import base64

    from django.core.files.uploadedfile import SimpleUploadedFile

    client.force_authenticate(member)
    # A recognizable PNG header whose compressed content fails Pillow verification.
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+XcQAAAABJRU5ErkJggg=="
    )
    response = client.post(
        "/api/v1/member/profile/photo/",
        {"photo": SimpleUploadedFile("bad.png", raw)},
        format="multipart",
    )
    assert response.status_code == 400
    assert "photo" in response.data


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:password@example.com",
        "https://example.com/path",
        "https://example.com?next=elsewhere",
        "javascript://example.com",
    ],
)
def test_web_origin_configuration_rejects_non_origins(origin):
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from unittest.mock import patch\nwith patch('environ.Env.read_env'):\n from config import settings",
        ],
        env={**os.environ, "APP_ENV": "local", "WEB_APP_BASE_URL": origin},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "WEB_APP_BASE_URL must be a web origin" in result.stderr
