from __future__ import annotations

import pytest

from accounts.models import User
from accounts.staff_permissions import (
    all_permission_codes,
    effective_permissions,
    normalize_permissions,
    staff_has_permission,
)

pytestmark = pytest.mark.django_db


def test_super_effective_permissions_are_full_catalog(super_admin):
    codes = effective_permissions(super_admin)
    assert codes == all_permission_codes()
    assert staff_has_permission(super_admin, "members.delete")
    assert staff_has_permission(super_admin, "device_controllers.create")


def test_staff_without_grants_denied(client, staff):
    staff.staff_profile.permissions = []
    staff.staff_profile.save(update_fields=["permissions", "updated_at"])
    client.force_authenticate(staff)
    assert client.get("/api/v1/admin/members/").status_code == 403
    assert client.get("/api/v1/admin/revenue/").status_code == 403
    assert client.get("/api/v1/admin/costs/").status_code == 403


def test_staff_view_grant_allows_member_list(client, staff):
    staff.staff_profile.permissions = ["members.view"]
    staff.staff_profile.save(update_fields=["permissions", "updated_at"])
    client.force_authenticate(staff)
    assert client.get("/api/v1/admin/members/").status_code == 200
    assert client.get("/api/v1/admin/revenue/").status_code == 403


def test_create_staff_with_permissions(client, super_admin):
    client.force_authenticate(super_admin)
    resp = client.post(
        "/api/v1/admin/staff/",
        {
            "name": "Front Desk",
            "phone_e164": "+8801711002200",
            "is_active": True,
            "permissions": ["members.view", "members.update", "costs.view"],
        },
        format="json",
    )
    assert resp.status_code == 201
    assert set(resp.data["permissions"]) == {
        "members.view",
        "members.update",
        "costs.view",
    }
    created = User.objects.get(pk=resp.data["id"])
    assert created.staff_profile.permissions == sorted(
        ["members.view", "members.update", "costs.view"]
    )


def test_create_staff_rejects_unknown_permission(client, super_admin):
    client.force_authenticate(super_admin)
    resp = client.post(
        "/api/v1/admin/staff/",
        {
            "name": "Bad",
            "phone_e164": "+8801711002201",
            "permissions": ["members.view", "members.explode"],
        },
        format="json",
    )
    assert resp.status_code == 400


def test_staff_data_returns_stored_permissions(staff):
    from accounts.services import staff_data

    profile = staff.staff_profile
    profile.permissions = ["reports.view", "activity.view"]
    profile.save(update_fields=["permissions", "updated_at"])

    data = staff_data(staff)
    assert set(data["permissions"]) == {"activity.view", "reports.view"}


def test_super_unlock_permissions_are_full(super_admin):
    from accounts.services import staff_data

    data = staff_data(super_admin)
    assert data["is_super"] is True
    assert data["permissions"] == all_permission_codes()


def test_normalize_permissions_dedupes_and_sorts():
    assert normalize_permissions(["costs.view", "members.view", "costs.view"]) == [
        "costs.view",
        "members.view",
    ]


def test_permissions_catalog_super_only(client, staff, super_admin):
    client.force_authenticate(staff)
    assert client.get("/api/v1/admin/staff/permissions/catalog/").status_code == 403
    client.force_authenticate(super_admin)
    resp = client.get("/api/v1/admin/staff/permissions/catalog/")
    assert resp.status_code == 200
    features = {row["feature"] for row in resp.data["features"]}
    assert "members" in features
    assert "staff" in features
