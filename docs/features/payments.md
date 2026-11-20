# Payments

SSLCommerz checkout sessions, IPN webhook, member cash requests, and receipts.

- **OpenAPI:** `/openapi/v1/payments.yaml`
- **Auth:** Bearer member for sessions/cash/receipts; IPN is unauthenticated provider callback

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

## Receipts

`GET /api/v1/member/payments/{id}/receipt/` returns a private URL; HTML variant available. Requires member Bearer.
