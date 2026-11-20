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
