# Public

Unauthenticated welcome and other public API helpers under `/api/v1/`.

- **OpenAPI:** `/openapi/v1/public.yaml`
- **Auth:** none

### Sample — welcome

```http
GET /api/v1/welcome/
```

```json
{
  "app_name": "GYMA",
  "environment": "local",
  "message": "Welcome to GYMA."
}
```

Health probes (`/health/`, `/health/live/`) are outside the versioned OpenAPI surface.
