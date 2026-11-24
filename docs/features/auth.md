# Auth

Member OTP / Google sign-in, token refresh/logout, and staff TOTP MFA.

- **OpenAPI (feature):** `/openapi/v1/auth.yaml`
- **OpenAPI (full):** `/openapi/v1.yaml`
- **Docs UI:** `/docs/v1/`
- **Base path:** `/api/v1/auth/`
- **Auth:** public for login flows; Bearer access JWT after authenticate

## Agent ref

Fetch `/openapi/v1/auth.yaml` to wire the whole auth surface. Operation IDs are stable.

## Member OTP flow

1. `POST /api/v1/auth/resolve-phone/` — optional; returns `kind: member|staff|unknown`
2. `POST /api/v1/auth/otp/send/`
3. `POST /api/v1/auth/otp/verify/`
4. Store `access_token` + `refresh_token`; send `Authorization: Bearer <access_token>`
5. `POST /api/v1/auth/refresh/` when access expires (rotate both tokens)
6. `POST /api/v1/auth/logout/` to revoke refresh

### Sample — send OTP

```http
POST /api/v1/auth/otp/send/
Content-Type: application/json

{"phone_e164": "+8801712345678", "purpose": "onboarding"}
```

```json
{
  "otp_session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "expires_in_sec": 300,
  "resend_after_sec": 24,
  "dev_bypass": true
}
```

### Sample — verify OTP

```http
POST /api/v1/auth/otp/verify/
Content-Type: application/json

{
  "otp_session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "code": "000000"
}
```

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<opaque>",
  "token_type": "Bearer",
  "expires_in_sec": 3600,
  "member": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "member_id": "PF-0001",
    "phone_e164": "+8801712345678",
    "profile_complete": false,
    "membership_status": "none"
  }
}
```

Use code `000000` only when the server reports `dev_bypass` (local/dev). Production SMS delivers a random code.

## Google

1. `POST /api/v1/auth/google/` with `{ "id_token": "..." }`
2. If `status: "needsPhoneLink"`, complete phone OTP then `POST /api/v1/auth/google/link-phone/`
3. If `status: "authenticated"`, store tokens

## Staff MFA

1. `POST /api/v1/auth/admin/mfa/setup/` with phone + `setup_token`
2. `POST /api/v1/auth/admin/mfa/confirm/` with TOTP
3. Later unlock: `POST /api/v1/auth/admin/unlock/` with phone + `totp_code`

## Errors agents must handle

| Status | Meaning |
|---|---|
| 400 | Validation (field map) |
| 401 | Bad/missing token or OTP |
| 409 | Conflict (e.g. staff phone used for member OTP) |
| 429 | Resend/rate limit (`Retry-After`) |

## Staff token `staff` object

Unlock / refresh may include staff-only scanner fields when provisioned:

- `device_keypad_id` — digits-only panel id (no leading zeros)
- `device_pin` — 4-digit fingerprint-fail PIN (single-use; rotates after password unlock)

Members never receive these fields. See the `device` feature pack for regenerate.

## Related

Phone change and Google link on the member profile live under the `member` feature pack.
