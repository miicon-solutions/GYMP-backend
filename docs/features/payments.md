# Payments

SSLCommerz checkout sessions, IPN webhook, member cash requests, and receipts.

- **OpenAPI:** `/openapi/v1/payments.yaml`
- **Auth:** Bearer member for sessions/cash/receipts; IPN is unauthenticated provider callback

## Admission & re-admission

Pricing snapshots charge an admission fee when `requires_admission_fee` is true:

1. **Never paid** (registration / profile complete only) → first purchase / first payment includes admission (unless a live offer waives it).
2. **Active renew or plan change** → no admission.
3. **Expired within 180 days** of payment-backed `expires_on` → no admission on renew / change plan.
4. **Expired ≥ 180 calendar days** after that `expires_on` → re-admission on the next pay.

Membership validity and `expires_on` are written only when payment succeeds (admin cash confirm / cash-request accept, or online IPN settle). That same activation replaces a temporary `PFT-####` member id with `PF-####`. Renewals and plan changes leave an existing paid id unchanged. The 180-day grace starts at that payment-backed expiry — never at registration, OTP, or profile-complete.

- Online kinds stay `first_purchase` | `renew` | `change_plan`; cash kinds stay `first_payment` | `renewal` | `plan_change`.
- `is_first_payment=True` only for the member’s first ever paid payment (true join). Re-admission after lapse keeps `is_first_payment=False` so first-N offer seats are not burned; admission reports still count charged/waived admission via line items / `admission_waived_taka`.
- Live special-offer `waive_admission` applies whenever admission would be charged and seats remain (including re-admission).
- Session and cash-request APIs expose `admission_waived` from the frozen `pricing_snapshot` so the payment-success UI can congratulate waived admission after settle/accept.

Constant: `READMISSION_LAPSE_DAYS = 180` in `payments/services.py`.

## Online checkout flow

1. `POST /api/v1/member/payments/sessions/` with `kind`, `plan_id`, optional `checkout`
2. Redirect to `gateway_url` (hosted) or use SDK with server `tran_id`
3. Poll `GET …/sessions/{tran_id}/` or `POST …/confirm/`
4. IPN: `POST /api/v1/webhooks/sslcommerz/ipn/` (server-side); browser return pages never activate alone

### Sample — create session

```http
POST /api/v1/member/payments/sessions/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "kind": "first_purchase",
  "plan_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "checkout": "hosted"
}
```

## Cash request (member)

1. `POST /api/v1/member/payments/cash-requests/` `{ "plan_id" }`
2. Poll `GET …/cash-requests/{id}/`
3. Cancel while pending: `POST …/cancel/`
4. Staff accept/reject under `admin-members`

Kind is server-inferred from the member + `plan_id` via `cash_details`:
`first_payment` (never paid) | `renewal` (same plan) | `plan_change` (different plan).

- **First payment:** sets `membership_status=pending_payment`; cancels prior pending cash + pending `first_purchase` online sessions. Cancel/reject returns unpaid members to `none`.
- **Renewal / plan change:** requires a prior paid payment and status `active` or `expired`; does **not** change membership status on create; cancels prior pending cash + pending `renew` / `change_plan` online sessions. Cancel/reject leave `active`/`expired` alone.

## Receipts

`GET /api/v1/member/payments/{id}/receipt/` returns a private URL; HTML variant available. Requires member Bearer.
