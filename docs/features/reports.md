# Reports

Staff revenue and operational report APIs (`reports.view`).

- **OpenAPI:** `/openapi/v1/reports.yaml`
- **Auth:** Bearer staff with `reports.view`

## Endpoints

| Method | Path | operationId |
|---|---|---|
| `GET` | `/api/v1/admin/revenue/` | `admin_revenue` |
| `GET` | `/api/v1/admin/reports/cash-vs-online/` | `admin_report_cash_vs_online` |
| `GET` | `/api/v1/admin/reports/member-collections/` | `admin_report_member_collections` |
| `GET` | `/api/v1/admin/reports/revenue-vs-expense/` | `admin_report_revenue_vs_expense` |
| `GET` | `/api/v1/admin/reports/membership-status/` | `admin_report_membership_status` |
| `GET` | `/api/v1/admin/reports/expenses-by-admin/` | `admin_report_expenses_by_admin` |
| `GET` | `/api/v1/admin/reports/admission/` | `admin_report_admission` |
| `GET` | `/api/v1/admin/reports/plan-mix/` | `admin_report_plan_mix` |

Most date-scoped reports accept `range`, `date`, `from`, `to`, and/or `dates`. Channel-aware ones also take `channel`. Membership status uses `within_days`. Revenue adds `member_id` and `limit`.

### Sample — revenue

```http
GET /api/v1/admin/revenue/?range=month&date=2026-11-01&channel=all&limit=50
Authorization: Bearer <staff_access_token>
```

### Sample — cash vs online

```http
GET /api/v1/admin/reports/cash-vs-online/?range=month&date=2026-11-01
Authorization: Bearer <staff_access_token>
```
