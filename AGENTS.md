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
| Docs | `README.md`, `docs/API_MIGRATION.md`, `docs/openapi.yaml` |

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
- Device check-in: `X-Device-Key` == `ATTENDANCE_DEVICE_KEY` on
  `POST /api/v1/internal/attendance/check-in/`.
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

## Testing and quality

- `make test`, `make check`, `make lint`, `make schema` as appropriate.
- Prefer pytest coverage for new services; mock external SMS/SSLCommerz/bridge HTTP.
- Keep OpenAPI and `docs/API_MIGRATION.md` current when routes change.

## Keeping this file current

Update this document when run model, clients, or ZKTeco contracts change.
