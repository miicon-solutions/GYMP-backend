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
- Staff PIN rotate: `POST /api/v1/admin/me/device-pin/regenerate/`
- Admin member PIN rotate: `POST /api/v1/admin/members/{id}/device-pin/regenerate/`
  (member self-regenerate is rejected)
- Internal bridge: `GET …/internal/bridge/ping/`, `POST …/heartbeat/`, `GET …/jobs/`, `POST …/jobs/{id}/complete/`
- Internal vault: `GET …/vault-members/`, `POST …/vault-export/`, `POST …/vault-sync-ack/`
  (`POST …/vault-push/` still enqueues per-member `push_user` jobs)

Enroll/delete return **503** when there is no recent heartbeat or the scanner is offline — probe status first.

### Sample — regenerate staff device PIN

```http
POST /api/v1/admin/me/device-pin/regenerate/
Authorization: Bearer <staff_access_token>
```

```json
{
  "device_keypad_id": "3",
  "device_pin": "7691",
  "pushed": true
}
```

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

Ops (Asia/Dhaka host cron): `make cron-expiry` (runs `notify_membership_expiry`,
then `reconcile_device_access`). Example: `0 6 * * *` with `CRON_TZ=Asia/Dhaka`
— see `docs/features/notifications.md`.

Bridge worker handles `revoke_access` → `DeviceClient.soft_delete_by_user_id`.
Staff / device-controller pins are never revoked by membership expiry.

## Keypad id + device PIN (digits-only)

ZK keypads cannot type letters (and cannot start input with `0`). Device
`user_id` is therefore a dedicated **digits-only, no-leading-zeros**
`device_keypad_id` on member/staff (not display `PF-…` / `ADM-…`; `PF-0003` →
`3`, never `0003` or `0`).

**Members and staff** get a cryptographically random **4-digit** PIN
(`device_pin_enc`) for fingerprint-fail unlock. Each PIN is **single-use**: after
a password verify check-in (`verify_method` from the bridge), GYMP rotates the
PIN and re-pushes. Member credentials are **admin-only** (never in the member app).

| Concern | Behavior |
| --- | --- |
| Provision | `ensure_device_keypad_id` + `ensure_device_pin`; bridge gets `user_id=keypad`, `password=PIN` |
| Legacy migration | Soft-delete old `PF-`/`ADM-` pin and zero-padded keypad ids when pushing under the unpadded id |
| Check-in | Resolve punch id: staff keypad → member keypad → legacy short_id / member_id; bridge sends `verify_method` |
| App visibility | Member profile never includes credentials; admin member detail + staff Manage → Scanner keypad access |
| Regenerate | `POST …/admin/members/{id}/device-pin/regenerate/` and `POST …/admin/me/device-pin/regenerate/`; member self-regenerate rejected |
| Single-use | Password unlock → rotate PIN + push (fingerprint unlock leaves PIN unchanged) |

Expiry revoke deletes by `device_keypad_id` (falls back to display id only for
unmigrated rows). Soft-delete remains the only door block (no EnableUser).
