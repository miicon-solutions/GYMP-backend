# API migration reference

The Django backend intentionally breaks the Go wire contract. The Flutter client in `GYMA_a` now targets this contract. Configure its API origin for this backend and use this document alongside [the generated schema](openapi/v1.yaml) and [feature packs](features/). There is no legacy `/v1/` compatibility alias and no data/session import. For day-to-day integration prefer `/docs/` and `/openapi/v1/{feature}.yaml`; this file remains the Go→Django migration history.

## Common changes

| Concern | Go | Django |
|---|---|---|
| API prefix | `/v1/` (welcome separately `/api/v1/`) | `/api/v1/` everywhere |
| Trailing slash | Normally absent | Required for API routes |
| Object success | `{"data": {...}}` | Resource object directly |
| Collections | Arrays/envelopes or page metadata | `{"next": null, "previous": null, "results": [...]}` |
| Pagination | Mixed `page`/`cursor`/`limit` | DRF opaque cursor; `limit` default 50, max 100 |
| JSON/query fields | camelCase | snake_case, including nested receipt lines and activity parameters |
| Validation errors | 422 + custom error envelope | 400 + field-to-error-list map |
| Other errors | Custom `{error: {kind, message}}` | `{"detail": "Short message."}` |
| Roles | Member/admin/super | Same authority, checked against the active database user |
| Tokens | Go JWT claims and opaque refresh records | New HS256 access JWT claims and new opaque refresh sessions |
| IDs | Go database UUIDs | Fresh Django user UUIDs and new data |

Send canonical slash-terminated URLs directly, especially for POST/PATCH/PUT; do not rely on redirecting request bodies. Dates are `YYYY-MM-DD`; instants are ISO 8601 with an offset. Monetary values are integer BDT taka. Error field arrays contain short strings. Status codes include 401 unauthenticated, 403 unauthorized role, 404 absent/not-owned resource, 409 conflict, 413 oversized upload, 429 cooldown/rate limit (with `Retry-After`), 502 provider failure, and safe 500 errors.

Member and staff API identity IDs are **user UUIDs**. Internal profile UUIDs are not public account identifiers. Human member display ids are temporary `PFT-0001` until first payment, then `PF-0001`. Device keypad ids are digits-only (`device_keypad_id`). API staff identifiers follow `ADM-1001`, etc.; the bootstrap super admin has `S-ADM-7400`. New UUIDs, sessions, and authenticator enrollment are independent of the Go service.

Business enum values remain unchanged, including `confirmCurrentPhone`, `changePhone`, `adminLinkMemberPhone`, `needsPhoneLink`, online payment kinds (`first_purchase`, `renew`, `change_plan`) and cash kinds (`first_payment`, `renewal`, `plan_change`). Field names change; enum strings do not. Activity `summary_key` localization identifiers are unchanged; parameter field names are snake_case.

## Authentication examples

All login and refresh results return `access_token`, `refresh_token`, `token_type: "Bearer"`, `expires_in_sec`, and either `member` or `staff`. Pass the access token as `Authorization: Bearer <access_token>`. Refresh tokens are opaque and rotate on every successful refresh; replace both cached credentials atomically. Logout revokes the submitted refresh token. Go-issued credentials are not accepted.

```json
POST /api/v1/auth/otp/send/
{"phone_e164": "+8801712345678", "purpose": "onboarding"}

POST /api/v1/auth/otp/verify/
{"otp_session_id": "<uuid>", "code": "000000"}

POST /api/v1/auth/refresh/
{"refresh_token": "<opaque refresh token>"}

POST /api/v1/auth/logout/
{"refresh_token": "<opaque refresh token>"}
```

Use `000000` only when the server explicitly reports a development bypass. In production SMS delivers a random code. OTP sessions expire after 300 seconds, allow five failed attempts, and enforce a 24-second resend cooldown by default. Hashes bind a code to its session ID. Consumed, expired, or differently scoped OTPs cannot be reused.

Phone changes retain the original proof flow:

1. As a member, send/verify `confirmCurrentPhone` for the current phone.
2. Send `changePhone` for the new phone with `current_phone_proof` from step 1.
3. Verify the new challenge to obtain `phone_proof_token` with `proof_kind: "changePhone"`.
4. Submit that token to `/api/v1/member/profile/phone/change/`.

Proofs expire after 15 minutes and cannot authenticate API requests. Staff linking uses `adminLinkMemberPhone`, `target_member_id` (user UUID), and the initiating admin's token. Submit that challenge/code to the target member's administrative `/phone/` endpoint; the generic OTP verifier rejects it.

`GET /api/v1/public/config/` returns `google_sign_in`. That flag is true only when `FIREBASE_CREDENTIALS_FILE` is set. When it is false, hide Google sign-in: `auth/google/`, `auth/google/link-phone/`, and `member/profile/link-google/` respond 404 with "Google sign-in is not available." When it is true, Google accepts `id_token`; a new identity returns `status: "needsPhoneLink"` and `google_session_id`. Complete phone OTP onboarding, then submit `google_session_id`, `otp_session_id`, and `code` to `auth/google/link-phone/`. Known identities return `status: "authenticated"` with tokens. Existing phone-first members use `member/profile/link-google/` with a verified Google `id_token`.

Staff MFA setup/confirm accept `phone_e164`, `setup_token`, and (confirm only) `totp_code`. Unlock accepts `phone_e164` and `totp_code`. A super admin starts/reset enrollment using the target staff's `/mfa/enroll/` operation. API staff have no browser password access unless explicitly provisioned as an operator.

## Resource payloads

Public OTP/Google onboarding creates an information-only member account. Profile completion leaves `membership_status` as `none`; existing `pending_payment` accounts are also unpaid. Keep these accounts able to sign in and edit their own details. A successful staff cash collection or verified online payment activates the membership; neither signup nor profile completion does so. Cash preview/collection require `profile_complete`, as online checkout already does. Device check-in returns 403 for either unpaid status. Member login uses OTP/Google without authenticator MFA; staff TOTP requirements are unchanged.

`GET /api/v1/admin/members/` accepts optional `status=unpaid|active|expired` alongside `q` and cursor pagination. `unpaid` matches both `none` and `pending_payment`; omitted status returns all members, and invalid values return 400.

- **Profile write:** `full_name`, `emergency_name`, `emergency_relationship`, `emergency_phone_e164`, `blood_group`. Completion is a one-time operation; later writes use PUT. Photos belong exclusively to multipart `photo` uploads. Client-supplied `photo_url` is ignored. Photos are JPEG/PNG/WebP up to 5 MB, validated from file contents; deletion returns 204. With MinIO/S3 storage, `photo_url` is a private signed absolute URL, valid for `AWS_QUERYSTRING_EXPIRE` seconds (default 3600). Fetch the profile again to refresh an expired link; do not persist the URL or assume an API-host media path. Downloading the signed URL does not require the API Bearer token, so treat it as a temporary access credential.
- **Plans:** write `name`, `monthly_rate_taka`, `admission_fee_taka`, `duration_months`, `discount_type`, `discount_value`, `is_active`. Durations are 1/3/6/9/12 months and globally unique. `catalog_id` and computed prices are read-only. The legacy `renewal_taka` write alias is retired; use `monthly_rate_taka`. Standing and offer percentage discounts each apply to full period coverage, use integer truncation, and together clamp the renewal price at zero.
- **Offers:** `name`, `starts_on`, `ends_on`, `waive_admission`, `extra_discount_type`, `extra_discount_value`, `is_active`. Active ranges on one plan cannot overlap. End dates are inclusive. Expired offers stop affecting prices immediately and are lazily deactivated on catalog reads.
- **Staff:** `name`, `phone_e164`, `is_active`, optional `is_super`. Only a super admin can mutate staff or reset enrollment. `is_super: true` creates or promotes another super admin. The last active super admin cannot be deactivated, demoted, or deleted. A super admin phone cannot be changed through this API. Browser operator access is not granted here.
- **Costs:** `title`, `category`, `amount_taka`, `date`, nullable `note`. PATCH with `note: null` clears it; `clear_note: true` is also supported. List uses `include_archived`; archive is an action.
- **Gym hours:** weekly PUT uses `{ "week": [...] }` with exactly ISO weekdays 1–7. Each row contains `weekday`, `is_open`, and nullable `open_time`/`close_time` (`HH:mm`). Open days must open before closing. Holiday writes use `date` and nullable `name`; holiday closure overrides weekly hours.
- **Activity filters:** `q`, `area`, `action`, `admin_id`, `sort` (`newest`/`oldest`), `from`, `to`, cursor/limit. Keep filters and sort unchanged while following cursor URLs.
- **Member search:** `q` matches display ID, name, or phone. Details include membership/plan/expiry, latest paid timestamp, and fingerprint state. Fingerprint action accepts `status: pending|ready|failed`.
- **Attendance:** member calendar takes `year`, `month`. Device POST takes display `member_id`, optional `checked_in_at`, and `source: device|admin|manual`, authenticated with `X-Device-Key`. The database deduplicates by member and Asia/Dhaka day, returning `recorded: false` for a duplicate.

Read/write serializers, required fields, response properties, and canonical paths are published in OpenAPI. API create operations return 201 where a resource is created; actions generally return 200. Deletions/logout return 204. Deleting a catalog plan deactivates it. Deleting a custom plan with membership/payment history returns 409; deactivate it instead. Historical payment/account references are protected.

## Payments, dates, and reporting

Create checkout sessions with `kind`, `plan_id`, and optional `checkout: "hosted"|"sdk"`. Hosted returns `gateway_url`; SDK initiation uses the server's `tran_id`/amount and leaves the URL empty. Both flows poll the session URL or POST its `/confirm/` action. Those operations enforce member ownership and query SSLCommerz server-side.

SSLCommerz IPNs keep provider field names `tran_id`, `val_id`, and `status`; JSON and form-encoded callbacks are supported. The merchant validation/query response must identify the exact transaction, amount, BDT currency, acceptable risk, and validation ID. Browser return pages never activate a membership. Duplicate validated callbacks create one payment and extend membership once.

The port fixes two unsafe legacy behaviors: callbacks with invalid/unrelated validation IDs cannot change another checkout's state, and negative callbacks are checked against the merchant transaction query before failure is recorded. Checkout price, receipt lines, and plan duration are frozen when the session is created, so a later plan edit or expired offer cannot alter that checkout. Cash likewise takes one price snapshot under plan/member locks.

Cash preview takes query `plan_id`; cash receive takes `{ "plan_id": "<uuid>" }` and returns `{ "member": {...}, "payment": {...} }`. The server determines price/kind; a posted amount is ignored. Activation changes fingerprint `not_required` to `pending` and preserves `ready` on later purchases.

Members may also request cash at first purchase: `POST /api/v1/member/payments/cash-requests/` with `{ "plan_id" }` creates a pending `CashPaymentRequest`, freezes the first-payment price snapshot, sets `membership_status` to `pending_payment`, and cancels any prior pending cash request or first-purchase SSL session. Members poll `GET .../cash-requests/{id}/` (or list via `GET .../cash-requests/list/?status=pending`) and may `POST .../cancel/` while pending. Staff list pending requests at `GET /api/v1/admin/cash-requests/?status=pending`, inspect per member at `GET /api/v1/admin/members/{id}/cash-requests/`, then `POST .../accept/` (records cash using the frozen amount, activates membership, idempotent) or `POST .../reject/` (returns the member to `none` when still unpaid). Legacy `POST .../cash-payments/` for the same member and plan auto-accepts a matching pending request so the counter flow does not double-charge.

Membership expiry uses fixed day packs mapped from `duration_months` (1→30, 3→90, 6→180, 9→270, 12→365). The start day counts: first purchase sets `expires_on` to today+(N−1) (e.g. 19 Nov monthly → 18 Dec). Eligible renewals/extensions add the full pack from the current last-valid `expires_on`. Online expiry bases dates on UTC; cash uses Asia/Dhaka. Dashboard `days_left` is inclusive remaining UTC calendar days (`expires_on − today + 1` while not past expiry), clamped to 0–9999. Attendance, gym hours, and offer eligibility use Asia/Dhaka. Daily host cron `notify_membership_expiry` (see `make cron-expiry`) rewrites still-`active` profiles with `expires_on < today` to `expired` and sends push/SMS; there is no in-process Celery/Redis scheduler.

Revenue accepts `range: day|week|month|overall|custom|dates`, `date`, `from`, `to`, comma-separated `dates`, `member_id`, `channel: all|cash|sslcommerz`, and `limit` (1–100, default 50). Nonempty `dates` overrides the range and deduplicates/sorts up to 62 days. Week means the selected date plus its preceding six days. Report defaults use the Dhaka date; payment filtering/chart dates preserve UTC day semantics. Totals cover **all** matching database rows (removing the old 5000-row aggregate cap); `limit` bounds only the embedded payment rows. Overall and custom ranges longer than 90 days use monthly series; shorter custom/week ranges include zero-value buckets.

Receipts remain private, requiring the member Bearer token even when opening the HTML URL. Payment history uses cursor pagination; dashboard previews remain bounded to five entries. Django's operator console allows CRUD for registered business models while keeping auth secrets and payment gateway session material off the forms; online settlement still goes through the payment services.

## Complete route mapping

Placeholders such as `{id}` are UUIDs except `{tranId}` (merchant transaction reference) and `{outcome}` (`success|fail|cancel`). Duplicate `/docs` registrations share the same canonical destination. Media URLs are storage-generated URLs, not collection APIs. In MinIO/S3 mode the legacy `/media/member-photos/<generated-filename>` route returns 404; only optional filesystem mode serves that route publicly.

| Method | Go path | Django path |
|---|---|---|
| GET | `/v1/admin/activity` | `/api/v1/admin/activity/` |
| GET | `/v1/admin/members` | `/api/v1/admin/members/` |
| GET | `/v1/admin/members/:id` | `/api/v1/admin/members/{id}/` |
| GET | `/v1/admin/members/:id/cash-preview` | `/api/v1/admin/members/{id}/cash-preview/` |
| POST | `/v1/admin/members/:id/cash-payments` | `/api/v1/admin/members/{id}/cash-payments/` |
| GET | (new) admin pending cash requests | `/api/v1/admin/cash-requests/` |
| GET | (new) admin member cash requests | `/api/v1/admin/members/{id}/cash-requests/` |
| POST | (new) accept cash request | `/api/v1/admin/cash-requests/{id}/accept/` |
| POST | (new) reject cash request | `/api/v1/admin/cash-requests/{id}/reject/` |
| POST | (new) member create cash request | `/api/v1/member/payments/cash-requests/` |
| GET | (new) member list cash requests | `/api/v1/member/payments/cash-requests/list/` |
| GET | (new) member get cash request | `/api/v1/member/payments/cash-requests/{id}/` |
| POST | (new) member cancel cash request | `/api/v1/member/payments/cash-requests/{id}/cancel/` |
| POST | `/v1/admin/members/:id/phone` | `/api/v1/admin/members/{id}/phone/` |
| POST | `/v1/admin/members/:id/fingerprint` | `/api/v1/admin/members/{id}/fingerprint/` |
| GET | `/v1/admin/device/status` | `/api/v1/admin/device/status/` |
| GET | (new) list vault finger indexes | `/api/v1/admin/members/{id}/fingerprint/templates/` |
| DELETE | (new) delete vault+device finger | `/api/v1/admin/members/{id}/fingerprint/templates/{finger_id}/` |
| POST | `/v1/admin/members/:id/fingerprint/enroll` | `/api/v1/admin/members/{id}/fingerprint/enroll/` (interactive; body `finger_id` 0–9) |
| POST | (new) pull templates to vault | `/api/v1/admin/members/{id}/fingerprint/pull/` |
| POST | (new) push vault to device | `/api/v1/admin/members/{id}/fingerprint/push/` |
| GET | (new) staff vault finger indexes | `/api/v1/admin/staff/{id}/fingerprint/templates/` |
| DELETE | (new) staff vault+device finger | `/api/v1/admin/staff/{id}/fingerprint/templates/{finger_id}/` |
| POST | (new) staff interactive enroll | `/api/v1/admin/staff/{id}/fingerprint/enroll/` |
| POST | (new) staff pull / push | `/api/v1/admin/staff/{id}/fingerprint/pull/` · `…/push/` |
| GET/POST | (new) device controllers (super) | `/api/v1/admin/device/controllers/` |
| DELETE | (new) remove device controller | `/api/v1/admin/device/controllers/{staff_id}/` |
| GET | `/v1/member/attendance` | `/api/v1/member/attendance/` |
| POST | `/v1/internal/attendance/check-in` | `/api/v1/internal/attendance/check-in/` |
| POST | `/v1/auth/resolve-phone` | `/api/v1/auth/resolve-phone/` |
| POST | `/v1/auth/otp/send` | `/api/v1/auth/otp/send/` |
| POST | `/v1/auth/otp/verify` | `/api/v1/auth/otp/verify/` |
| GET | (new) public auth config | `/api/v1/public/config/` |
| POST | `/v1/auth/google` | `/api/v1/auth/google/` |
| POST | `/v1/auth/google/link-phone` | `/api/v1/auth/google/link-phone/` |
| POST | `/v1/auth/admin/unlock` | `/api/v1/auth/admin/unlock/` |
| POST | `/v1/auth/admin/mfa/setup` | `/api/v1/auth/admin/mfa/setup/` |
| POST | `/v1/auth/admin/mfa/confirm` | `/api/v1/auth/admin/mfa/confirm/` |
| POST | `/v1/auth/refresh` | `/api/v1/auth/refresh/` |
| POST | `/v1/auth/logout` | `/api/v1/auth/logout/` |
| POST | `/v1/member/profile/link-google` | `/api/v1/member/profile/link-google/` |
| POST | `/v1/admin/staff/:id/mfa/enroll` | `/api/v1/admin/staff/{id}/mfa/enroll/` |
| GET | `/v1/admin/costs` | `/api/v1/admin/costs/` |
| POST | `/v1/admin/costs` | `/api/v1/admin/costs/` |
| PATCH | `/v1/admin/costs/:id` | `/api/v1/admin/costs/{id}/` |
| POST | `/v1/admin/costs/:id/archive` | `/api/v1/admin/costs/{id}/archive/` |
| DELETE | `/v1/admin/costs/:id` | `/api/v1/admin/costs/{id}/` |
| GET | `/v1/member/dashboard` | `/api/v1/member/dashboard/` |
| GET | `/` | `/` |
| GET | `/docs` | `/docs/` |
| GET | `/docs/` | `/docs/` |
| GET | `/openapi.yaml` | `/openapi.yaml` |
| GET | `/v1/admin/gym-hours` | `/api/v1/admin/gym-hours/` |
| PUT | `/v1/admin/gym-hours/week` | `/api/v1/admin/gym-hours/week/` |
| GET | `/v1/admin/gym-hours/holidays` | `/api/v1/admin/gym-hours/holidays/` |
| POST | `/v1/admin/gym-hours/holidays` | `/api/v1/admin/gym-hours/holidays/` |
| PATCH | `/v1/admin/gym-hours/holidays/:id` | `/api/v1/admin/gym-hours/holidays/{id}/` |
| DELETE | `/v1/admin/gym-hours/holidays/:id` | `/api/v1/admin/gym-hours/holidays/{id}/` |
| GET | `/v1/member/gym-status` | `/api/v1/member/gym-status/` |
| GET | `/health` | `/health/` |
| GET | `/v1/member/profile` | `/api/v1/member/profile/` |
| PUT | `/v1/member/profile` | `/api/v1/member/profile/` |
| POST | `/v1/member/profile/complete` | `/api/v1/member/profile/complete/` |
| POST | `/v1/member/profile/phone/change` | `/api/v1/member/profile/phone/change/` |
| POST | `/v1/member/profile/phone/recover-email` | `/api/v1/member/profile/phone/recover-email/` |
| POST | `/v1/member/profile/photo` | `/api/v1/member/profile/photo/` |
| DELETE | `/v1/member/profile/photo` | `/api/v1/member/profile/photo/` |
| POST | `/v1/member/payments/sessions` | `/api/v1/member/payments/sessions/` |
| GET | `/v1/member/payments/sessions/:tranId` | `/api/v1/member/payments/sessions/{tranId}/` |
| POST | `/v1/member/payments/sessions/:tranId/confirm` | `/api/v1/member/payments/sessions/{tranId}/confirm/` |
| GET | `/v1/member/payments` | `/api/v1/member/payments/` |
| GET | `/v1/member/payments/:id` | `/api/v1/member/payments/{id}/` |
| GET | `/v1/member/payments/:id/receipt` | `/api/v1/member/payments/{id}/receipt/` |
| GET | `/v1/member/payments/:id/receipt.html` | `/api/v1/member/payments/{id}/receipt.html/` |
| POST | `/v1/webhooks/sslcommerz/ipn` | `/api/v1/webhooks/sslcommerz/ipn/` |
| GET | `/payments/return/:outcome` | `/payments/return/{outcome}/` |
| GET | `/v1/admin/plans` | `/api/v1/admin/plans/` |
| POST | `/v1/admin/plans` | `/api/v1/admin/plans/` |
| PATCH | `/v1/admin/plans/:id` | `/api/v1/admin/plans/{id}/` |
| DELETE | `/v1/admin/plans/:id` | `/api/v1/admin/plans/{id}/` |
| GET | `/v1/admin/plans/:id/offers` | `/api/v1/admin/plans/{id}/offers/` |
| POST | `/v1/admin/plans/:id/offers` | `/api/v1/admin/plans/{id}/offers/` |
| PATCH | `/v1/admin/plans/:id/offers/:offerId` | `/api/v1/admin/plans/{id}/offers/{offerId}/` |
| DELETE | `/v1/admin/plans/:id/offers/:offerId` | `/api/v1/admin/plans/{id}/offers/{offerId}/` |
| GET | `/v1/member/plans` | `/api/v1/member/plans/` |
| GET | `/v1/member/plans/:planId` | `/api/v1/member/plans/{planId}/` |
| GET | `/v1/admin/revenue` | `/api/v1/admin/revenue/` |
| GET | `/v1/admin/staff` | `/api/v1/admin/staff/` (`staff.view`) |
| GET | (new) permission catalog | `/api/v1/admin/staff/permissions/catalog/` (super) |
| POST | `/v1/admin/staff` | `/api/v1/admin/staff/` (super; optional `permissions`) |
| PATCH | `/v1/admin/staff/:id` | `/api/v1/admin/staff/{id}/` (super; optional `permissions`) |
| DELETE | `/v1/admin/staff/:id` | `/api/v1/admin/staff/{id}/` |
| POST | `/v1/admin/staff/:id/activate` | `/api/v1/admin/staff/{id}/activate/` |
| POST | `/v1/admin/staff/:id/deactivate` | `/api/v1/admin/staff/{id}/deactivate/` |
| GET | `/api/v1/welcome` | `/api/v1/welcome/` |

The machine-readable [route map](route-map.json) is checked against generated Django API operations by the test suite. Public HTML/media views and health probes are exercised separately.
