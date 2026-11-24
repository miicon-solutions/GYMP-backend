# Member

Authenticated member profile, photo, dashboard, and gym status.

- **OpenAPI:** `/openapi/v1/member.yaml`
- **Base path:** `/api/v1/member/`
- **Auth:** Bearer member JWT

## Typical flow

1. Complete profile once: `POST /api/v1/member/profile/complete/`
2. Read/update: `GET|PUT /api/v1/member/profile/`
3. Photo: `POST|DELETE /api/v1/member/profile/photo/` (multipart `photo`)
4. Dashboard: `GET /api/v1/member/dashboard/`
   - Includes `activated_on` (Dhaka date of first paid activation) when status is
     `active` / `expired`, for calendar lower-bound in the member app.
5. Gym status: `GET /api/v1/member/gym-status/`

### Sample — complete profile

```http
POST /api/v1/member/profile/complete/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "full_name": "Amina Rahman",
  "emergency_name": "Karim Rahman",
  "emergency_relationship": "spouse",
  "emergency_phone_e164": "+8801812345678",
  "blood_group": "B+"
}
```

## Scanner keypad credentials (admin-only)

Member self-profile **never** returns `device_keypad_id` / `device_pin`, and
`POST /api/v1/member/device-pin/regenerate/` is rejected.

Admin member detail (`GET /api/v1/admin/members/{id}/`) includes keypad id + PIN
when provisioned (after fingerprint enroll). Rotate via
`POST /api/v1/admin/members/{id}/device-pin/regenerate/`. Each PIN is
**single-use** — password unlock auto-rotates it (see `device` pack).

## Notes

- Membership stays `none` / `pending_payment` until cash accept or verified online payment.
- Phone change uses OTP proofs from the `auth` pack, then `POST …/profile/phone/change/`.
- Member plans listing is tagged `plans`; payments/cash-requests are tagged `payments`.
