# Plans

Public plan catalog plus admin plan/offer CRUD. Member-facing plan list/detail also land here.

- **OpenAPI:** `/openapi/v1/plans.yaml`
- **Paths:** `/api/v1/public/plans/`, `/api/v1/member/plans/`, `/api/v1/admin/plans/`
- **Auth:** public list is open; member/admin require Bearer

### Sample — public list

```http
GET /api/v1/public/plans/
```

Admin writes use `name`, `monthly_rate_taka`, `admission_fee_taka`, `duration_months`, discount fields, `is_active`. Offers attach under `/admin/plans/{id}/offers/`.

### Special offers (first-N admission waiver)

Offers are date-bounded on a base plan (`starts_on`/`ends_on` inclusive, Asia/Dhaka). Active date ranges on one plan cannot overlap.

Writable fields: `name`, `starts_on`, `ends_on`, `waive_admission`, `extra_discount_type`, `extra_discount_value`, `max_redemptions` (null = unlimited), `limit_scope` (`offer` | `plan` | `gym`, default `offer`), `is_active`.

Computed on read (list/detail/`active_offer`): `redeemed_count`, `remaining`, `admission_waived`.

- Admission waiver applies only while `waive_admission` is true **and** seats remain (`remaining` is null or &gt; 0).
- Extra period discount still applies when seats are exhausted.
- Seat counts use **paid** first payments only (pending sessions/cash requests do not reserve).
- `limit_scope=offer`: payments that redeemed this offer (linked when admission was waived).
- `limit_scope=plan`: paid first payments on this plan with `paid_at` on/after `starts_on`.
- `limit_scope=gym`: all paid first payments gym-wide with `paid_at` on/after `starts_on`.
- Checkout freezes amounts in `pricing_snapshot` (includes `offer_id`, `admission_waived`); settlement honors the freeze even if seats later exhaust.

### Sample — create limited offer

```http
POST /api/v1/admin/plans/{plan_id}/offers/
Content-Type: application/json

{
  "name": "Opening — free admission",
  "starts_on": "2026-11-01",
  "ends_on": "2026-12-31",
  "waive_admission": true,
  "max_redemptions": 50,
  "limit_scope": "gym"
}
```
