from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.api import BadGateway
from members.models import MemberProfile
from operations.models import Activity
from payments.models import CashPaymentRequest, Payment, PaymentSession
from payments.services import add_pack_days, create_session, handle_ipn, new_expiry, receive_cash
from plans.models import Offer, Plan
from plans.services import pricing

pytestmark = pytest.mark.django_db


def complete(user):
    p = user.member_profile
    p.profile_complete = True
    p.save()
    return p


def valid(session, **changes):
    return {
        "status": "VALID",
        "tran_id": session.tran_id,
        "amount": f"{session.amount_taka}.00",
        "currency": "BDT",
        "val_id": "validated-order",
        "risk_level": "0",
        **changes,
    }


@pytest.mark.parametrize(
    "day,months,extend,expected",
    [
        (date(2025, 11, 19), 1, False, date(2025, 12, 18)),
        (date(2025, 11, 19), 3, False, date(2026, 2, 16)),
        (date(2025, 11, 19), 12, False, date(2026, 11, 18)),
        (date(2025, 12, 18), 1, True, date(2026, 1, 17)),
        (date(2025, 12, 15), 1, False, date(2026, 1, 13)),
    ],
)
def test_fixed_day_packs(day, months, extend, expected):
    assert add_pack_days(day, months, extend=extend) == expected


def test_cash_and_online_date_boundaries(member):
    p = member.member_profile
    now = datetime(2026, 1, 1, 20, tzinfo=UTC)
    # Online today=2026-01-01 UTC → +29; cash today=2026-01-02 Dhaka → +29
    assert new_expiry(p, 1, "first_purchase", now) == date(2026, 1, 30)
    assert new_expiry(p, 1, "first_payment", now, cash=True) == date(2026, 1, 31)
    p.expires_on = date(2026, 3, 31)
    p.membership_status = "active"
    assert new_expiry(p, 1, "renew", now) == date(2026, 4, 30)
    assert new_expiry(p, 1, "renewal", now, cash=True) == date(2026, 4, 30)
    p.membership_status = "expired"
    assert new_expiry(p, 1, "renew", now) == date(2026, 4, 30)
    assert new_expiry(p, 1, "renewal", now, cash=True) == date(2026, 1, 31)


def test_standing_and_offer_discounts(plan):
    plan.discount_type = "percent"
    plan.discount_value = 15
    plan.save()
    today = timezone.localdate()
    offer = Offer.objects.create(
        plan=plan,
        name="Offer",
        starts_on=today,
        ends_on=today,
        waive_admission=True,
        extra_discount_type="amount",
        extra_discount_value=200,
    )
    assert pricing(plan)["effective_renewal_taka"] == 1075
    assert pricing(plan)["effective_first_payment_taka"] == 1075
    offer.extra_discount_value = 9999
    offer.save()
    assert pricing(plan)["effective_renewal_taka"] == 0
    offer.is_active = False
    offer.save()
    assert pricing(plan)["effective_first_payment_taka"] == 2275


def test_admin_plan_crud_offers_and_member_catalog(client, staff, member):
    client.force_authenticate(staff)
    url = "/api/v1/admin/plans/"
    body = {
        "name": "Quarterly",
        "duration_months": 3,
        "monthly_rate_taka": 1500,
        "admission_fee_taka": 1000,
        "discount_type": "amount",
        "discount_value": 500,
    }
    response = client.post(url, body, format="json")
    assert response.status_code == 201
    assert response.data["effective_first_payment_taka"] == 5000
    plan_id = response.data["id"]
    assert client.post(url, body, format="json").status_code == 409
    offer_url = f"{url}{plan_id}/offers/"
    offer = {
        "name": "Special",
        "starts_on": "2026-01-01",
        "ends_on": "2030-01-01",
        "extra_discount_type": "percent",
        "extra_discount_value": 10,
    }
    created = client.post(offer_url, offer, format="json")
    assert created.status_code == 201
    assert client.post(offer_url, offer, format="json").status_code == 409
    oid = created.data["id"]
    assert (
        client.patch(f"{offer_url}{oid}/", {"is_active": False}, format="json").status_code == 200
    )
    assert client.delete(f"{offer_url}{oid}/").status_code == 204
    assert (
        client.patch(f"{url}{plan_id}/", {"discount_value": 99999}, format="json").status_code
        == 400
    )
    assert client.patch(f"{url}{plan_id}/", {"is_active": False}, format="json").status_code == 200
    client.force_authenticate(member)
    assert client.get("/api/v1/member/plans/").data["results"] == []
    assert client.get(f"/api/v1/member/plans/{plan_id}/").status_code == 404
    client.force_authenticate(staff)
    assert client.delete(f"{url}{plan_id}/").status_code == 204
    assert not Plan.objects.filter(pk=plan_id).exists()


def test_catalog_delete_deactivates_and_payment_plan_is_protected(client, staff, member, plan):
    complete(member)
    plan.catalog_id = "monthly"
    plan.save()
    client.force_authenticate(staff)
    assert client.delete(f"/api/v1/admin/plans/{plan.pk}/").status_code == 204
    plan.refresh_from_db()
    assert plan.is_active is False
    plan.catalog_id = None
    plan.is_active = True
    plan.save()
    receive_cash(staff, member.member_profile, plan.pk)
    assert client.delete(f"/api/v1/admin/plans/{plan.pk}/").status_code == 409
    assert Payment.objects.count() == 1


def test_online_checkout_and_ipn_idempotency(client, member, plan):
    complete(member)
    client.force_authenticate(member)
    response = client.post(
        "/api/v1/member/payments/sessions/",
        {"kind": "first_purchase", "plan_id": str(plan.pk), "checkout": "sdk"},
        format="json",
    )
    assert response.status_code == 201
    session = PaymentSession.objects.get()
    assert session.gateway_url == ""
    assert response.data["amount_taka"] == 2500
    body = {"tran_id": session.tran_id, "val_id": "valid", "status": "VALID"}
    client.force_authenticate(None)
    with patch("payments.gateway.validate", return_value=valid(session)) as provider:
        assert (
            client.post("/api/v1/webhooks/sslcommerz/ipn/", body, format="multipart").status_code
            == 200
        )
        assert (
            client.post("/api/v1/webhooks/sslcommerz/ipn/", body, format="multipart").status_code
            == 200
        )
        assert provider.call_count == 1
    assert Payment.objects.count() == 1
    member.member_profile.refresh_from_db()
    assert member.member_profile.fingerprint_status == "pending"
    assert member.member_profile.membership_status == "active"
    client.force_authenticate(member)
    assert (
        client.get(f"/api/v1/member/payments/sessions/{session.tran_id}/").data["status"] == "paid"
    )
    payment = Payment.objects.get()
    assert client.get(f"/api/v1/member/payments/{payment.pk}/receipt/").status_code == 200
    html = client.get(f"/api/v1/member/payments/{payment.pk}/receipt.html/")
    assert html.status_code == 200 and b"2500" in html.content


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": "0.01"},
        {"amount": "NaN"},
        {"amount": "Infinity"},
        {"tran_id": "wrong"},
        {"currency": "USD"},
        {"risk_level": "1"},
        {"val_id": ""},
    ],
)
def test_invalid_gateway_settlement(member, plan, changes):
    complete(member)
    session = create_session(
        member, {"kind": "first_purchase", "plan_id": plan.pk, "checkout": "sdk"}
    )
    with patch("payments.gateway.validate", return_value=valid(session, **changes)):
        with pytest.raises(ValidationError):
            handle_ipn({"tran_id": session.tran_id, "val_id": "v", "status": "VALID"})
    assert Payment.objects.count() == 0
    assert MemberProfile.objects.get(user=member).membership_status == "none"
    session.refresh_from_db()
    assert session.status == "pending"


def test_confirmation_polling_and_owner_checks(client, member, other_member, plan):
    complete(member)
    session = create_session(
        member, {"kind": "first_purchase", "plan_id": plan.pk, "checkout": "sdk"}
    )
    url = f"/api/v1/member/payments/sessions/{session.tran_id}/"
    client.force_authenticate(other_member)
    assert client.get(url).status_code == 404
    client.force_authenticate(member)
    with patch("payments.gateway.query", side_effect=BadGateway()):
        assert client.get(url).data["status"] == "pending"
        assert client.post(url + "confirm/", {}, format="json").status_code == 502
    with patch("payments.gateway.query", return_value=valid(session)):
        assert client.post(url + "confirm/", {}, format="json").data["status"] == "paid"
    payment = Payment.objects.get()
    client.force_authenticate(other_member)
    assert client.get(f"/api/v1/member/payments/{payment.pk}/").status_code == 404
    assert client.get(f"/api/v1/member/payments/{payment.pk}/receipt.html/").status_code == 404


def test_hosted_checkout_failure_and_pending_cancellation(member, plan):
    complete(member)
    with patch("payments.gateway.initiate", side_effect=BadGateway()):
        with pytest.raises(BadGateway):
            create_session(member, {"kind": "first_purchase", "plan_id": plan.pk})
    assert PaymentSession.objects.get().status == "failed"
    first = create_session(
        member, {"kind": "first_purchase", "plan_id": plan.pk, "checkout": "sdk"}
    )
    with patch(
        "payments.gateway.initiate",
        return_value={
            "GatewayPageURL": "https://sandbox.sslcommerz.com/pay",
            "sessionkey": "private",
        },
    ):
        second = create_session(member, {"kind": "first_purchase", "plan_id": plan.pk})
    first.refresh_from_db()
    assert first.status == "cancelled" and second.gateway_url.startswith("https://")


def test_pricing_frozen_at_checkout(member, plan):
    complete(member)
    session = create_session(
        member, {"kind": "first_purchase", "plan_id": plan.pk, "checkout": "sdk"}
    )
    plan.monthly_rate_taka = 9999
    plan.is_active = False
    plan.save()
    with patch("payments.gateway.validate", return_value=valid(session)):
        handle_ipn({"tran_id": session.tran_id, "val_id": "v", "status": "VALID"})
    p = Payment.objects.get()
    assert p.amount_taka == 2500
    assert sum(item["amount_taka"] for item in p.line_items) == 2500


def test_cash_first_renewal_plan_change(client, staff, member, plan):
    complete(member)
    client.force_authenticate(staff)
    url = f"/api/v1/admin/members/{member.pk}/"
    preview = client.get(url + "cash-preview/", {"plan_id": str(plan.pk)})
    assert preview.status_code == 200
    assert preview.data["amount_taka"] == 2500
    first = client.post(
        url + "cash-payments/", {"plan_id": str(plan.pk), "amount_taka": 1}, format="json"
    )
    assert first.status_code == 201 and first.data["payment"]["amount_taka"] == 2500
    assert first.data["payment"]["kind"] == "first_payment"
    member.member_profile.refresh_from_db()
    expiry = member.member_profile.expires_on
    member.member_profile.fingerprint_status = "ready"
    member.member_profile.save()
    second = client.post(url + "cash-payments/", {"plan_id": str(plan.pk)}, format="json")
    assert second.data["payment"]["kind"] == "renewal"
    assert second.data["payment"]["amount_taka"] == 1500
    p = MemberProfile.objects.get(user=member)
    assert p.expires_on == add_pack_days(expiry, 1, extend=True)
    assert p.fingerprint_status == "ready"
    quarterly = Plan.objects.create(name="Quarterly", duration_months=3, monthly_rate_taka=1400)
    third = client.post(url + "cash-payments/", {"plan_id": str(quarterly.pk)}, format="json")
    assert third.data["payment"]["kind"] == "plan_change"
    assert Activity.objects.filter(area="member").count() == 3


def test_checkout_requires_complete_profile_and_eligible_kind(client, member, plan):
    client.force_authenticate(member)
    body = {"kind": "first_purchase", "plan_id": str(plan.pk), "checkout": "sdk"}
    assert client.post("/api/v1/member/payments/sessions/", body, format="json").status_code == 400
    complete(member)
    assert (
        client.post(
            "/api/v1/member/payments/sessions/", {**body, "kind": "renew"}, format="json"
        ).status_code
        == 400
    )
    plan.monthly_rate_taka = 0
    plan.admission_fee_taka = 0
    plan.save()
    assert client.post("/api/v1/member/payments/sessions/", body, format="json").status_code == 400


def test_payment_and_activation_rollback(staff, member, plan):
    complete(member)
    with patch("payments.services.record", side_effect=RuntimeError("audit failure")):
        with pytest.raises(RuntimeError):
            receive_cash(staff, member.member_profile, plan.pk)
    assert not Payment.objects.exists()
    assert MemberProfile.objects.get(user=member).membership_status == "none"


def test_member_cash_request_create_poll_accept(client, staff, member, plan):
    complete(member)
    client.force_authenticate(member)
    created = client.post(
        "/api/v1/member/payments/cash-requests/",
        {"plan_id": str(plan.pk)},
        format="json",
    )
    assert created.status_code == 201
    assert created.data["status"] == "pending"
    assert created.data["amount_taka"] == 2500
    assert created.data["kind"] == "first_payment"
    request_id = created.data["id"]
    member.member_profile.refresh_from_db()
    assert member.member_profile.membership_status == "pending_payment"

    polled = client.get(f"/api/v1/member/payments/cash-requests/{request_id}/")
    assert polled.status_code == 200 and polled.data["status"] == "pending"

    listed = client.get("/api/v1/member/payments/cash-requests/list/", {"status": "pending"})
    assert listed.status_code == 200 and len(listed.data) == 1

    client.force_authenticate(staff)
    pending = client.get("/api/v1/admin/cash-requests/", {"status": "pending"})
    assert pending.status_code == 200 and len(pending.data) == 1
    assert pending.data[0]["member_display_id"] == member.member_profile.member_id

    accepted = client.post(f"/api/v1/admin/cash-requests/{request_id}/accept/", {}, format="json")
    assert accepted.status_code == 200
    assert accepted.data["request"]["status"] == "accepted"
    assert accepted.data["payment"]["amount_taka"] == 2500
    assert accepted.data["payment"]["channel"] == "cash"
    assert accepted.data["member"]["membership_status"] == "active"
    assert Payment.objects.count() == 1
    assert CashPaymentRequest.objects.get(pk=request_id).payment_id is not None

    # Idempotent accept
    again = client.post(f"/api/v1/admin/cash-requests/{request_id}/accept/", {}, format="json")
    assert again.status_code == 200 and Payment.objects.count() == 1

    client.force_authenticate(member)
    assert (
        client.get(f"/api/v1/member/payments/cash-requests/{request_id}/").data["status"]
        == "accepted"
    )


def test_cash_request_accept_requires_permission(client, member, plan):
    from accounts.models import StaffProfile, User

    limited = User.objects.create_user("+8801922222222", role="admin", full_name="Viewer")
    StaffProfile.objects.create(
        user=limited,
        short_id="S-VIEW",
        permissions=["members.view", "cash_requests.view"],
    )
    complete(member)
    client.force_authenticate(member)
    created = client.post(
        "/api/v1/member/payments/cash-requests/",
        {"plan_id": str(plan.pk)},
        format="json",
    ).data
    client.force_authenticate(limited)
    listed = client.get("/api/v1/admin/cash-requests/", {"status": "pending"})
    assert listed.status_code == 200 and len(listed.data) == 1
    denied = client.post(
        f"/api/v1/admin/cash-requests/{created['id']}/accept/", {}, format="json"
    )
    assert denied.status_code == 403


def test_member_cash_request_reject_and_cancel(client, staff, member, plan):
    complete(member)
    client.force_authenticate(member)
    first = client.post(
        "/api/v1/member/payments/cash-requests/",
        {"plan_id": str(plan.pk)},
        format="json",
    ).data
    client.force_authenticate(staff)
    rejected = client.post(f"/api/v1/admin/cash-requests/{first['id']}/reject/", {}, format="json")
    assert rejected.status_code == 200 and rejected.data["status"] == "rejected"
    member.member_profile.refresh_from_db()
    assert member.member_profile.membership_status == "none"

    client.force_authenticate(member)
    second = client.post(
        "/api/v1/member/payments/cash-requests/",
        {"plan_id": str(plan.pk)},
        format="json",
    ).data
    cancelled = client.post(
        f"/api/v1/member/payments/cash-requests/{second['id']}/cancel/", {}, format="json"
    )
    assert cancelled.status_code == 200 and cancelled.data["status"] == "cancelled"
    member.member_profile.refresh_from_db()
    assert member.member_profile.membership_status == "none"


def test_cash_request_replaces_prior_pending_and_legacy_receive_links(client, staff, member, plan):
    complete(member)
    client.force_authenticate(member)
    first = client.post(
        "/api/v1/member/payments/cash-requests/",
        {"plan_id": str(plan.pk)},
        format="json",
    ).data
    second = client.post(
        "/api/v1/member/payments/cash-requests/",
        {"plan_id": str(plan.pk)},
        format="json",
    ).data
    assert first["id"] != second["id"]
    assert CashPaymentRequest.objects.get(pk=first["id"]).status == "cancelled"
    assert (
        CashPaymentRequest.objects.filter(member=member.member_profile, status="pending").count()
        == 1
    )

    client.force_authenticate(staff)
    received = client.post(
        f"/api/v1/admin/members/{member.pk}/cash-payments/",
        {"plan_id": str(plan.pk)},
        format="json",
    )
    assert received.status_code == 201
    linked = CashPaymentRequest.objects.get(pk=second["id"])
    assert linked.status == "accepted"
    assert str(linked.payment_id) == received.data["payment"]["id"]


def test_cash_request_requires_profile_and_ownership(client, member, other_member, plan):
    client.force_authenticate(member)
    assert (
        client.post(
            "/api/v1/member/payments/cash-requests/",
            {"plan_id": str(plan.pk)},
            format="json",
        ).status_code
        == 400
    )
    complete(member)
    created = client.post(
        "/api/v1/member/payments/cash-requests/",
        {"plan_id": str(plan.pk)},
        format="json",
    )
    assert created.status_code == 201
    client.force_authenticate(other_member)
    assert (
        client.get(f"/api/v1/member/payments/cash-requests/{created.data['id']}/").status_code
        == 404
    )


def _limited_offer(plan, *, scope="offer", max_redemptions=1, waive=True):
    today = timezone.localdate()
    return Offer.objects.create(
        plan=plan,
        name="First-N",
        starts_on=today,
        ends_on=today.replace(year=today.year + 1),
        waive_admission=waive,
        max_redemptions=max_redemptions,
        limit_scope=scope,
    )


def test_first_n_offer_scope_exhausts_on_paid_only(client, staff, member, other_member, plan):
    complete(member)
    complete(other_member)
    offer = _limited_offer(plan, scope="offer", max_redemptions=1)
    assert pricing(plan)["effective_first_payment_taka"] == 1500

    # Pending session does not consume a seat.
    session = create_session(
        member, {"kind": "first_purchase", "plan_id": plan.pk, "checkout": "sdk"}
    )
    assert session.pricing_snapshot["admission_waived"] is True
    assert session.pricing_snapshot["offer_id"] == str(offer.pk)
    assert pricing(plan)["effective_first_payment_taka"] == 1500
    client.force_authenticate(member)
    row = client.get("/api/v1/member/plans/").data["results"][0]
    assert row["active_offer"]["remaining"] == 1
    assert row["active_offer"]["admission_waived"] is True

    with patch("payments.gateway.validate", return_value=valid(session)):
        handle_ipn({"tran_id": session.tran_id, "val_id": "v", "status": "VALID"})
    payment = Payment.objects.get()
    assert payment.offer_id == offer.pk
    assert payment.is_first_payment
    assert pricing(plan)["effective_first_payment_taka"] == 2500
    client.force_authenticate(other_member)
    row = client.get("/api/v1/member/plans/").data["results"][0]
    assert row["active_offer"]["remaining"] == 0
    assert row["active_offer"]["admission_waived"] is False
    assert row["effective_first_payment_taka"] == 2500

    # Renew does not claim another seat / change remaining.
    member.member_profile.membership_status = "active"
    member.member_profile.expires_on = timezone.localdate()
    member.member_profile.plan = plan
    member.member_profile.save()
    client.force_authenticate(staff)
    renew = client.post(
        f"/api/v1/admin/members/{member.pk}/cash-payments/",
        {"plan_id": str(plan.pk)},
        format="json",
    )
    assert renew.status_code == 201
    assert renew.data["payment"]["kind"] == "renewal"
    assert Payment.objects.filter(offer=offer).count() == 1
    assert pricing(plan)["effective_first_payment_taka"] == 2500


def test_first_n_plan_and_gym_scopes(staff, member, other_member, plan):
    from accounts.services import new_member

    complete(member)
    complete(other_member)
    third = new_member("+8801711111111")
    complete(third)
    other_plan = Plan.objects.create(
        name="Quarterly", duration_months=3, monthly_rate_taka=1500, admission_fee_taka=1000
    )

    plan_offer = _limited_offer(plan, scope="plan", max_redemptions=1)
    receive_cash(staff, member.member_profile, plan.pk)
    assert Payment.objects.get(member=member.member_profile).offer_id == plan_offer.pk
    assert pricing(plan)["effective_first_payment_taka"] == 2500
    # Other plan has no offer yet — full quarterly first price.
    assert pricing(other_plan)["effective_first_payment_taka"] == 5500

    gym_offer = _limited_offer(other_plan, scope="gym", max_redemptions=1)
    from plans.services import remaining_redemptions

    # One gym-wide first payment already exists (member), so gym seat is gone.
    assert remaining_redemptions(gym_offer) == 0
    assert pricing(other_plan)["effective_first_payment_taka"] == 5500

    # Higher gym cap still has a seat after one prior payment.
    gym_offer.max_redemptions = 2
    gym_offer.save()
    assert remaining_redemptions(gym_offer) == 1
    assert pricing(other_plan)["effective_first_payment_taka"] == 4500
    receive_cash(staff, other_member.member_profile, other_plan.pk)
    assert remaining_redemptions(gym_offer) == 0
    assert pricing(other_plan)["effective_first_payment_taka"] == 5500


def test_first_n_frozen_session_keeps_waived_amount_after_exhaustion(
    client, staff, member, other_member, plan
):
    complete(member)
    complete(other_member)
    _limited_offer(plan, scope="offer", max_redemptions=1)
    session = create_session(
        member, {"kind": "first_purchase", "plan_id": plan.pk, "checkout": "sdk"}
    )
    assert session.amount_taka == 1500
    # Exhaust seats via cash for the other member while session is still pending.
    receive_cash(staff, other_member.member_profile, plan.pk)
    assert pricing(plan)["effective_first_payment_taka"] == 2500
    with patch("payments.gateway.validate", return_value=valid(session)):
        handle_ipn({"tran_id": session.tran_id, "val_id": "v", "status": "VALID"})
    payment = Payment.objects.get(member=member.member_profile)
    assert payment.amount_taka == 1500
    assert payment.offer_id is not None


def test_admin_offer_accepts_max_redemptions_and_limit_scope(client, staff, plan):
    client.force_authenticate(staff)
    today = timezone.localdate().isoformat()
    created = client.post(
        f"/api/v1/admin/plans/{plan.pk}/offers/",
        {
            "name": "Opening",
            "starts_on": today,
            "ends_on": "2030-01-01",
            "waive_admission": True,
            "max_redemptions": 50,
            "limit_scope": "gym",
        },
        format="json",
    )
    assert created.status_code == 201
    assert created.data["max_redemptions"] == 50
    assert created.data["limit_scope"] == "gym"
    assert created.data["remaining"] == 50
    assert created.data["admission_waived"] is True
    bad = client.patch(
        f"/api/v1/admin/plans/{plan.pk}/offers/{created.data['id']}/",
        {"max_redemptions": 0},
        format="json",
    )
    assert bad.status_code == 400
