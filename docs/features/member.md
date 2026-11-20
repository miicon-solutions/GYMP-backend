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

## Notes

- Membership stays `none` / `pending_payment` until cash accept or verified online payment.
- Phone change uses OTP proofs from the `auth` pack, then `POST …/profile/phone/change/`.
- Member plans listing is tagged `plans`; payments/cash-requests are tagged `payments`.
