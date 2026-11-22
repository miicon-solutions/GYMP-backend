# AGENTS.md

Instructions for AI coding agents working on **GYMP-backend** (Pure Fitness Django API).

You are a senior Django / DRF engineer. The checked-out project is the source of
truth. Implement features completely and verify them. Do not invent alternate
product flows that diverge from the Go-era architecture already ported here.

## Project profile

| Setting | Value |
|---|---|
| Project | GYMP-backend |
| Stack | Python 3.14, Django 5.2 LTS, DRF, PostgreSQL |
| HTTP | `:8080` (local compose / runserver) |
| Contract | `/api/v1/…` trailing slashes, snake_case |
| Docs | `/docs/` (Scalar), `/openapi/v1.yaml`, `docs/features/`, `docs/API_MIGRATION.md` |

## First: understand this project

1. Read `README.md`, `pyproject.toml`, `config/settings.py`, `config/urls.py`.
2. Inspect `.env` / `.env.example` — never commit or print real secrets.
3. Follow existing apps: `accounts`, `members`, `plans`, `payments`, `operations`,
   `attendance`, `reporting`, `core` (+ `biometrics` when present).
4. Match the nearest feature’s serializers → services → URL `endpoint()` style.
5. Check the Git diff before editing; preserve unrelated user changes.

## Architecture contract

```text
config/           # settings, urls, wsgi
accounts|members|plans|payments|operations|attendance|reporting|biometrics/
  models.py
  serializers.py  # validate input/output
  services.py     # business logic + DB
  …views / urls via config/urls.py endpoint() helpers
core/             # shared API helpers, middleware, permissions
```

- Serializers validate; **services own business logic**; URL handlers enforce auth.
- Do not add Celery/Redis unless requested.
- Do not redesign OTP, SSLCommerz, cash receive, membership activation, or
  attendance check-in sequences. Path/field naming follows `docs/API_MIGRATION.md`
  only.

## Clients

| Client | Role |
|---|---|
| **GYMP-mobile** (Flutter) | Member app → this API |
| **GYMP-web** (Next.js) | Public site + **staff/admin UI** (to implement/maintain there — not Flutter admin web) |
| **zkteco-bridge** (Django, standalone) | LAN device + **control-center portal** only |

## Standalone run model

- This repo’s Docker Compose is **api-only**. It does **not** start Postgres or
  the ZKTeco bridge.
- `DATABASE_URL` points at **Postgres already running in Docker** (dedicated DB
  `gyma_django` — never the legacy Go database).
- From the API container use `host.docker.internal`; from host Python use
  `localhost` and the published Postgres port.
- `ZKTECO_BRIDGE_URL` / `ZKTECO_BRIDGE_KEY` are optional. Empty = full product
  except hardware enroll/sync. Health must not call the bridge.
- Start bridge separately: sibling `zkteco-bridge/` `docker compose up` on the
  gym LAN.

## Auth and providers

- Members: phone OTP (sms.net.bd) or Firebase Google; Bearer HS256 access JWT +
  opaque refresh rotation.
- Staff: TOTP MFA; browser operator console uses Django sessions when provisioned
  and allows CRUD on registered models (secrets stay off forms).
- **Local/dev seed super (Go parity):** `seed_dev` ensures
  `+8801700000000` / `SADM-7400` (`role=admin`, `is_superuser`, MFA unenrolled +
  one-time setup token printed). Browser `/admin/` login:
  `gym-pm` / `GYM-PM-7400` (`is_staff`). `resolve-phone` → `kind: staff`; member
  OTP → 409. Reclaims that phone if it was OTP-onboarded as a bare member. Local
  Compose runs `seed_dev` after migrate. **Production:** no fixed seed — use
  `bootstrap_admin --phone …` only.
- **Staff feature permissions:** `StaffProfile.permissions` is a list of
  `feature.action` codes (`accounts/staff_permissions.py`). Super
  (`is_superuser` / `SADM-7400`) always has the full catalog. Non-super staff
  need an explicit grant; empty list → no admin feature APIs. Staff identity
  mutations (create/update/delete/activate/MFA enroll) stay **SuperOnly**.
  Unlock/refresh `staff.permissions` returns effective grants. Catalog:
  `GET /api/v1/admin/staff/permissions/catalog/`.
  `notifications` actions: `view`, `create`, `update`, `delete` (announcement
  campaigns under `/api/v1/admin/notifications/`; resend-push uses `create`).
  `cash_requests` actions: `view` (inbox + FCM for new cash requests; list
  pending), `update` (accept / reject).
- **Notifications / FCM / SMS:** member **and** staff feed + device tokens
  (`GET/POST …/member/notifications/`, `POST/DELETE …/member/devices/fcm/`)
  + staff announcement campaigns — see `docs/features/notifications.md` and
  `/openapi/v1/notifications.yaml`. `StaffAnnouncement` fans out
  `MemberNotification` rows (`code=announcement`, `related_object_id=campaign`).
  Channels: in-app always; optional FCM (`send_push`, default on for
  campaigns); optional SMS (`send_sms`, default **off** for campaigns;
  `POST …/resend-sms/`). Critical system codes also SMS by catalog:
  `payment_received`, `cash_request_rejected`, `membership_expiring`,
  `membership_expired` (not `fingerprint_ready` / `membership_activated`).
  Cash request create notifies staff with `cash_requests.view`
  (`notify_staff_cash_request`: inbox `code=cash_request` + FCM). Accept /
  reject / cancel marks those staff rows read. Member opt-out:
  `push_enabled` / `sms_enabled` on `MemberProfile`. SMS via
  `accounts.providers.send_sms_message` (sms.net.bd; needs
  `SMS_NET_BD_API_KEY`). OTP uses `send_sms` only — `OTP_DEV_BYPASS` skips
  OTP texts, never notification/announcement SMS. System SMS bodies are fixed
  English plain text. FCM uses `FIREBASE_CREDENTIALS_FILE` (same project as
  Google auth). Android payloads set
  `AndroidNotification.channel_id=pure_fitness_push` (must match the mobile
  app channel). iOS needs an APNs auth key on the Firebase iOS app whose
  bundle id matches the shipping app. Invalid/unregistered tokens are
  dropped on send; APNs/project misconfig must not delete tokens.
- Device check-in: `X-Device-Key` == `ATTENDANCE_DEVICE_KEY` on
  `POST /api/v1/internal/attendance/check-in/`.
- Remote bridge + local API: bridge push uses its own `API_BASE_URL` (often
  production). Set `ZKTECO_BRIDGE_URL` and leave `ATTENDANCE_BRIDGE_PULL=true`
  (default when URL is set) so this API polls
  `GET {bridge}/internal/attendance/` and ingests punches. One-shot:
  `manage.py pull_bridge_attendance`.
- SSLCommerz: session → gateway → IPN/confirm; return pages never activate alone;
  IPN idempotent. Same architectural flow as the Go API.
- Member cash request (first purchase): `POST /api/v1/member/payments/cash-requests/`
  freezes price + sets `pending_payment`; poll `GET …/cash-requests/{id}/`; cancel
  while pending. Staff `GET /api/v1/admin/cash-requests/`, per-member list, then
  accept (cash payment + activate, frozen amount) or reject. Legacy
  `POST …/cash-payments/` auto-accepts a matching pending request.
- Local: `OTP_DEV_BYPASS` / master code only outside `APP_ENV=prod`.

## ZKTeco / biometrics

- Vault (encrypted templates, devices, sync state) lives in **this** database.
- Admin APIs may call the standalone bridge when configured; otherwise return a
  clear unavailable response — never fail process startup.
- Device user id on the scanner = display `member_id` (`PF-…`) **or** staff
  `short_id` (`ADM-…` / seed `SADM-7400`; ≤ device PIN width, often 9). After the `PG-` → `PF-` rename migration,
  re-push vault templates to devices if fingers were enrolled under the old
  display ids.
- Control-center HTML UI lives only on `zkteco-bridge`, not here.
- Interactive enroll (`POST …/members|staff/{id}/fingerprint/enroll/` with
  `finger_id`) blocks on the bridge (~120s client timeout) while the person
  presses the scanner, then pulls templates into the vault and sets
  `fingerprint_status=ready`.
- List/delete vault fingers:
  `GET/DELETE …/fingerprint/templates/` (+ `{finger_id}/` for delete). Delete
  removes the slot on the device via bridge, then the vault row; empty vault
  returns status to `pending` (unless `not_required`).
- Staff vault: `StaffBiometricTemplate` + `StaffProfile.fingerprint_status`
  (default `pending`). Staff attendance punches land in `StaffCheckIn` /
  `StaffCheckInPunch` via the same internal check-in route (wire field still
  `member_id`; dual-resolves staff `short_id` first).
- Device controllers (super-only): `StaffProfile.device_admin` +
  `GET/POST/DELETE …/admin/device/controllers/`. Controllers are ensured on the
  bridge with ZK `USER_ADMIN` (14) so they can open the scanner settings menu;
  members and non-controller staff stay `USER_DEFAULT` (0).
- Device reachability: `GET …/admin/device/status/` (any authenticated staff).
  `online` is true only when the bridge can probe the scanner. Fingerprint
  enroll/delete and device-controller add call `require_device_online` and
  return **503** when the scanner is unreachable — admin UIs should disable
  those actions after a status probe rather than letting staff start a wait.

## API docs (humans + AI agents)

| Ref | Use |
|---|---|
| `/docs/` or `/docs/v1/` | Feature-wise Swagger UI (tags = menu) + feature pack links |
| `/openapi/v1.yaml` | Full v1 OpenAPI (also `/openapi.yaml`) |
| `/openapi/v1/{feature}.yaml` | One feature only (e.g. `auth`, `payments`) |
| `/docs/features/` | Feature pack index (`?format=json` for machines) |
| `/docs/features/{feature}/` | Narrative + samples (`?format=md` for raw markdown) |
| `docs/openapi/v1.yaml` | Committed schema (from `make schema`) |
| `docs/features/*.md` + `index.json` | Offline/agent packs |

**Agent contract:** giving `/openapi/v1/auth.yaml` or `/docs/features/auth/` is enough to
wire the whole auth surface. Giving one `operationId` plus `/openapi/v1.yaml` is
enough for a single endpoint. Published schema includes only `/api/v1/` paths.

Feature tags: `auth`, `member`, `admin-members`, `plans`, `payments`,
`attendance`, `device`, `staff`, `operations`, `reports`, `fitness`, `music`,
`notifications`, `public`. Assign tags via `endpoint(..., tags=[...])` or path
rules in `core/api_docs.py`.

### When adding or changing an API

1. Set the correct feature `tags` (and `examples` for high-traffic flows) on the
   view / `endpoint()`.
2. Run `make schema` (writes `docs/openapi/v1.yaml` + `docs/features/index.json`).
3. Update `docs/features/{feature}.md` samples/flow if behavior changed.
4. Add a new `docs/features/{feature}.md` entry when introducing a **new** feature
   tag (also extend `FEATURE_TAGS` in `core/api_docs.py`).
5. Keep `docs/API_MIGRATION.md` for Go→Django history only; do not grow it for
   new product work.

`make check` runs `build_api_docs --check` so stale schema/index fails CI-style
checks.

## Testing and quality

- `make test`, `make check`, `make lint`, `make schema` as appropriate.
- Prefer pytest coverage for new services; mock external SMS/SSLCommerz/bridge HTTP.
- Keep OpenAPI, feature packs, and (when relevant) `docs/API_MIGRATION.md` current.

## Keeping this file current

Update this document when run model, clients, ZKTeco contracts, notifications/FCM
contracts, **docs URL layout**, **API version** (`v2+`), or **feature tag
taxonomy** change.
