# Notifications

Member in-app notification feed, FCM device registration, and staff announcements.

- **OpenAPI:** `/openapi/v1/notifications.yaml`
- **Base paths:** `/api/v1/member/notifications/`, `/api/v1/member/devices/fcm/`, `/api/v1/admin/notifications/`
- **Auth:** Member Bearer for feed/devices; staff with `notifications.create` for announcements

## Member feed

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/member/notifications/` | Latest 100; newest first |
| `POST` | `/api/v1/member/notifications/{id}/read/` | Mark one read |
| `POST` | `/api/v1/member/notifications/read-all/` | Mark all read |

Resource fields: `id`, `kind` (`membership` \| `payment` \| `attendance` \| `general`), `code`, `title_key` / `body_key` (+ params), optional free-text `title` / `body`, `is_unread`, `created_at`.

`GET /api/v1/member/dashboard/` → `has_unread_notifications` reflects unread rows.

## FCM devices

| Method | Path | Body |
|---|---|---|
| `POST` | `/api/v1/member/devices/fcm/` | `{ token, platform: ios\|android }` |
| `DELETE` | `/api/v1/member/devices/fcm/` | `{ token }` |

Push uses the same Firebase project as Google auth (`FIREBASE_CREDENTIALS_FILE`). Invalid tokens are dropped on send.

## Auto catalog

| Code | Trigger | Push |
|---|---|---|
| `payment_received` | Online settle / cash accept / receive cash | yes |
| `membership_activated` | First payment only | no |
| `cash_request_rejected` | Staff rejects cash request | yes |
| `fingerprint_ready` | Enroll/pull or manual status → ready | yes |
| `membership_expiring` | Cron 7d and 1d before expiry | yes |
| `membership_expired` | Cron day after expiry | yes |

Run expiry batch: `python manage.py notify_membership_expiry` (daily cron, Asia/Dhaka).

## Admin announcement

`POST /api/v1/admin/notifications/` with `{ scope: member|active, member_id?, title, body, send_push }` requires `notifications.create`.

## Django operator console (manual test)

**Notifications → Member notifications → Add** (defaults to announcement + send push):

1. Pick the member **User** (search phone).
2. Set free-text **title** / **body**.
3. Leave **Send push** checked to deliver FCM after save (needs a **Member device tokens** row).
4. Save → in-app feed updates; admin shows success/warning about FCM.

List action **Send FCM now** re-delivers push for selected rows.
