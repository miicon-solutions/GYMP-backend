import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib import admin
from django.core.management import call_command
from django.db import IntegrityError, transaction
from drf_spectacular.generators import SchemaGenerator

from accounts.models import Challenge, User
from core.middleware import redact
from payments.models import Payment

pytestmark = pytest.mark.django_db


def add_payment(member, plan, at, channel="cash", amount=100, status="paid"):
    return Payment.objects.create(
        member=member.member_profile,
        plan=plan,
        channel=channel,
        kind="renewal",
        amount_taka=amount,
        paid_at=at,
        status=status,
    )


def test_revenue_ranges_sparse_dates_channels_and_full_aggregates(client, staff, member, plan):
    add_payment(member, plan, datetime(2026, 11, 1, 10, tzinfo=UTC), amount=100)
    add_payment(
        member, plan, datetime(2026, 11, 2, 10, tzinfo=UTC), channel="sslcommerz", amount=200
    )
    add_payment(member, plan, datetime(2026, 11, 3, 10, tzinfo=UTC), amount=400)
    add_payment(member, plan, datetime(2026, 11, 2, 10, tzinfo=UTC), amount=99, status="failed")
    client.force_authenticate(staff)
    url = "/api/v1/admin/revenue/"
    month = client.get(url, {"range": "month", "date": "2026-11-15", "limit": 1})
    assert month.status_code == 200
    assert month.data["total_taka"] == 700
    assert month.data["payment_count"] == 3 and month.data["failed_count"] == 1
    assert len(month.data["payments"]) == 1
    assert month.data["by_channel"] == {"cash": 500, "sslcommerz": 200}
    assert len(month.data["series"]) == 3
    sparse = client.get(url, {"range": "bad", "dates": "2026-11-01,2026-11-03,2026-11-01"})
    # Dates take precedence, including the range selector.
    assert sparse.status_code == 200
    assert sparse.data["range"] == "dates" and sparse.data["total_taka"] == 500
    assert client.get(url, {"range": "overall", "channel": "sslcommerz"}).data["total_taka"] == 200
    assert len(client.get(url, {"range": "week", "date": "2026-11-03"}).data["series"]) == 7
    assert (
        len(
            client.get(url, {"range": "custom", "from": "2026-01-01", "to": "2026-12-31"}).data[
                "series"
            ]
        )
        == 12
    )
    assert client.get(url, {"range": "day", "date": "2026-11-01"}).data["total_taka"] == 100
    assert (
        client.get(url, {"range": "custom", "from": "2026-12-31", "to": "2026-01-01"}).status_code
        == 400
    )
    assert client.get(url, {"range": "dates"}).status_code == 400
    assert client.get(url, {"dates": "bad"}).status_code == 400


def test_cursor_pagination_limits_and_stability(client, member):
    from plans.models import Offer, Plan

    # Staff/member listing a larger offer table exercises capped cursor pagination.
    p = Plan.objects.create(name="Test", duration_months=1, monthly_rate_taka=100)
    Offer.objects.bulk_create(
        [
            Offer(
                plan=p,
                name=f"Offer {i}",
                starts_on="2026-01-01",
                ends_on="2026-12-31",
                is_active=False,
            )
            for i in range(103)
        ]
    )
    from accounts.models import StaffProfile

    u = User.objects.create_user("+8801412345678", role="admin")
    StaffProfile.objects.create(user=u, short_id="S-PAGE")
    client.force_authenticate(u)
    url = f"/api/v1/admin/plans/{p.pk}/offers/"
    first = client.get(url, {"limit": 2})
    assert first.status_code == 200
    assert set(first.data) == {"next", "previous", "results"}
    assert len(first.data["results"]) == 2
    second = client.get(first.data["next"])
    assert {x["id"] for x in first.data["results"]}.isdisjoint(
        {x["id"] for x in second.data["results"]}
    )
    assert len(client.get(url, {"limit": 999}).data["results"]) == 100
    assert client.get(url, {"cursor": "invalid"}).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/terms/",
        "/privacy/",
        "/docs/",
        "/health/",
        "/health/live/",
        "/api/v1/welcome/",
        "/payments/return/success/",
    ],
)
def test_public_routes(client, path):
    assert client.get(path).status_code == 200


def test_health_failure_and_request_id(client):
    with patch(
        "core.public.connection.cursor", side_effect=RuntimeError("private connection failure")
    ):
        result = client.get("/health/")
    assert result.status_code == 503
    assert "private" not in result.content.decode()
    response = client.get("/health/live/", HTTP_X_REQUEST_ID="test-correlation")
    assert response["X-Request-ID"] == "test-correlation"
    assert (
        client.get("/health/live/", HTTP_X_REQUEST_ID="unsafe\nvalue")["X-Request-ID"]
        != "unsafe\nvalue"
    )


def test_return_html_is_escaped_and_does_not_settle(client):
    result = client.get("/payments/return/success/", {"tran_id": "<script>alert(1)</script>"})
    assert b"<script>alert" not in result.content
    assert not Payment.objects.exists()
    assert client.get("/payments/return/unknown/").status_code == 404


def test_permissions(client, member, staff):
    assert client.get("/api/v1/member/profile/").status_code == 401
    assert client.get("/api/v1/admin/staff/").status_code == 401
    client.force_authenticate(member)
    assert client.get("/api/v1/admin/staff/").status_code == 403
    client.force_authenticate(staff)
    assert client.get("/api/v1/member/profile/").status_code == 403


def test_model_constraints(member, plan):
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(member.phone_e164, role="admin")
    from plans.models import Plan

    with pytest.raises(IntegrityError), transaction.atomic():
        Plan.objects.create(
            name="Duplicate", duration_months=plan.duration_months, monthly_rate_taka=10
        )
    from attendance.models import CheckIn

    at = datetime(2026, 11, 1, tzinfo=UTC)
    CheckIn.objects.create(member=member.member_profile, checked_in_at=at, check_in_date=at.date())
    with pytest.raises(IntegrityError), transaction.atomic():
        CheckIn.objects.create(
            member=member.member_profile, checked_in_at=at, check_in_date=at.date()
        )


def test_admin_is_inspect_only_and_secrets_hidden(client, super_admin):
    client.force_login(super_admin)
    assert client.get("/admin/").status_code == 200
    url = f"/admin/accounts/user/{super_admin.pk}/change/"
    response = client.get(url)
    assert response.status_code == 200
    assert super_admin.password.encode() not in response.content
    assert b'name="password"' not in response.content
    for model, registered in admin.site._registry.items():
        if model._meta.app_label in {
            "accounts",
            "members",
            "plans",
            "payments",
            "operations",
            "attendance",
        }:
            request = type("R", (), {"user": super_admin})()
            assert not registered.has_add_permission(request)
            assert not registered.has_change_permission(request)
            assert not registered.has_delete_permission(request)
    assert Challenge not in admin.site._registry
    client.force_login(User.objects.create_user("+8801412345678", role="admin"))
    assert client.get("/admin/").status_code == 302


def test_log_redaction():
    assert redact({"access_token": "private", "safe": {"password": "private", "ok": "yes"}}) == {
        "access_token": "[redacted]",
        "safe": {"password": "[redacted]", "ok": "yes"},
    }


def test_schema_and_route_manifest():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    assert "/api/v1/auth/otp/verify/" in schema["paths"]
    assert "/api/v1/admin/revenue/" in schema["paths"]
    assert schema["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"
    assert schema["components"]["securitySchemes"]["deviceKey"]["name"] == "X-Device-Key"
    manifest = Path(__file__).resolve().parents[1] / "docs/route-map.json"
    import re

    def normalize(p):
        return re.sub(r"\{[^}]+\}", "*", p)

    actual = {
        (method.upper(), normalize(path))
        for path, ops in schema["paths"].items()
        for method in ops
        if method in {"get", "post", "put", "patch", "delete"}
    }
    for route in json.loads(manifest.read_text()):
        if route["new"].startswith("/api/v1/"):
            assert (route["method"], normalize(route["new"])) in actual, route


def test_dev_seed_no_credentials_and_idempotent():
    call_command("seed_dev")
    call_command("seed_dev")
    from operations.models import WeekdayHours
    from plans.models import Plan

    assert Plan.objects.count() == 3
    assert WeekdayHours.objects.count() == 7
    assert User.objects.count() == 0


def test_bootstrap_admin_creates_hashed_one_time_setup_and_no_fixed_password():
    from io import StringIO

    from django.core.management.base import CommandError

    from accounts.crypto import digest

    stream = StringIO()
    call_command("bootstrap_admin", phone="+8801712345678", name="Operator", stdout=stream)
    user = User.objects.get()
    assert user.role == "admin" and user.is_superuser is True
    assert user.is_staff is False and not user.has_usable_password()
    raw = stream.getvalue().splitlines()[-1]
    assert user.staff_profile.setup_token_hash == digest(raw)
    assert raw not in user.staff_profile.setup_token_hash
    with pytest.raises(CommandError):
        call_command("bootstrap_admin", phone="+8801812345678", name="Other", stdout=StringIO())
