import secrets

import pytest
from django.conf import settings as django_settings
from rest_framework.test import APIClient

from accounts.models import StaffProfile, User
from accounts.services import new_member
from plans.models import Plan


@pytest.fixture(scope="session", autouse=True)
def _refuse_live_database(django_db_setup, django_db_blocker):
    """Fail fast if pytest is pointed at the real app database."""
    with django_db_blocker.unblock():
        name = str(django_settings.DATABASES["default"]["NAME"])
    if not name.startswith("test"):
        pytest.exit(
            f"Refusing to run tests against live database {name!r}. "
            "Expected a name starting with 'test'.",
            returncode=1,
        )


@pytest.fixture(autouse=True)
def test_settings(settings, tmp_path):
    settings.OTP_DEV_BYPASS = True
    settings.EMAIL_DEV_BYPASS = True
    settings.TOTP_ENCRYPTION_KEY = "0" * 64
    settings.MEDIA_ROOT = tmp_path
    settings.MEDIA_STORAGE = "filesystem"
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.STATIC_ROOT = tmp_path / "static"
    settings.STATIC_ROOT.mkdir()
    settings.ATTENDANCE_DEVICE_KEY = "test-device-key"
    settings.PUBLIC_BASE_URL = "http://testserver"
    settings.WEB_APP_BASE_URL = ""


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def member(db):
    return new_member("+8801712345678")


@pytest.fixture
def other_member(db):
    return new_member("+8801812345678")


@pytest.fixture
def staff(db):
    from accounts.staff_permissions import all_permission_codes

    u = User.objects.create_user("+8801912345678", role="admin", full_name="Staff")
    StaffProfile.objects.create(
        user=u, short_id="S-TEST", permissions=all_permission_codes()
    )
    return u


@pytest.fixture
def super_admin(db):
    u = User.objects.create_superuser(
        "+8801612345678", password=secrets.token_urlsafe(24), full_name="Operator"
    )
    # create_superuser provisions its staff profile.
    return u


@pytest.fixture
def plan(db):
    return Plan.objects.create(
        name="Monthly", duration_months=1, monthly_rate_taka=1500, admission_fee_taka=1000
    )


@pytest.fixture
def profile_payload():
    return {
        "full_name": "Test Member",
        "emergency_name": "Test Parent",
        "emergency_relationship": "parent",
        "emergency_phone_e164": "+8801512345678",
        "blood_group": "O+",
    }
