# Operations

Costs, gym hours/holidays, and admin activity log.

- **OpenAPI:** `/openapi/v1/operations.yaml`
- **Auth:** Bearer staff with matching feature permissions

## Routes

- Costs: `/api/v1/admin/costs/` (+ archive action)
- Gym hours: `GET /api/v1/admin/gym-hours/`, `PUT …/week/`, holidays CRUD
- Activity: `GET /api/v1/admin/activity/` with filters `q`, `area`, `action`, `from`, `to`, cursor
