# Reports

Revenue reporting for staff.

- **OpenAPI:** `/openapi/v1/reports.yaml`
- **Route:** `GET /api/v1/admin/revenue/`
- **Auth:** Bearer staff with `reports.view`

### Sample

```http
GET /api/v1/admin/revenue/?range=month&date=2026-11-01&channel=all&limit=50
Authorization: Bearer <staff_access_token>
```

Query supports `range`, `date`, `from`, `to`, `dates`, `member_id`, `channel`, `limit`.
