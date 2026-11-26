# Notifications

Member in-app notification feed, FCM device registration, SMS delivery (critical system + optional announcements), and staff announcement campaigns.

- **OpenAPI:** `/openapi/v1/notifications.yaml`
- **Base paths:** `/api/v1/member/notifications/`, `/api/v1/member/devices/fcm/`, `/api/v1/admin/notifications/`
- **Auth:** Member or staff Bearer for FCM devices **and** the in-app feed; staff with `notifications.*` for announcement campaigns; staff with `cash_requests.view` receive cash-request inbox + FCM; staff with `music.view` receive FloorCue request inbox + FCM

## Member / staff feed

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/member/notifications/` | Latest 100; newest first (member **or** staff Bearer) |
| `POST` | `/api/v1/member/notifications/{id}/read/` | Mark one read |
| `POST` | `/api/v1/member/notifications/read-all/` | Mark all read |

Resource fields: `id`, `kind` (`membership` \| `payment` \| `attendance` \| `general`), `code`, `title_key` / `body_key` (+ params), optional free-text `title` / `body`, `is_unread`, `created_at`, `related_object_id`.

`GET /api/v1/member/dashboard/` → `has_unread_notifications` reflects unread rows (members). Staff unread is derived from the same feed list.

## FCM devices

| Method | Path | Body |
|---|---|---|
| `POST` | `/api/v1/member/devices/fcm/` | `{ token, platform: ios\|android }` |
| `DELETE` | `/api/v1/member/devices/fcm/` | `{ token }` |

Members **and staff** register on this path (same Firebase project). Staff tokens receive operational pushes (e.g. new cash payment request). Invalid / unregistered tokens are dropped on send; APNs credential or sender-id misconfig must **not** delete tokens. iOS requires an APNs auth key on the matching Firebase iOS app bundle id. Android FCM uses channel `pure_fitness_push` (high importance); the mobile app creates that channel and shows local notifications while foregrounded.

System FCM title/body are fixed **Bangla** plain text (tray copy; no member locale on the API). System SMS is always **English**. In-app feed still stores ARB `title_key` / `body_key` for client localization. Announcement pushes use staff free-text as-is.

Member opt-out: `MemberProfile.push_enabled` (default true). SMS opt-out: `MemberProfile.sms_enabled` (default true).

**Staff cash-request notify:** when a member creates `POST …/cash-requests/`, after commit the API creates a `MemberNotification` (`code=cash_request`, kind `payment`) for each active staff with `cash_requests.view` (super included) and FCM-pushes those users’ registered devices (`type=cash_request`, `member_id`, `cash_request_id`, `amount_taka`). Tap opens admin member detail. Accept / reject / cancel marks matching staff inbox rows (`related_object_id` = request id) as read. A later re-request creates a new unread row.

**Staff FloorCue music-request notify:** when a member `POST …/music/queue/` lands in `pending_approval`, after commit the API creates a `MemberNotification` (`code=music_request`, kind `general`) for each active staff with `music.view` and FCM-pushes (`type=music_request`, `music_queue_item_id` — **no** `member_id` in FCM data so taps open FloorCue, not member detail). Staff approve (`POST …/approve/`) or reject pending (`DELETE …/queue/{id}/`) marks those staff rows read and notifies the requesting member (`music_request_approved` / `music_request_rejected`, push only). Member self-withdraw of a pending item marks staff rows read without a member push. Auto-queue when `require_approval=false` (or staff add) does not fan out.

## SMS delivery

Uses sms.net.bd (`SMS_NET_BD_API_KEY`, optional `SMS_NET_BD_SENDER_ID`) via `accounts.providers.send_sms_message`. **Requires a real API key** — without it, notification SMS is skipped (`sms_unconfigured`) and logged; in-app/push still work. OTP auth uses the OTP-only `send_sms` wrapper (which honors `OTP_DEV_BYPASS`); notification SMS never uses that bypass.

System SMS bodies are fixed **English** plain text (no member locale on the API). Announcement SMS uses staff free-text (`"{title}: {body}"`). SMS failures are non-fatal for notifications (in-app row remains; stats count `sms_failed`).

## Auto catalog

| Code | Trigger | Push | SMS |
|---|---|---|---|
| `payment_received` | Online settle / cash accept / receive cash | yes | **yes** |
| `membership_activated` | First payment only | no | no |
| `cash_request_rejected` | Staff rejects cash request | yes | **yes** |
| `music_request` | Member song → `pending_approval` (staff inbox) | yes | no |
| `music_request_approved` | Staff approves pending FloorCue song | yes | no |
| `music_request_rejected` | Staff rejects pending FloorCue song | yes | no |
| `fingerprint_ready` | Enroll/pull or manual status → ready | yes | no |
| `membership_expiring` | Cron 7d and 1d before expiry | yes | **yes** |
| `membership_expired` | Cron when past `expires_on` (flip + catch-up) | yes | **yes** |

### Membership expiry cron (host, Asia/Dhaka)

No in-process scheduler. Ops must run the daily chain on the host (or
equivalent):

```bash
make cron-expiry
# same as: make notify-expiry && make reconcile-access
# or: python manage.py notify_membership_expiry
#     python manage.py reconcile_device_access
```

Example crontab (~06:00 Asia/Dhaka wall clock; set `CRON_TZ` or run on a
Dhaka-local host):

```cron
CRON_TZ=Asia/Dhaka
0 6 * * * cd /path/to/GYMP-backend && make cron-expiry >> /var/log/gymp-expiry.log 2>&1
```

`notify_membership_expiry` creates 7d/1d `membership_expiring` rows, flips
**all** still-`active` members with `expires_on < today` to `expired`, creates
`membership_expired`, and enqueues scanner `revoke_access` (soft-delete; vault
kept). Then `reconcile_device_access` repairs drift (failed jobs, past-due lag,
missing restores).

**Push delivery deps:** `FIREBASE_CREDENTIALS_JSON` or `FIREBASE_CREDENTIALS_FILE`,
registered FCM device tokens, and member `push_enabled` (SMS also needs
`SMS_NET_BD_API_KEY` + `sms_enabled`).

## Admin ops alerts (cron)

Super-only settings: selected staff recipients + toggles for near-live enrollment and end-of-day digest. Cash-request fan-out stays on `cash_requests.view` and is independent.

| Method | Path | Permission |
|---|---|---|
| `GET` | `/api/v1/admin/ops-alerts/settings/` | `SuperOnly` |
| `PUT` | `/api/v1/admin/ops-alerts/settings/` | `SuperOnly` |

PUT body: `{ enrollment_live_enabled?, daily_digest_enabled?, recipient_ids: uuid[] }` (full replace of recipient set when `recipient_ids` is sent).

| Code | Command | Cron |
|---|---|---|
| `admin_enrollment` | `python manage.py notify_admin_enrollments` | every 5–15 min Asia/Dhaka (recommended `*/10`) |
| `admin_daily_enrollments` | `python manage.py notify_admin_daily_enrollments --timezone Asia/Dhaka` | ~23:55 Asia/Dhaka |
| `admin_daily_enrollments` | `python manage.py notify_admin_daily_enrollments --timezone Europe/London` | ~23:55 Europe/London |

Or run both digests in one shot: `python manage.py notify_admin_daily_enrollments` / `--all` (uses “today” in each zone).

Both create staff inbox rows + FCM (no SMS). First-payment enrollments only. Poll is idempotent per payment id; digest is idempotent per `timezone:YYYY-MM-DD` (Dhaka and London digests both deliver).

## Admin announcement campaigns

`StaffAnnouncement` is the staff-facing campaign. Create fans out one `MemberNotification` (`code=announcement`) per recipient with `related_object_id = campaign id`.

| Method | Path | Permission |
|---|---|---|
| `GET` | `/api/v1/admin/notifications/` | `notifications.view` |
| `POST` | `/api/v1/admin/notifications/` | `notifications.create` |
| `GET` | `/api/v1/admin/notifications/{id}/` | `notifications.view` |
| `PATCH` | `/api/v1/admin/notifications/{id}/` | `notifications.update` |
| `DELETE` | `/api/v1/admin/notifications/{id}/` | `notifications.delete` |
| `POST` | `/api/v1/admin/notifications/{id}/resend-push/` | `notifications.create` |
| `POST` | `/api/v1/admin/notifications/{id}/resend-sms/` | `notifications.create` |

Create body: `{ scope: member\|active, member_id?, title, body, send_push, send_sms }`.  
`send_push` defaults **true**; `send_sms` defaults **false**.

PATCH body: `{ title?, body? }` — updates campaign and all linked member rows; does **not** resend push or SMS.

Delete removes the campaign and all linked fan-out rows.

Create / resend-push responses include `push_sent`, `push_failed`, `push_skipped_no_device`, `push_skipped_disabled`.  
Create / resend-sms responses include `sms_sent`, `sms_failed`, `sms_skipped_disabled`, `sms_skipped_no_phone`.

## Django operator console (manual test)

**Notifications → Member notifications → Add** (defaults to announcement + send push):

1. Pick the member **User** (search phone).
2. Set free-text **title** / **body**.
3. Leave **Send push** checked to deliver FCM after save (needs a **Member device tokens** row).
4. Optionally check **Send sms** to deliver via sms.net.bd.
5. Save → in-app feed updates; admin shows success/warning about FCM/SMS.

List actions **Send FCM now** / **Send SMS now** re-deliver for selected rows.
