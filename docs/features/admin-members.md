# Admin members

Staff APIs for member search/detail, phone link, fingerprint vault actions, and cash accept/reject.

- **OpenAPI:** `/openapi/v1/admin-members.yaml`
- **Base path:** `/api/v1/admin/members/` (+ `/api/v1/admin/cash-requests/`)
- **Auth:** Bearer staff JWT; feature permissions via `StaffProfile.permissions`

## Common operations

- `GET /api/v1/admin/members/?q=&status=unpaid|active|expired` — `q` matches temporary `PFT-####` before payment and `PF-####` after it (`PF-` / legacy `PG-` decoration on digits is ignored)
- `GET /api/v1/admin/members/{id}/`
- `DELETE /api/v1/admin/members/{id}/` — **super only**; hard-deletes **only** the member whose phone is `+8801307482200` (device revoke + related data). Any other member → 403. Django `/admin/` User delete stays unrestricted for any member.
- `POST …/phone/` — admin link member phone (OTP proof)
- Fingerprint: templates list/delete, interactive enroll, pull/push
- Cash: preview, legacy cash-payments, cash-requests accept/reject

### Sample — accept cash request

```http
POST /api/v1/admin/cash-requests/{id}/accept/
Authorization: Bearer <staff_access_token>
```

Returns `{ "request", "member", "payment" }` and activates membership using the frozen amount.

## Permissions

Non-super staff need grants such as `members.view` / `members.update`. Cash-request list needs `cash_requests.view`; accept/reject need `cash_requests.update`. Catalog: `GET /api/v1/admin/staff/permissions/catalog/` (staff feature).

Member account hard-delete via the app API is **super-only** and phone-allowlisted (`+8801307482200`). Having `members.delete` alone is not enough (that code still gates fingerprint template delete only).
