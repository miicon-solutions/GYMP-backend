import pyotp
import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.crypto import digest, encrypt_secret
from accounts.models import StaffProfile
from accounts.services import begin_mfa

pytestmark = pytest.mark.django_db


def enrollment_url(user):
    return reverse("admin:accounts_staffprofile_mfa_enroll", args=[user.staff_profile.pk])


def test_admin_mfa_confirmation_is_read_only(client, super_admin, staff):
    original_token = begin_mfa(staff)["setup_token"]
    client.force_login(super_admin)
    detail = client.get(
        reverse("admin:accounts_staffprofile_change", args=[staff.staff_profile.pk])
    )
    assert detail.status_code == 200
    assert enrollment_url(staff).encode() in detail.content
    response = client.get(enrollment_url(staff))
    assert response.status_code == 200
    assert b"Generate setup token" in response.content
    assert b"csrfmiddlewaretoken" in response.content
    assert original_token.encode() not in response.content
    staff.staff_profile.refresh_from_db()
    assert staff.staff_profile.setup_token_hash == digest(original_token)
    assert not LogEntry.objects.exists()


@pytest.mark.parametrize("self_reset", [False, True])
def test_admin_mfa_token_resets_and_completes_web_enrollment(
    client, super_admin, staff, self_reset
):
    target = super_admin if self_reset else staff
    old_token = begin_mfa(target)["setup_token"]
    profile = StaffProfile.objects.get(user=target)
    profile.totp_secret_encrypted = encrypt_secret(pyotp.random_base32())
    profile.mfa_enrolled_at = timezone.now()
    profile.totp_last_step = 123
    profile.save()
    client.force_login(super_admin)
    response = client.post(enrollment_url(target))
    assert response.status_code == 200
    token = response.context["setup"]["setup_token"]
    assert token != old_token
    assert token.encode() in response.content
    assert "no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "same-origin"
    profile.refresh_from_db()
    assert profile.setup_token_hash == digest(token)
    assert not profile.totp_secret_encrypted
    assert profile.mfa_enrolled_at is None
    assert profile.totp_last_step is None
    log = LogEntry.objects.get()
    assert log.user_id == super_admin.pk
    assert log.object_id == str(profile.pk)
    assert token not in log.change_message
    assert client.get(enrollment_url(target)).context["setup"] is None

    payload = {"phone_e164": target.phone_e164, "setup_token": token}
    rejected = client.post(
        "/api/v1/auth/admin/mfa/setup/", {**payload, "setup_token": old_token}, format="json"
    )
    assert rejected.status_code == 400
    setup = client.post("/api/v1/auth/admin/mfa/setup/", payload, format="json")
    assert setup.status_code == 200
    confirmed = client.post(
        "/api/v1/auth/admin/mfa/confirm/",
        {**payload, "totp_code": pyotp.TOTP(setup.data["secret_base32"]).now()},
        format="json",
    )
    assert confirmed.status_code == 200
    profile.refresh_from_db()
    assert profile.mfa_enrolled_at is not None
    assert not profile.setup_token_hash


@pytest.mark.parametrize("method", ["get", "post"])
def test_admin_mfa_requires_browser_login(client, staff, method):
    response = getattr(client, method)(enrollment_url(staff))
    assert response.status_code == 302
    assert "/admin/login/" in response.url
    assert not LogEntry.objects.exists()


@pytest.mark.parametrize("method", ["get", "post"])
def test_admin_mfa_denies_regular_browser_operator(client, staff, super_admin, method):
    staff.is_staff = True
    staff.save()
    staff.user_permissions.add(Permission.objects.get(codename="view_staffprofile"))
    client.force_login(staff)
    detail = client.get(
        reverse("admin:accounts_staffprofile_change", args=[super_admin.staff_profile.pk])
    )
    assert detail.status_code == 200
    assert enrollment_url(super_admin).encode() not in detail.content
    assert getattr(client, method)(enrollment_url(super_admin)).status_code == 403
    assert not LogEntry.objects.exists()


@pytest.mark.parametrize("secure", [False, True])
def test_admin_mfa_requires_csrf(super_admin, staff, secure):
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(super_admin)
    url = enrollment_url(staff)
    origin = "https://testserver" if secure else "http://testserver"
    assert browser.post(url, secure=secure, HTTP_ORIGIN=origin).status_code == 403
    confirmation = browser.get(url, secure=secure)
    assert confirmation.status_code == 200
    # no-referrer makes a browser's native form POST use Origin: null.
    assert confirmation["Referrer-Policy"] == "same-origin"
    assert (
        browser.post(
            url,
            {"csrfmiddlewaretoken": browser.cookies["csrftoken"].value},
            secure=secure,
            HTTP_ORIGIN=origin,
            HTTP_REFERER=origin + url,
        ).status_code
        == 200
    )
    assert LogEntry.objects.count() == 1


@pytest.mark.parametrize("origin", ["null", "https://untrusted.example"])
def test_admin_mfa_rejects_untrusted_origins(super_admin, staff, origin):
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(super_admin)
    url = enrollment_url(staff)
    browser.get(url)
    response = browser.post(
        url,
        {"csrfmiddlewaretoken": browser.cookies["csrftoken"].value},
        HTTP_ORIGIN=origin,
    )
    assert response.status_code == 403
    assert not LogEntry.objects.exists()
    staff.staff_profile.refresh_from_db()
    assert not staff.staff_profile.setup_token_hash


@pytest.mark.parametrize("method", ["get", "post"])
def test_admin_mfa_rejects_inactive_staff(client, super_admin, staff, method):
    original_token = begin_mfa(staff)["setup_token"]
    staff.is_active = False
    staff.save()
    client.force_login(super_admin)
    assert getattr(client, method)(enrollment_url(staff)).status_code == 404
    staff.staff_profile.refresh_from_db()
    assert staff.staff_profile.setup_token_hash == digest(original_token)


@pytest.mark.parametrize("object_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_admin_mfa_missing_profile(client, super_admin, object_id):
    client.force_login(super_admin)
    url = reverse("admin:accounts_staffprofile_mfa_enroll", args=[object_id])
    assert client.post(url).status_code == 404


def test_admin_mfa_rejects_other_methods(client, super_admin, staff):
    client.force_login(super_admin)
    response = client.put(enrollment_url(staff), {}, format="json")
    assert response.status_code == 405
    assert not LogEntry.objects.exists()
