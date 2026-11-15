from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from accounts.models import User
from operations.models import Holiday
from operations.services import gym_status, seed_hours
from payments.services import receive_cash

pytestmark = pytest.mark.django_db


def test_member_profile_completion_validation_and_update(client, member, profile_payload):
    client.force_authenticate(member)
    url = "/api/v1/member/profile/"
    assert client.get(url).data["profile_complete"] is False
    assert client.put(url, profile_payload, format="json").status_code == 400
    bad = {**profile_payload, "emergency_phone_e164": member.phone_e164}
    assert client.post(url + "complete/", bad, format="json").status_code == 400
    good = client.post(
        url + "complete/",
        {**profile_payload, "photo_url": "https://evil.example/photo"},
        format="json",
    )
    assert good.status_code == 200
    assert good.data["profile_complete"] is True
    assert good.data["photo_url"] is None
    assert client.post(url + "complete/", profile_payload, format="json").status_code == 409
    assert (
        client.put(url, {**profile_payload, "full_name": "Updated Name"}, format="json").data[
            "full_name"
        ]
        == "Updated Name"
    )
    assert (
        client.put(url, {**profile_payload, "full_name": "123bad"}, format="json").status_code
        == 400
    )


@pytest.mark.parametrize(
    "fmt,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")]
)
def test_photo_upload_public_serve_and_delete(client, member, fmt, mime):
    client.force_authenticate(member)
    buf = BytesIO()
    Image.new("RGB", (8, 8), (255, 0, 0)).save(buf, format=fmt)
    response = client.post(
        "/api/v1/member/profile/photo/",
        {"photo": SimpleUploadedFile("image.bin", buf.getvalue(), content_type=mime)},
        format="multipart",
    )
    assert response.status_code == 200
    photo_url = response.data["photo_url"]
    assert photo_url.startswith("http://testserver/media/member-photos/")
    public = client.get(photo_url.removeprefix("http://testserver"))
    assert public.status_code == 200
    assert public["Content-Type"] == mime
    assert client.delete("/api/v1/member/profile/photo/").status_code == 204
    assert client.get("/api/v1/member/profile/").data["photo_url"] is None


def test_invalid_photo_and_path_traversal(client, member):
    client.force_authenticate(member)
    url = "/api/v1/member/profile/photo/"
    assert (
        client.post(
            url,
            {"photo": SimpleUploadedFile("fake.jpg", b"not image", content_type="image/jpeg")},
            format="multipart",
        ).status_code
        == 400
    )
    assert (
        client.post(
            url,
            {
                "photo": SimpleUploadedFile(
                    "huge.png", b"x" * (5 * 1024 * 1024 + 1), content_type="image/png"
                )
            },
            format="multipart",
        ).status_code
        == 413
    )
    assert client.get("/media/member-photos/settings.py").status_code == 404


def test_recovery_email_existing_limitations(client, member, settings):
    client.force_authenticate(member)
    url = "/api/v1/member/profile/phone/recover-email/"
    assert client.post(url, {}, format="json").status_code == 403
    member.firebase_uid = "google-id"
    member.email = "user@example.com"
    member.save()
    assert client.post(url, {}, format="json").data == {"sent": True, "dev_bypass": True}
    assert client.post(url, {}, format="json").status_code == 429
    member.member_profile.recovery_sent_at = timezone.now() - timedelta(seconds=61)
    member.member_profile.save()
    settings.EMAIL_DEV_BYPASS = False
    assert client.post(url, {}, format="json").status_code == 502


def test_staff_crud_and_super_protection(client, staff, super_admin, member):
    url = "/api/v1/admin/staff/"
    client.force_authenticate(staff)
    assert client.get(url).status_code == 200
    body = {"name": "New Staff", "phone_e164": "+8801312345678"}
    assert client.post(url, body, format="json").status_code == 403
    client.force_authenticate(super_admin)
    assert (
        client.post(url, {**body, "phone_e164": member.phone_e164}, format="json").status_code
        == 409
    )
    new = client.post(url, body, format="json")
    assert new.status_code == 201
    ident = new.data["id"]
    assert (
        client.patch(url + str(ident) + "/", {"name": "Changed"}, format="json").data["name"]
        == "Changed"
    )
    assert (
        client.post(url + str(ident) + "/deactivate/", {}, format="json").data["is_active"] is False
    )
    assert client.post(url + str(ident) + "/activate/", {}, format="json").data["is_active"] is True
    assert client.post(url + str(ident) + "/mfa/enroll/", {}, format="json").data["setup_token"]
    assert client.delete(f"{url}{super_admin.pk}/").status_code == 403
    assert client.post(f"{url}{super_admin.pk}/deactivate/", {}, format="json").status_code == 403
    assert (
        client.patch(
            f"{url}{super_admin.pk}/", {"phone_e164": "+8801412345678"}, format="json"
        ).status_code
        == 403
    )
    assert client.delete(url + str(ident) + "/").status_code == 204
    assert not User.objects.filter(pk=ident).exists()


def test_cost_crud_and_activity_filters(client, staff):
    client.force_authenticate(staff)
    url = "/api/v1/admin/costs/"
    response = client.post(
        url,
        {
            "title": "Rent",
            "category": "rent",
            "amount_taka": 10000,
            "date": "2026-11-01",
            "note": "Test",
        },
        format="json",
    )
    assert response.status_code == 201
    ident = response.data["id"]
    assert client.patch(f"{url}{ident}/", {"note": None}, format="json").data["note"] is None
    assert client.post(f"{url}{ident}/archive/", {}, format="json").data["is_archived"] is True
    assert client.get(url).data["results"] == []
    assert len(client.get(url, {"include_archived": "true"}).data["results"]) == 1
    activity = client.get(
        "/api/v1/admin/activity/", {"area": "cost", "q": "Rent", "sort": "oldest"}
    )
    assert activity.status_code == 200
    assert len(activity.data["results"]) == 3
    assert activity.data["results"][0]["action"] == "create"
    assert client.get("/api/v1/admin/activity/", {"admin_id": "bad"}).status_code == 400
    assert client.delete(f"{url}{ident}/").status_code == 204


def test_gym_hours_holidays_and_status(client, staff):
    seed_hours()
    saturday = datetime(2026, 11, 14, 1, tzinfo=UTC)  # 07:00 Dhaka
    assert gym_status(saturday)["is_open_now"] is True
    assert gym_status(datetime(2026, 11, 14, 16, tzinfo=UTC))["is_open_now"] is False
    assert gym_status(datetime(2026, 11, 13, 6, tzinfo=UTC))["today_is_weekly_closed"] is True
    assert gym_status(saturday)["hours_summary"] == "06:00 AM – 10:00 PM (Sat – Thu)"
    Holiday.objects.create(date=saturday.date(), name="Closure")
    assert gym_status(saturday)["closed_day_label"] == "Closure"
    client.force_authenticate(staff)
    week = client.get("/api/v1/admin/gym-hours/").data["week"]
    assert (
        client.put("/api/v1/admin/gym-hours/week/", {"week": week[:6]}, format="json").status_code
        == 400
    )
    week[0]["open_time"] = "23:00"
    assert (
        client.put("/api/v1/admin/gym-hours/week/", {"week": week}, format="json").status_code
        == 400
    )
    week[0]["open_time"] = "07:00"
    assert (
        client.put("/api/v1/admin/gym-hours/week/", {"week": week}, format="json").status_code
        == 200
    )
    url = "/api/v1/admin/gym-hours/holidays/"
    holiday = client.post(url, {"date": "2026-12-01", "name": "Holiday"}, format="json")
    assert holiday.status_code == 201
    ident = holiday.data["id"]
    assert client.patch(f"{url}{ident}/", {"name": "Updated"}, format="json").status_code == 200
    assert client.delete(f"{url}{ident}/").status_code == 204


def test_attendance_device_and_member_dashboard(client, member, staff, plan):
    seed_hours()
    url = "/api/v1/internal/attendance/check-in/"
    body = {"member_id": member.member_profile.member_id, "checked_in_at": "2026-11-14T20:30:00Z"}
    assert client.post(url, body, format="json").status_code == 401
    response = client.post(url, body, format="json", HTTP_X_DEVICE_KEY="test-device-key")
    assert response.status_code == 200
    assert str(response.data["day"]) == "2026-11-15"
    assert response.data["recorded"] is True
    assert (
        client.post(url, body, format="json", HTTP_X_DEVICE_KEY="test-device-key").data["recorded"]
        is False
    )
    receive_cash(staff, member.member_profile, plan.pk)
    client.force_authenticate(member)
    month = client.get("/api/v1/member/attendance/", {"year": 2026, "month": 11})
    assert month.status_code == 200 and month.data["visit_count"] == 1
    assert month.data["closed_weekday"] == 5
    assert client.get("/api/v1/member/attendance/", {"month": 13}).status_code == 400
    dashboard = client.get("/api/v1/member/dashboard/")
    assert dashboard.status_code == 200
    assert dashboard.data["fingerprint_status"] == "pending"
    assert dashboard.data["has_unread_notifications"] is False
    assert len(dashboard.data["payment_preview"]) == 1
    assert dashboard.data["status"] == "active"
    client.force_authenticate(staff)
    detail = client.get(f"/api/v1/admin/members/{member.pk}/")
    assert detail.data["last_paid_at"] is not None
    assert client.get("/api/v1/admin/members/", {"q": member.phone_e164}).data["results"][0][
        "id"
    ] == str(member.pk)
    assert (
        client.post(
            f"/api/v1/admin/members/{member.pk}/fingerprint/", {"status": "ready"}, format="json"
        ).data["fingerprint_status"]
        == "ready"
    )
