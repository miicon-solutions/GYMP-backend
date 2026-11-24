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

## Membership expiry ↔ scanner access

**Fingerprint matching is on the ZKTeco device** (local templates). GYMP is the
**source of truth for who may exist on the panel** (membership + vault). The
device is a synced cache: expire removes the user; renew re-pushes vault
templates.

pyzk has **no per-user disable** (only whole-device `disable_device`). Blocking
physical access therefore requires **soft-delete** (`delete_user`) on the
scanner. Vault rows stay encrypted in GYMP for restore.

| Event | Action |
| --- | --- |
| Daily `notify_membership_expiry` | Flip **any** `active` with `expires_on < today` → `expired`, enqueue `revoke_access` |
| Payment `activate(...)` | Enqueue `push_user` from vault when templates exist / status `ready` |
| `python manage.py reconcile_device_access` | Catch-up flip past-due; revoke `expired` (vault or `ready`); restore `active`+`ready` missing sync |

Ops (Asia/Dhaka cron): run `notify_membership_expiry`, then `reconcile_device_access`.

Bridge worker handles `revoke_access` → `DeviceClient.soft_delete_by_user_id`.
Staff / device-controller pins are never revoked by membership expiry.
