# Admin members

Staff APIs for member search/detail, phone link, fingerprint vault actions, and cash accept/reject.

- **OpenAPI:** `/openapi/v1/admin-members.yaml`
- **Base path:** `/api/v1/admin/members/` (+ `/api/v1/admin/cash-requests/`)
- **Auth:** Bearer staff JWT; feature permissions via `StaffProfile.permissions`

## Common operations

- `GET /api/v1/admin/members/?q=&status=unpaid|active|expired`
- `GET|PATCH /api/v1/admin/members/{id}/`
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
