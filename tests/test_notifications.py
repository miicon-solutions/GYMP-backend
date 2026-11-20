from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from notifications.models import MemberDeviceToken, MemberNotification, StaffAnnouncement
from notifications.services import (
    create_notification,
    has_unread,
    mark_all_read,
    mark_read,
    notify_membership_expiry_batch,
    notify_payment_received,
    register_device,
)
from payments.models import Payment


@pytest.mark.django_db
def test_create_list_mark_read(client, member):
    create_notification(
        member,
        code="fingerprint_ready",
        push=False,
    )
    assert has_unread(member) is True

    client.force_authenticate(member)
    listed = client.get("/api/v1/member/notifications/")
    assert listed.status_code == 200
    assert len(listed.data) == 1
    assert listed.data[0]["code"] == "fingerprint_ready"
    assert listed.data[0]["is_unread"] is True

    dash = client.get("/api/v1/member/dashboard/")
    assert dash.data["has_unread_notifications"] is True

    nid = listed.data[0]["id"]
    read = client.post(f"/api/v1/member/notifications/{nid}/read/")
    assert read.status_code == 200
    assert read.data["is_unread"] is False
    assert has_unread(member) is False


@pytest.mark.django_db
def test_mark_all_read(client, member):
    create_notification(member, code="fingerprint_ready", push=False)
    create_notification(member, code="membership_expired", push=False)
    client.force_authenticate(member)
    result = client.post("/api/v1/member/notifications/read-all/")
    assert result.status_code == 200
    assert result.data["updated"] == 2
    assert has_unread(member) is False


@pytest.mark.django_db
def test_payment_received_dedupe(member, plan):
    payment = Payment.objects.create(
        member=member.member_profile,
        plan=plan,
        catalog_id=plan.catalog_id,
        channel="cash",
        kind="first_payment",
        is_first_payment=True,
        amount_taka=3000,
        paid_at=timezone.now(),
    )
    notify_payment_received(member, payment)
    notify_payment_received(member, payment)
    assert (
        MemberNotification.objects.filter(user=member, code="payment_received").count()
        == 1
    )
    assert (
        MemberNotification.objects.filter(user=member, code="membership_activated").count()
        == 1
    )


@pytest.mark.django_db
def test_cash_reject_notifies(client, member, staff, plan):
    from payments.models import CashPaymentRequest
    from payments.services import reject_cash_request

    profile = member.member_profile
    profile.membership_status = "pending_payment"
    profile.profile_complete = True
    profile.save()
    req = CashPaymentRequest.objects.create(
        member=profile,
        plan=plan,
        kind="first_payment",
        amount_taka=3000,
        pricing_snapshot={"amount_taka": 3000, "catalog_id": plan.catalog_id, "line_items": []},
        status="pending",
    )
    reject_cash_request(staff, req.pk)
    assert MemberNotification.objects.filter(
        user=member, code="cash_request_rejected"
    ).exists()


@pytest.mark.django_db
def test_fcm_register_unregister(client, member):
    client.force_authenticate(member)
    reg = client.post(
        "/api/v1/member/devices/fcm/",
        {"token": "tok-abc", "platform": "ios"},
        format="json",
    )
    assert reg.status_code == 200
    assert MemberDeviceToken.objects.filter(user=member, token="tok-abc").exists()

    deleted = client.delete(
        "/api/v1/member/devices/fcm/",
        {"token": "tok-abc"},
        format="json",
    )
    assert deleted.status_code == 200
    assert deleted.data["deleted"] == 1


@pytest.mark.django_db
def test_expiry_batch_idempotent(member, plan):
    profile = member.member_profile
    today = timezone.localdate()
    profile.membership_status = "active"
    profile.plan = plan
    profile.expires_on = today + timedelta(days=7)
    profile.save()

    first = notify_membership_expiry_batch(today=today)
    second = notify_membership_expiry_batch(today=today)
    assert first["expiring_7"] == 1
    assert second["expiring_7"] == 0
    assert MemberNotification.objects.filter(
        user=member, code="membership_expiring"
    ).count() == 1


@pytest.mark.django_db
def test_admin_announcement_campaign_crud(client, member, staff, plan):
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.save()
    client.force_authenticate(staff)

    created = client.post(
        "/api/v1/admin/notifications/",
        {
            "scope": "active",
            "title": "Friday closed",
            "body": "Gym closed this Friday.",
            "send_push": False,
        },
        format="json",
    )
    assert created.status_code == 201
    assert created.data["created"] == 1
    assert created.data["recipient_count"] == 1
    assert created.data["push_requested"] is False
    campaign_id = created.data["id"]
    assert StaffAnnouncement.objects.filter(pk=campaign_id).exists()
    fanout = MemberNotification.objects.get(user=member, code="announcement")
    assert fanout.related_object_id == str(campaign_id)
    assert fanout.title == "Friday closed"

    listed = client.get("/api/v1/admin/notifications/")
    assert listed.status_code == 200
    assert listed.data["results"][0]["id"] == campaign_id

    patched = client.patch(
        f"/api/v1/admin/notifications/{campaign_id}/",
        {"title": "Saturday closed", "body": "Closed Sat."},
        format="json",
    )
    assert patched.status_code == 200
    assert patched.data["title"] == "Saturday closed"
    fanout.refresh_from_db()
    assert fanout.title == "Saturday closed"
    assert fanout.body == "Closed Sat."

    deleted = client.delete(f"/api/v1/admin/notifications/{campaign_id}/")
    assert deleted.status_code == 204
    assert not StaffAnnouncement.objects.filter(pk=campaign_id).exists()
    assert not MemberNotification.objects.filter(
        code="announcement", related_object_id=str(campaign_id)
    ).exists()


@pytest.mark.django_db
def test_admin_announcement_reports_no_device(client, member, staff, plan):
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.save()
    client.force_authenticate(staff)
    result = client.post(
        "/api/v1/admin/notifications/",
        {
            "scope": "member",
            "member_id": str(member.pk),
            "title": "Ping",
            "body": "Hello",
            "send_push": True,
        },
        format="json",
    )
    assert result.status_code == 201
    assert result.data["created"] == 1
    assert result.data["push_requested"] is True
    assert result.data["push_sent"] == 0
    assert result.data["push_skipped_no_device"] == 1


@pytest.mark.django_db
def test_admin_announcement_resend_push(client, member, staff, plan):
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.save()
    client.force_authenticate(staff)
    created = client.post(
        "/api/v1/admin/notifications/",
        {
            "scope": "member",
            "member_id": str(member.pk),
            "title": "Hi",
            "body": "Again",
            "send_push": False,
        },
        format="json",
    )
    campaign_id = created.data["id"]
    with patch(
        "notifications.services.send_fcm_for_notification",
        return_value={"sent": 1, "failed": 0, "skipped": None},
    ) as send:
        resend = client.post(f"/api/v1/admin/notifications/{campaign_id}/resend-push/")
    assert resend.status_code == 200
    assert resend.data["push_sent"] == 1
    send.assert_called_once()


@pytest.mark.django_db
def test_admin_announcement_permissions(client, member, staff, plan):
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.save()
    staff.staff_profile.permissions = ["notifications.view"]
    staff.staff_profile.save(update_fields=["permissions", "updated_at"])
    client.force_authenticate(staff)
    assert client.get("/api/v1/admin/notifications/").status_code == 200
    assert (
        client.post(
            "/api/v1/admin/notifications/",
            {
                "scope": "active",
                "title": "Nope",
                "body": "Denied",
                "send_push": False,
            },
            format="json",
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_mark_read_service(member):
    notif = create_notification(member, code="fingerprint_ready", push=False)
    mark_read(member, notif.pk)
    notif.refresh_from_db()
    assert notif.is_unread is False
    assert mark_all_read(member)["updated"] == 0


@pytest.mark.django_db
def test_register_device_moves_token(member, other_member):
    register_device(member, "shared-token", "android")
    register_device(other_member, "shared-token", "android")
    assert MemberDeviceToken.objects.filter(token="shared-token").count() == 1
    assert MemberDeviceToken.objects.get(token="shared-token").user_id == other_member.pk
