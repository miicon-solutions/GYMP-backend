# Device

Scanner reachability, device controllers, and biometric vault (admin + internal bridge).

- **OpenAPI:** `/openapi/v1/device.yaml`
- **Auth:** Bearer staff for admin device routes; `X-Device-Key` for internal vault routes

## Key routes

- `GET /api/v1/admin/device/status/` — `online` only when bridge can probe the scanner
- Controllers: `GET|POST /api/v1/admin/device/controllers/`, delete by staff id
- Internal: `GET …/internal/biometrics/vault-members/`, `POST …/vault-push/`

Enroll/delete return **503** when the scanner is unreachable — probe status first.
