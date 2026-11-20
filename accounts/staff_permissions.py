"""Feature + CRUD permission catalog for admin-app staff.

``is_superuser`` (seed ``SADM-7400``) always has every code. Non-super staff
carry an explicit list of ``feature.action`` strings on ``StaffProfile.permissions``.
Staff identity mutations (create / update / delete / activate / MFA enroll) stay
super-only and are not grantable.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied, ValidationError

# feature → allowed CRUD actions (subset of view/create/update/delete)
STAFF_PERMISSION_CATALOG: dict[str, tuple[str, ...]] = {
    "dashboard": ("view",),
    "members": ("view", "create", "update", "delete"),
    "reports": ("view",),
    "costs": ("view", "create", "update", "delete"),
    "plans": ("view", "create", "update", "delete"),
    "gym_hours": ("view", "create", "update", "delete"),
    "activity": ("view",),
    "staff": ("view",),
    "device_controllers": ("view", "create", "delete"),
    "notifications": ("view", "create"),
}

def all_permission_codes() -> list[str]:
    return [f"{feature}.{action}" for feature, actions in STAFF_PERMISSION_CATALOG.items() for action in actions]


def catalog_payload() -> list[dict]:
    """Wire shape for clients building the staff permission tree."""
    return [
        {"feature": feature, "actions": list(actions)}
        for feature, actions in STAFF_PERMISSION_CATALOG.items()
    ]


def permission_code(feature: str, action: str) -> str:
    return f"{feature}.{action}"


def is_valid_permission(code: str) -> bool:
    if not isinstance(code, str) or "." not in code:
        return False
    feature, _, action = code.partition(".")
    return feature in STAFF_PERMISSION_CATALOG and action in STAFF_PERMISSION_CATALOG[feature]


def normalize_permissions(raw) -> list[str]:
    """Validate and de-duplicate a permission list. Raises ValidationError."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError({"permissions": "Expected a list of permission codes."})
    seen: set[str] = set()
    out: list[str] = []
    invalid: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not is_valid_permission(item):
            invalid.append(str(item))
            continue
        if item not in seen:
            seen.add(item)
            out.append(item)
    if invalid:
        raise ValidationError(
            {"permissions": f"Unknown permission code(s): {', '.join(invalid)}."}
        )
    return sorted(out)


def stored_permissions(user) -> list[str]:
    profile = getattr(user, "staff_profile", None)
    if profile is None:
        return []
    raw = getattr(profile, "permissions", None) or []
    if not isinstance(raw, list):
        return []
    return [c for c in raw if isinstance(c, str) and is_valid_permission(c)]


def effective_permissions(user) -> list[str]:
    """Permissions the client should treat as granted (super → full catalog)."""
    if not user or not getattr(user, "is_active", False) or getattr(user, "role", None) != "admin":
        return []
    if getattr(user, "is_superuser", False):
        return all_permission_codes()
    return stored_permissions(user)


def staff_has_permission(user, code: str) -> bool:
    if not user or not getattr(user, "is_active", False) or getattr(user, "role", None) != "admin":
        return False
    if getattr(user, "is_superuser", False):
        return True
    if not is_valid_permission(code):
        return False
    return code in stored_permissions(user)


def require_staff_permission(user, code: str) -> None:
    if not staff_has_permission(user, code):
        raise PermissionDenied("You do not have permission for this action.")
