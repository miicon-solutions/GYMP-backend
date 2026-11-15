from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connections
from rest_framework.exceptions import AuthenticationFailed, ValidationError

from accounts.services import consume_challenge, issue_tokens, rotate_refresh, send_otp
from attendance.models import CheckIn
from attendance.services import record_checkin
from members.models import MemberProfile
from payments.models import Payment
from payments.services import create_session, handle_ipn, receive_cash

pytestmark = pytest.mark.django_db(transaction=True)


def parallel(call):
    barrier = Barrier(2)

    def run():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return call()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(lambda _: run(), range(2)))


def test_concurrent_refresh_accepts_once(member):
    raw = issue_tokens(member)["refresh_token"]

    def call():
        try:
            rotate_refresh(raw)
            return "ok"
        except AuthenticationFailed:
            return "rejected"

    assert sorted(parallel(call)) == ["ok", "rejected"]


def test_concurrent_otp_consumed_once(member):
    otp = send_otp({"phone_e164": member.phone_e164, "purpose": "onboarding"})["otp_session_id"]

    def call():
        try:
            consume_challenge(otp, "000000", ["onboarding"])
            return "ok"
        except ValidationError:
            return "rejected"

    assert sorted(parallel(call)) == ["ok", "rejected"]


def test_concurrent_ipn_activation_once(member, plan):
    member.member_profile.profile_complete = True
    member.member_profile.save()
    s = create_session(member, {"kind": "first_purchase", "plan_id": plan.pk, "checkout": "sdk"})
    result = {
        "status": "VALID",
        "tran_id": s.tran_id,
        "amount": str(s.amount_taka),
        "currency": "BDT",
        "val_id": "valid",
        "risk_level": "0",
    }
    with patch("payments.gateway.validate", return_value=result):
        parallel(lambda: handle_ipn({"tran_id": s.tran_id, "status": "VALID", "val_id": "valid"}))
    assert Payment.objects.count() == 1
    assert MemberProfile.objects.get(user=member).membership_status == "active"


def test_concurrent_cash_extends_from_latest_expiry(member, staff, plan):
    parallel(lambda: receive_cash(staff, member.member_profile, plan.pk))
    assert Payment.objects.count() == 2
    payments = list(Payment.objects.order_by("created_at"))
    assert payments[0].is_first_payment is True
    assert payments[1].is_first_payment is False
    assert MemberProfile.objects.get(user=member).expires_on is not None


def test_concurrent_checkin_deduplicates(member):
    at = datetime(2026, 11, 15, 8, tzinfo=UTC)
    results = parallel(
        lambda: record_checkin({"member_id": member.member_profile.member_id, "checked_in_at": at})
    )
    assert CheckIn.objects.count() == 1
    assert sorted(r["recorded"] for r in results) == [False, True]


def test_offer_patch_uses_latest_row(staff, plan):
    from datetime import date

    from plans.models import Offer
    from plans.services import save_offer

    offer = Offer.objects.create(
        plan=plan, name="Original", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31)
    )
    stale = Offer.objects.get(pk=offer.pk)
    save_offer(staff, plan, {"name": "Renamed"}, offer)
    updated = save_offer(staff, plan, {"extra_discount_value": 10}, stale)
    assert updated.name == "Renamed"
    assert updated.extra_discount_value == 10


@pytest.mark.parametrize("channel", ["cash", "online"])
def test_price_snapshot_holds_plan_lock(member, staff, plan, channel):
    from django.db import DatabaseError, transaction

    from payments.services import snapshot
    from plans.models import Plan

    p = member.member_profile
    p.profile_complete = True
    p.save()

    def probe():
        close_old_connections()
        try:
            with transaction.atomic():
                Plan.objects.select_for_update(nowait=True).get(pk=plan.pk)
            return False
        except DatabaseError:
            return True
        finally:
            connections.close_all()

    def checked_snapshot(selected, kind):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(probe).result(timeout=10) is True
        return snapshot(selected, kind)

    with patch("payments.services.snapshot", side_effect=checked_snapshot):
        if channel == "cash":
            receive_cash(staff, p, plan.pk)
        else:
            create_session(
                member, {"kind": "first_purchase", "plan_id": plan.pk, "checkout": "sdk"}
            )
