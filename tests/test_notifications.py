from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from notifications.models import MemberDeviceToken, MemberNotification, StaffAnnouncement
from notifications.services import (
    CATALOG,
    create_notification,
    format_push,
    format_sms,
    has_unread,
    mark_all_read,
    mark_read,
    notify_membership_expiry_batch,
    notify_payment_received,
    register_device,
    send_fcm_for_notification,
    send_sms_for_notification,
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
def test_cash_reject_queues_sms(
    member, staff, plan, django_capture_on_commit_callbacks, settings
):
    from payments.models import CashPaymentRequest
    from payments.services import reject_cash_request

    settings.SMS_NET_BD_API_KEY = "test-key"
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
    with patch("accounts.providers.send_sms_message") as send_sms:
        with patch("notifications.services.send_fcm_for_notification"):
            with django_capture_on_commit_callbacks(execute=True):
                reject_cash_request(staff, req.pk)
    send_sms.assert_called_once()
    assert "not approved" in send_sms.call_args.args[1]


@pytest.mark.django_db
def test_cash_request_pushes_staff(
    member, staff, plan, django_capture_on_commit_callbacks
):
    from payments.services import create_cash_request

    profile = member.member_profile
    profile.membership_status = "none"
    profile.profile_complete = True
    profile.save()
    register_device(staff, "staff-fcm-token", "android")
    with patch(
        "notifications.services._send_fcm",
    ) as send_fcm:
        with django_capture_on_commit_callbacks(execute=True):
            create_cash_request(member, {"plan_id": plan.pk})
    send_fcm.assert_called()
    kwargs = send_fcm.call_args.kwargs
    assert kwargs["data"]["type"] == "cash_request"
    assert kwargs["data"]["member_id"] == str(member.pk)
    assert "Cash payment request" in kwargs["title"]


@pytest.mark.django_db
def test_staff_can_register_fcm_device(client, staff):
    client.force_authenticate(staff)
    reg = client.post(
        "/api/v1/member/devices/fcm/",
        {"token": "staff-tok", "platform": "ios"},
        format="json",
    )
    assert reg.status_code == 200
    assert MemberDeviceToken.objects.filter(user=staff, token="staff-tok").exists()


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


def test_catalog_critical_sms_defaults():
    assert CATALOG["payment_received"][4] is True
    assert CATALOG["cash_request_rejected"][4] is True
    assert CATALOG["membership_expiring"][4] is True
    assert CATALOG["membership_expired"][4] is True
    assert CATALOG["fingerprint_ready"][4] is False
    assert CATALOG["membership_activated"][4] is False
    assert CATALOG["announcement"][4] is False


@pytest.mark.django_db
def test_create_notification_queues_sms_for_critical(
    member, django_capture_on_commit_callbacks
):
    with patch("notifications.services.send_sms_for_notification") as send_sms:
        with patch("notifications.services.send_fcm_for_notification"):
            with django_capture_on_commit_callbacks(execute=True):
                notif = create_notification(
                    member,
                    code="payment_received",
                    body_params={"amount": 3000},
                    related_object_id="pay-1",
                    push=False,
                )
    assert notif is not None
    assert notif.send_sms is True
    send_sms.assert_called_once_with(notif.pk)


@pytest.mark.django_db
def test_create_notification_skips_sms_for_fingerprint(
    member, django_capture_on_commit_callbacks
):
    with patch("notifications.services.send_sms_for_notification") as send_sms:
        with patch("notifications.services.send_fcm_for_notification"):
            with django_capture_on_commit_callbacks(execute=True):
                notif = create_notification(
                    member,
                    code="fingerprint_ready",
                    related_object_id="ready",
                    push=False,
                )
    assert notif is not None
    assert notif.send_sms is False
    send_sms.assert_not_called()


@pytest.mark.django_db
def test_format_sms_templates(member):
    payment = create_notification(
        member,
        code="payment_received",
        body_params={"amount": 3000},
        related_object_id="pay-sms",
        push=False,
        sms=False,
    )
    assert "৳3000" in format_sms(payment)
    announce = create_notification(
        member,
        code="announcement",
        title="Closed",
        body="Friday off",
        related_object_id="camp-1",
        push=False,
        sms=False,
    )
    assert format_sms(announce) == "Closed: Friday off"


@pytest.mark.django_db
def test_format_push_never_returns_arb_keys(member):
    rejected = create_notification(
        member,
        code="cash_request_rejected",
        related_object_id="cash-push",
        push=False,
        sms=False,
    )
    title, body = format_push(rejected)
    assert title == "নগদ পেমেন্ট প্রত্যাখ্যান"
    assert "মেম্বারশিপ থেকে আবার চেষ্টা করুন" in body
    assert "notifCashRejected" not in title
    assert "notifCashRejected" not in body

    payment = create_notification(
        member,
        code="payment_received",
        body_params={"amount": 3000},
        related_object_id="pay-push",
        push=False,
        sms=False,
    )
    pay_title, pay_body = format_push(payment)
    assert pay_title == "পেমেন্ট গৃহীত"
    assert "৳3000" in pay_body
    assert "notifPaymentReceived" not in pay_title

    announce = create_notification(
        member,
        code="announcement",
        title="Closed",
        body="Friday off",
        related_object_id="camp-push",
        push=False,
        sms=False,
    )
    assert format_push(announce) == ("Closed", "Friday off")


@pytest.mark.django_db
def test_send_fcm_uses_bangla_human_copy(member):
    register_device(member, "token-push-copy", "android")
    notif = create_notification(
        member,
        code="cash_request_rejected",
        related_object_id="cash-fcm",
        push=False,
        sms=False,
    )
    with patch("notifications.services._send_fcm") as send:
        result = send_fcm_for_notification(notif.pk)
    assert result["sent"] == 1
    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert kwargs["title"] == "নগদ পেমেন্ট প্রত্যাখ্যান"
    assert "notifCashRejectedTitle" not in kwargs["title"]
    assert "notifCashRejectedBody" not in kwargs["body"]
    assert kwargs["data"]["title_key"] == "notifCashRejectedTitle"
    assert kwargs["data"]["body_key"] == "notifCashRejectedBody"


@pytest.mark.django_db
def test_send_sms_for_notification_respects_opt_out(member):
    profile = member.member_profile
    profile.sms_enabled = False
    profile.save(update_fields=["sms_enabled", "updated_at"])
    notif = create_notification(
        member,
        code="cash_request_rejected",
        related_object_id="cash-1",
        push=False,
        sms=False,
    )
    with patch("accounts.providers.send_sms_message") as send:
        result = send_sms_for_notification(notif.pk)
    assert result["skipped"] == "sms_disabled"
    send.assert_not_called()


@pytest.mark.django_db
def test_admin_announcement_sms_default_off(client, member, staff, plan):
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.save()
    client.force_authenticate(staff)
    with patch("notifications.services.send_sms_for_notification") as send_sms:
        result = client.post(
            "/api/v1/admin/notifications/",
            {
                "scope": "member",
                "member_id": str(member.pk),
                "title": "Hi",
                "body": "No SMS",
                "send_push": False,
            },
            format="json",
        )
    assert result.status_code == 201
    assert result.data["sms_requested"] is False
    assert result.data["sms_sent"] == 0
    assert result.data["send_sms_requested"] is False
    send_sms.assert_not_called()
    fanout = MemberNotification.objects.get(user=member, code="announcement")
    assert fanout.send_sms is False


@pytest.mark.django_db
def test_admin_announcement_send_sms(client, member, staff, plan):
    profile = member.member_profile
    profile.membership_status = "active"
    profile.plan = plan
    profile.save()
    client.force_authenticate(staff)
    with patch(
        "notifications.services.send_sms_for_notification",
        return_value={"sent": 1, "failed": 0, "skipped": None},
    ) as send_sms:
        result = client.post(
            "/api/v1/admin/notifications/",
            {
                "scope": "member",
                "member_id": str(member.pk),
                "title": "Alert",
                "body": "Please renew",
                "send_push": False,
                "send_sms": True,
            },
            format="json",
        )
    assert result.status_code == 201
    assert result.data["sms_requested"] is True
    assert result.data["sms_sent"] == 1
    send_sms.assert_called_once()
    fanout = MemberNotification.objects.get(user=member, code="announcement")
    assert fanout.send_sms is True


@pytest.mark.django_db
def test_admin_announcement_resend_sms(client, member, staff, plan):
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
            "send_sms": False,
        },
        format="json",
    )
    campaign_id = created.data["id"]
    with patch(
        "notifications.services.send_sms_for_notification",
        return_value={"sent": 1, "failed": 0, "skipped": None},
    ) as send:
        resend = client.post(f"/api/v1/admin/notifications/{campaign_id}/resend-sms/")
    assert resend.status_code == 200
    assert resend.data["sms_sent"] == 1
    send.assert_called_once()
    fanout = MemberNotification.objects.get(
        code="announcement", related_object_id=str(campaign_id)
    )
    assert fanout.send_sms is True
