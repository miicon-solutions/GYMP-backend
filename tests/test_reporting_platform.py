import json
from datetime import UTC, date, datetime
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


def add_payment(
    member,
    plan,
    at,
    channel="cash",
    amount=100,
    status="paid",
    *,
    list_amount=None,
    standing=None,
    offer=None,
    admission_waived=None,
    is_first=False,
    line_items=None,
):
    return Payment.objects.create(
        member=member.member_profile,
        plan=plan,
        channel=channel,
        kind="first_purchase" if is_first else "renewal",
        is_first_payment=is_first,
        amount_taka=amount,
        list_amount_taka=list_amount,
        standing_discount_taka=standing,
        offer_discount_taka=offer,
        admission_waived_taka=admission_waived,
        line_items=line_items or [],
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
    assert month.data["list_taka"] == 700
    assert month.data["discount_taka"] == 0
    assert month.data["payment_count"] == 3 and month.data["failed_count"] == 1
    assert len(month.data["payments"]) == 1
    assert month.data["by_channel"] == {"cash": 500, "sslcommerz": 200}
    assert len(month.data["series"]) == 3
    assert month.data["series"][0]["list_amount_taka"] == month.data["series"][0]["amount_taka"]
    assert month.data["prior"] is not None
    assert str(month.data["prior"]["from"])[:10] == "2026-10-01"
    sparse = client.get(url, {"range": "bad", "dates": "2026-11-01,2026-11-03,2026-11-01"})
    # Dates take precedence, including the range selector.
    assert sparse.status_code == 200
    assert sparse.data["range"] == "dates" and sparse.data["total_taka"] == 500
    assert sparse.data["prior"] is None
    assert client.get(url, {"range": "overall", "channel": "sslcommerz"}).data["total_taka"] == 200
    assert client.get(url, {"range": "overall"}).data["prior"] is None
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


def test_phase1_report_endpoints(client, staff, member, plan):
    add_payment(
        member,
        plan,
        datetime(2026, 11, 10, 10, tzinfo=UTC),
        amount=800,
        list_amount=1500,
        standing=200,
        offer=100,
        admission_waived=400,
        is_first=True,
    )
    add_payment(
        member,
        plan,
        datetime(2026, 11, 10, 12, tzinfo=UTC),
        channel="sslcommerz",
        amount=500,
        list_amount=500,
        line_items=[{"label": "Admission fee", "amount_taka": 1000}],
        is_first=True,
    )
    from operations.models import Cost

    Cost.objects.create(
        title="Rent",
        category="rent",
        amount_taka=300,
        date=date(2026, 11, 10),
        created_by=staff,
    )
    client.force_authenticate(staff)
    cash = client.get(
        "/api/v1/admin/reports/cash-vs-online/",
        {"range": "week", "date": "2026-11-10"},
    )
    assert cash.status_code == 200
    assert cash.data["cash_taka"] == 800
    assert cash.data["online_taka"] == 500
    members = client.get(
        "/api/v1/admin/reports/member-collections/",
        {"range": "week", "date": "2026-11-10"},
    )
    assert members.status_code == 200
    assert members.data["total_taka"] == 1300
    assert len(members.data["members"]) == 1
    mix = client.get(
        "/api/v1/admin/reports/plan-mix/",
        {"range": "week", "date": "2026-11-10"},
    )
    assert mix.status_code == 200
    assert mix.data["total_taka"] == 1300
    rev_exp = client.get(
        "/api/v1/admin/reports/revenue-vs-expense/",
        {"range": "week", "date": "2026-11-10"},
    )
    assert rev_exp.status_code == 200
    assert rev_exp.data["revenue_taka"] == 1300
    assert rev_exp.data["expense_taka"] == 300
    assert rev_exp.data["net_taka"] == 1000
    expenses = client.get(
        "/api/v1/admin/reports/expenses-by-admin/",
        {"range": "week", "date": "2026-11-10"},
    )
    assert expenses.status_code == 200
    assert expenses.data["total_taka"] == 300
    assert expenses.data["by_admin"][0]["amount_taka"] == 300
    status = client.get("/api/v1/admin/reports/membership-status/")
    assert status.status_code == 200
    assert "expired" in status.data and "expiring_soon" in status.data
    admission = client.get(
        "/api/v1/admin/reports/admission/",
        {"range": "week", "date": "2026-11-10"},
    )
    assert admission.status_code == 200


def test_revenue_discount_breakdown_and_prior_week(client, staff, member, plan):
    add_payment(
        member,
        plan,
        datetime(2026, 11, 10, 10, tzinfo=UTC),
        amount=800,
        list_amount=1500,
        standing=200,
        offer=100,
        admission_waived=400,
    )
    add_payment(
        member,
        plan,
        datetime(2026, 11, 2, 10, tzinfo=UTC),
        amount=500,
        list_amount=500,
    )
    client.force_authenticate(staff)
    week = client.get(
        "/api/v1/admin/revenue/",
        {"range": "week", "date": "2026-11-10"},
    )
    assert week.status_code == 200
    assert week.data["total_taka"] == 800
    assert week.data["list_taka"] == 1500
    assert week.data["discount_taka"] == 700
    assert week.data["discount_standing_taka"] == 200
    assert week.data["discount_offer_taka"] == 100
    assert week.data["discount_admission_taka"] == 400
    prior_from = week.data["prior"]["from"]
    prior_to = week.data["prior"]["to"]
    assert str(prior_from)[:10] == "2026-10-28"
    assert str(prior_to)[:10] == "2026-11-03"
    assert week.data["prior"]["total_taka"] == 500
    discounted = [p for p in week.data["series"] if p["bucket"] == "2026-11-10"][0]
    assert discounted["amount_taka"] == 800
    assert discounted["list_amount_taka"] == 1500
    assert discounted["discount_taka"] == 700


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


def test_admin_allows_crud_and_secrets_hidden(client, super_admin):
    client.force_login(super_admin)
    assert client.get("/admin/").status_code == 200
    url = f"/admin/accounts/user/{super_admin.pk}/change/"
    response = client.get(url)
    assert response.status_code == 200
    assert super_admin.password.encode() not in response.content
    assert b'name="password"' not in response.content
    assert client.get("/admin/operations/weekdayhours/").status_code == 200
    assert client.get("/admin/operations/weekdayhours/add/").status_code == 200
    assert client.get("/admin/plans/plan/add/").status_code == 200
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
            assert registered.has_add_permission(request)
            assert registered.has_change_permission(request)
            assert registered.has_delete_permission(request)
    assert Challenge not in admin.site._registry
    client.force_login(User.objects.create_user("+8801412345678", role="admin"))
    assert client.get("/admin/").status_code == 302


def test_admin_can_delete_user_with_related_profile(client, super_admin, member, staff, plan):
    from accounts.models import StaffProfile
    from attendance.models import CheckIn
    from django.utils import timezone
    from members.models import MemberProfile

    add_payment(member, plan, timezone.now())
    CheckIn.objects.create(
        member=member.member_profile,
        checked_in_at=timezone.now(),
        check_in_date=timezone.localdate(),
        source="manual",
    )
    member_id = member.pk
    staff_id = staff.pk
    client.force_login(super_admin)

    member_delete = client.post(f"/admin/accounts/user/{member_id}/delete/", {"post": "yes"})
    assert member_delete.status_code == 302
    assert not User.objects.filter(pk=member_id).exists()
    assert not MemberProfile.objects.filter(user_id=member_id).exists()
    assert not Payment.objects.filter(member__user_id=member_id).exists()

    staff_delete = client.post(f"/admin/accounts/user/{staff_id}/delete/", {"post": "yes"})
    assert staff_delete.status_code == 302
    assert not User.objects.filter(pk=staff_id).exists()
    assert not StaffProfile.objects.filter(user_id=staff_id).exists()

    # Operators cannot delete their own account from the change form.
    assert (
        admin.site._registry[User].has_delete_permission(
            type("R", (), {"user": super_admin})(), super_admin
        )
        is False
    )


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


def test_dev_seed_idempotent_with_seed_super():
    from accounts.seed_super import SEED_SUPER_PHONE
    from operations.models import WeekdayHours
    from plans.models import Plan

    call_command("seed_dev")
    call_command("seed_dev")
    assert Plan.objects.count() == 3
    assert WeekdayHours.objects.count() == 7
    assert User.objects.filter(phone_e164=SEED_SUPER_PHONE, role="admin").count() == 1


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
    assert user.staff_profile.short_id == "SADM-7400"
    call_command("bootstrap_admin", phone="+8801812345678", name="Other", stdout=StringIO())
    other = User.objects.get(phone_e164="+8801812345678")
    assert other.is_superuser is True
    assert other.staff_profile.short_id != "SADM-7400"
    with pytest.raises(CommandError, match="already registered"):
        call_command("bootstrap_admin", phone="+8801712345678", name="Dup", stdout=StringIO())
