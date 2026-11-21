from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.management.commands.seed_demo import demo_id
from accounts.models import StaffProfile, User
from attendance.models import CheckIn
from members.models import MemberProfile
from operations.models import Activity, Cost, Holiday
from payments.models import Payment, PaymentSession
from plans.models import Offer, Plan

pytestmark = pytest.mark.django_db


def seed(admin, **options):
    output = StringIO()
    call_command("seed_demo", admin_phone=admin.phone_e164, stdout=output, **options)
    return output.getvalue()


def test_demo_seed_consistent_repeatable_and_expandable(super_admin):
    with patch("payments.gateway.initiate") as gateway:
        output = seed(super_admin)
    gateway.assert_not_called()
    assert "created 32" in output
    assert Plan.objects.count() == 3
    assert Offer.objects.count() == 2
    assert StaffProfile.objects.count() == 3
    assert Cost.objects.count() == 12
    assert Holiday.objects.count() == 2
    assert MemberProfile.objects.filter(membership_status="none").count() == 10
    assert MemberProfile.objects.filter(membership_status="active").count() == 15
    assert MemberProfile.objects.filter(membership_status="expired").count() == 5
    for profile in MemberProfile.objects.select_related("user"):
        assert profile.profile_complete
        assert not profile.user.has_usable_password()
        assert not profile.user.is_staff
        if profile.membership_status == "none":
            assert not profile.payments.exists()
            assert not profile.check_ins.exists()
            assert profile.plan_id is None
        else:
            assert profile.expires_on
            assert profile.payments.filter(is_first_payment=True).count() == 1
            assert profile.check_ins.exists()
            for visit in profile.check_ins.all():
                assert visit.check_in_date <= min(profile.expires_on, timezone.localdate())
                assert visit.checked_in_at <= timezone.now()
    for payment in Payment.objects.all():
        assert payment.amount_taka == sum(item["amount_taka"] for item in payment.line_items)
        assert payment.paid_at <= timezone.now()
        if payment.channel == "sslcommerz":
            assert PaymentSession.objects.get(tran_id=payment.tran_id).status == "paid"
    models = [User, Plan, Offer, Payment, PaymentSession, CheckIn, Cost, Activity, Holiday]
    counts = [model.objects.count() for model in models]
    seed(super_admin)
    assert counts == [model.objects.count() for model in models]
    seed(super_admin, members=36)
    assert MemberProfile.objects.count() == 36
    assert MemberProfile.objects.filter(membership_status="none").count() == 12


def test_demo_seed_preserves_existing_catalog_and_members(super_admin, plan, member):
    original = Plan.objects.values().get(pk=plan.pk)
    seed(super_admin, members=6)
    assert Plan.objects.values().get(pk=plan.pk) == original
    member.refresh_from_db()
    assert member.full_name == ""
    assert member.member_profile.membership_status == "none"


def test_demo_seed_phone_collision_rolls_back(super_admin):
    User.objects.create_user("+8801999000003", role="member", full_name="Real account")
    with pytest.raises(CommandError, match="Phone collision"):
        seed(super_admin)
    assert User.objects.count() == 2
    assert not Plan.objects.exists()
    assert not MemberProfile.objects.exists()
    assert not Activity.objects.exists()


def test_demo_seed_production_is_disabled(settings, super_admin):
    settings.APP_ENV = "prod"
    with pytest.raises(CommandError, match="disabled in production"):
        seed(super_admin)
    assert not Plan.objects.exists()


@pytest.mark.parametrize("count", [0, -1, 1001])
def test_demo_seed_invalid_count(super_admin, count):
    with pytest.raises(CommandError, match="between 1 and 1000"):
        seed(super_admin, members=count)


def test_demo_seed_requires_existing_super_admin(staff):
    with pytest.raises(CommandError, match="Bootstrap an active super admin"):
        seed(staff)
    assert not Plan.objects.exists()


def test_demo_seed_does_not_reset_edited_demo_data(super_admin):
    seed(super_admin, members=1)
    user = User.objects.get(pk=demo_id("user", "member-1"))
    user.full_name = "Updated demo member"
    user.save()
    seed(super_admin, members=1)
    user.refresh_from_db()
    assert user.full_name == "Updated demo member"


def test_demo_seed_report_month_oct_2026_idempotent(super_admin):
    seed(super_admin, report_month="2026-10")
    oct_start = date(2026, 10, 1)
    oct_end = date(2026, 10, 31)
    oct_payments = Payment.objects.filter(
        paid_at__date__gte=oct_start, paid_at__date__lte=oct_end
    )
    assert oct_payments.count() >= 40
    frozen = oct_payments.filter(list_amount_taka__isnull=False)
    assert frozen.count() >= 40
    assert frozen.filter(is_first_payment=True, admission_waived_taka__gt=0).exists()
    assert frozen.filter(channel="cash").exists()
    assert frozen.filter(channel="sslcommerz").exists()
    report_costs = Cost.objects.filter(title__startswith="Demo report")
    assert report_costs.count() >= 12
    assert report_costs.values("created_by").distinct().count() >= 2
    assert MemberProfile.objects.filter(membership_status="expired").count() >= 5
    soon = MemberProfile.objects.filter(
        membership_status="active",
        expires_on__gte=timezone.localdate(),
        expires_on__lte=timezone.localdate() + timedelta(days=7),
    )
    assert soon.count() >= 5
    models = [Payment, PaymentSession, Cost, MemberProfile, User]
    counts = [model.objects.count() for model in models]
    seed(super_admin, report_month="2026-10")
    assert counts == [model.objects.count() for model in models]


def test_demo_seed_report_month_invalid(super_admin):
    with pytest.raises(CommandError, match="YYYY-MM"):
        seed(super_admin, report_month="2026/10")


def test_public_registration_remains_unpaid_until_cash(client, staff, plan, profile_payload):
    sent = client.post(
        "/api/v1/auth/otp/send/",
        {"phone_e164": "+8801712345678", "purpose": "onboarding"},
        format="json",
    )
    verified = client.post(
        "/api/v1/auth/otp/verify/",
        {"otp_session_id": sent.data["otp_session_id"], "code": "000000"},
        format="json",
    )
    assert verified.status_code == 200
    assert verified.data["member"]["membership_status"] == "none"
    user = User.objects.get(pk=verified.data["member"]["id"])
    client.force_authenticate(user)
    saved = client.post("/api/v1/member/profile/complete/", profile_payload, format="json")
    assert saved.status_code == 200
    assert saved.data["membership_status"] == "none"
    assert not Payment.objects.exists()
    client.force_authenticate(staff)
    rows = client.get("/api/v1/admin/members/", {"status": "unpaid"}).data["results"]
    assert rows[0]["id"] == str(user.pk)
    paid = client.post(
        f"/api/v1/admin/members/{user.pk}/cash-payments/",
        {"plan_id": str(plan.pk)},
        format="json",
    )
    assert paid.status_code == 201
    assert paid.data["member"]["membership_status"] == "active"
    assert Activity.objects.filter(area="member", action="activate").count() == 1
    client.force_authenticate(user)
    assert client.get("/api/v1/member/profile/").data["membership_status"] == "active"


def test_cash_requires_complete_profile(client, staff, member, plan):
    client.force_authenticate(staff)
    base = f"/api/v1/admin/members/{member.pk}/"
    assert client.get(base + "cash-preview/", {"plan_id": str(plan.pk)}).status_code == 400
    assert (
        client.post(base + "cash-payments/", {"plan_id": str(plan.pk)}, format="json").status_code
        == 400
    )
    assert not Payment.objects.exists()
    assert not Activity.objects.exists()


@pytest.mark.parametrize("status", ["none", "pending_payment"])
def test_unpaid_registration_cannot_check_in(client, member, status):
    profile = member.member_profile
    profile.membership_status = status
    profile.save()
    response = client.post(
        "/api/v1/internal/attendance/check-in/",
        {"member_id": profile.member_id},
        format="json",
        HTTP_X_DEVICE_KEY="test-device-key",
    )
    assert response.status_code == 403
    assert not CheckIn.objects.exists()


def test_member_status_filter_and_search(client, staff, member, other_member):
    profile = other_member.member_profile
    profile.membership_status = "active"
    profile.save()
    client.force_authenticate(staff)
    base = "/api/v1/admin/members/"
    assert len(client.get(base).data["results"]) == 2
    assert client.get(base, {"status": "unpaid"}).data["results"][0]["id"] == str(member.pk)
    assert client.get(base, {"status": "active"}).data["results"][0]["id"] == str(other_member.pk)
    assert (
        client.get(base, {"status": "unpaid", "q": other_member.phone_e164}).data["results"] == []
    )
    assert client.get(base, {"status": "invalid"}).status_code == 400
