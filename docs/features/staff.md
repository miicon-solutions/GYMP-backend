# Staff

Staff CRUD, activate/deactivate, permissions catalog, MFA enroll reset, and staff fingerprint vault.

- **OpenAPI:** `/openapi/v1/staff.yaml`
- **Base path:** `/api/v1/admin/staff/`
- **Auth:** Bearer staff; identity mutations are SuperOnly

## Own scanner credentials

Auth unlock / refresh `staff` objects may include owner-only `device_keypad_id` and
`device_pin` (digits-only keypad, no leading zeros, 4-digit PIN). Member keypad
credentials are admin-only (member detail), not in the member app. Rotate staff
PIN via `POST /api/v1/admin/me/device-pin/regenerate/` (`device` pack). Each PIN
unlocks **once** — password check-in rotates it automatically; reopen Manage →
Scanner keypad access (or the member detail) for the new PIN.

### Sample — permissions catalog

```http
GET /api/v1/admin/staff/permissions/catalog/
Authorization: Bearer <super_access_token>
```

`StaffProfile.permissions` is a list of `feature.action` codes. Empty list → no admin feature APIs for non-super staff.
