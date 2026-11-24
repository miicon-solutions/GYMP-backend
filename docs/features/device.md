# Device

Scanner reachability, device controllers, and biometric vault (admin + internal bridge).

- **OpenAPI:** `/openapi/v1/device.yaml`
- **Auth:** Bearer staff for admin device routes; `X-Device-Key` for internal bridge routes

## Networking

The LAN **zkteco-bridge** is an outbound HTTP client of this API. This server never
dials the bridge (`ZKTECO_BRIDGE_URL` is deprecated / unused for control). The
bridge heartbeats, claims device jobs, exports vault templates, and pushes
attendance punches.

## Key routes

- `GET /api/v1/admin/device/status/` — from last bridge heartbeat (`online` only when the scanner was reachable; includes `last_seen_at` / `heartbeat_age_sec`)
- `GET /api/v1/admin/device/ping/` — connection check (`bridge_connected` / `scanner_online`)
- Controllers: `GET|POST /api/v1/admin/device/controllers/`, delete by staff id
- Internal bridge: `GET …/internal/bridge/ping/`, `POST …/heartbeat/`, `GET …/jobs/`, `POST …/jobs/{id}/complete/`
- Internal vault: `GET …/vault-members/`, `POST …/vault-export/`, `POST …/vault-sync-ack/`
  (`POST …/vault-push/` still enqueues per-member `push_user` jobs)

Enroll/delete return **503** when there is no recent heartbeat or the scanner is offline — probe status first.
