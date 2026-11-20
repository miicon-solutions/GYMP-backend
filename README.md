# GYMA Django backend

Python 3.14, Django 5.2 LTS, Django REST Framework, and PostgreSQL. This is a complete, independently runnable port of the implemented Go backend. It uses a **new database** and a **breaking API contract**. The Go project is unchanged; the Flutter client in `GYMA_a` targets this Django API.

## Start with Docker (standalone API)

Compose starts **only the API**. Postgres and the ZKTeco bridge are separate.

1. Ensure Postgres is already running in Docker and create a dedicated empty DB:

```bash
psql "$DATABASE_URL_ADMIN" -c 'CREATE DATABASE gyma_django;'
```

2. Run the API:

```bash
cp .env.example .env
# Edit .env: DATABASE_URL → your existing Postgres (host.docker.internal from compose,
# localhost from host Python). Use DB name gyma_django — never the legacy Go database.
# Generate TOTP_ENCRYPTION_KEY: python -c 'import secrets; print(secrets.token_hex(32))'
# Local media: MEDIA_STORAGE=filesystem. Leave ZKTECO_BRIDGE_URL empty unless the
# standalone zkteco-bridge is running on the gym LAN.
docker compose up --build -d
# Local Compose already runs seed_dev after migrate (plans + Go-parity seed super).
# Capture the printed MFA setup token from api logs on first boot.
# Production/staging: bootstrap explicitly (no fixed seed phone):
docker compose exec api python manage.py bootstrap_admin --phone +88017XXXXXXXX --name 'Gym Operator' --browser-access
```

Agent notes: see [AGENTS.md](AGENTS.md). ZK control center lives in sibling `zkteco-bridge/` (own `docker compose up`).

**Local/dev seed super (Go parity):** `seed_dev` ensures phone `+8801700000000` (`01700000000`), short id `SADM-7400`, starts MFA-unenrolled, and prints a one-time setup token. Browser operator console at `/admin/` uses username `gym-pm` / password `GYM-PM-7400`. `POST /api/v1/auth/resolve-phone/` returns `kind: staff` for that number; member onboarding OTP is rejected (409). If that phone was accidentally OTP-onboarded as a member (no payment/attendance history), `seed_dev` reclaims it as the seed super.

**Production:** use `bootstrap_admin --phone …` with a real number. It prompts for an operator password only with `--browser-access`, prints a **one-time setup token**, and refuses to replace an existing super admin. Production does not use the fixed seed phone.

The API listens at `http://localhost:8080`. Open `/docs/` for the feature-wise API docs UI (Swagger tag groups; version-pinned at `/docs/v1/`), `/openapi/v1.yaml` for the full schema, `/openapi/v1/{feature}.yaml` for one feature (e.g. `auth`), `/docs/features/` for agent/human feature packs, `/docs/v1/reference/` for Scalar, `/admin/` for the operator console, `/health/` for database readiness, and `/health/live/` for liveness. Migrations run before Gunicorn starts. The initial migration installs default gym hours: Saturday–Thursday 06:00–22:00, Friday closed.

Compose runs the API; PostgreSQL and MinIO/S3 are managed separately. Create a dedicated empty PostgreSQL database for this backend and set `DATABASE_URL` to its connection URL. Do not point it at the Go database: startup runs Django migrations against the configured database. Set `HTTP_PORT` if port 8080 is already occupied. Stopping Compose leaves the external database and bucket untouched.

For PostgreSQL running in another Docker container with host port 5432 published, use `postgres://USER:PASSWORD@host.docker.internal:5432/DATABASE` from Compose. The file includes the Linux host-gateway mapping. Use your actual published port and URL-encode special characters in credentials. PostgreSQL must accept connections from the API container; a port published only on host loopback may be inaccessible through the gateway. Containers on a shared Docker network can instead use the database container's network hostname (attach the API using a local Compose override). `localhost` inside the API container refers to the API itself.

`seed_dev` adds the original monthly/quarterly/annual catalog math (rate 1500, admission 1500, standing discounts 0/500/3500) and the Go-parity seed super admin above. It is idempotent and disabled in production. Plans can also be created through the staff API. Local Compose runs `seed_dev` automatically after migrate; host Python still calls it manually after migrate.

For a populated demo, use the seed super (or a bootstrapped super), then run:

```bash
docker compose exec api python manage.py seed_demo --admin-phone +8801700000000
# Local Python alternative (after seed_dev or bootstrap_admin):
uv run python manage.py seed_demo --admin-phone +8801700000000 --members 30
```

`seed_demo` requires that existing active super admin and runs only outside production. By default it creates 30 completed member profiles (10 unpaid, 15 active, 5 expired), two staff, catalogue plans, offers on demo-created plans, synthetic cash/online payments, attendance, expenses, holidays, and activity over the preceding 90 days. It never contacts SMS, Firebase, payments, or media providers. Sample staff have no password/browser access or enrolled authenticator; generate their enrollment token through your super admin interface. Demo member phone numbers are printed for login using the configured OTP provider or local development bypass.

The command reuses existing catalogue durations without changing their settings. Repeated runs preserve existing demo records; a larger `--members` count adds members (maximum 1000). Deterministic identifiers prevent duplicates, and conflicting phone numbers abort the whole transaction without changing data. It does not delete or reset records.

The deployment entrypoint `/app/entrypoint.sh` runs migrations, collects static files, and starts Gunicorn on port `8000` for Traefik. `PORT` overrides the listen port. Explicit commands retain control of their startup steps, including the local Compose command on `8080`. Local configuration is loaded from `.env` by Django.

## Local Python development

Install Python 3.14 and `uv`, then:

```bash
uv sync --locked
# Set DATABASE_URL to your separately running PostgreSQL and configure MinIO in .env.
uv run python manage.py migrate
uv run python manage.py seed_dev
uv run python manage.py runserver 0.0.0.0:8080
```

For local Python, replace `host.docker.internal` with `localhost` in `DATABASE_URL`, using the PostgreSQL container's published port. Compose passes your configured URL through unchanged. If your rootless Docker/network setup does not expose the database to host processes, run commands through `docker compose exec api` and use the container test workflow below.

## Next.js web app

The sibling `GYMP-web` repository provides the Pure Fitness public website, English/Bangla member portal, and staff workspace. Its Next.js server connects to this backend with `BACKEND_API_URL`; database and MinIO/S3 credentials stay in Django.

`GET /api/v1/public/plans/` exposes only active catalogue plans with the same computed prices/offers and cursor pagination as the member catalogue. It needs no login and contains no member data.

Set `WEB_APP_BASE_URL` to the web origin (for example `http://localhost:3000` locally or `https://fitness.example.com` in production) to forward browser payment returns there. It accepts only a configured HTTP(S) origin, requires HTTPS in production, and never trusts a client-provided redirect destination. GET and POST gateway returns redirect without settling a payment; authenticated confirmation/IPN still validates the gateway. Leaving this variable empty preserves the existing Django return page.

## Media storage: MinIO locally, S3 in production

Uploads use Django's default storage backend. `.env.example` selects `MEDIA_STORAGE=s3`; the same backend supports MinIO and AWS S3. Create a private bucket and credentials separately. The application does not start MinIO, create buckets, or change bucket policies.

For MinIO, fill these values in `.env`:

```dotenv
MEDIA_STORAGE=s3
AWS_STORAGE_BUCKET_NAME=gyma-media
AWS_ACCESS_KEY_ID=YOUR_MINIO_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_MINIO_SECRET_KEY
AWS_S3_ENDPOINT_URL=http://YOUR_HOST_LAN_IP:9000
AWS_S3_REGION_NAME=us-east-1
AWS_S3_ADDRESSING_STYLE=path
S3_SUB_FOLDER=puregym
AWS_LOCATION=media
AWS_QUERYSTRING_EXPIRE=3600
```

Use MinIO's S3 API port (usually 9000), not its console port. The endpoint hostname/IP must resolve and be reachable from **both the backend and photo-viewing clients**: it appears in signed download URLs. A host LAN IP or shared DNS name works when both can reach it. Container-only names such as `minio` or `host.docker.internal` usually cannot be used by phones or other client machines. Do not rewrite the hostname in a signed URL; doing so invalidates its signature. Use HTTPS outside local development.

For AWS S3, leave `AWS_S3_ENDPOINT_URL` empty, set `AWS_S3_REGION_NAME` to the bucket's region, and use `AWS_S3_ADDRESSING_STYLE=virtual`. Set AWS access credentials and optionally `AWS_SESSION_TOKEN`, or leave them blank to use the deployment's IAM role/default AWS credential chain. Grant bucket listing and object read/write/delete access to the selected prefix. Keep public access blocked; no object ACL is sent.

`S3_SUB_FOLDER` selects this project's directory in a shared bucket, following the project-prefix approach used in MAP. It is combined with `AWS_LOCATION` (default `media`), so the example stores objects at `puregym/media/<filename>`. Nested project folders such as `projects/puregym` are supported; surrounding whitespace and leading/trailing slashes are removed. Dot segments, backslashes, control characters, and empty internal path segments are rejected. The configured storage applies this prefix to uploads, signed downloads, lookups, and deletions; database photo names stay relative. Static assets continue to use WhiteNoise.

Leaving `S3_SUB_FOLDER` unset or empty preserves the previous `AWS_LOCATION` paths. Keep both settings stable after uploading files: changing either does not move existing objects. If moving existing photos into a new project folder, copy/move those objects to the new prefix before switching configuration. `AWS_QUERYSTRING_EXPIRE` defaults to 3600 seconds and accepts 1–604800 seconds. The API returns a freshly signed `photo_url` when a profile is fetched. Treat it as temporary: fetch the profile again after expiry instead of persisting the URL. Upload/replacement/deletion endpoints and the 5 MB JPEG/PNG/WebP validation remain unchanged. In S3 mode, the legacy public `/media/member-photos/` route returns 404.

`MEDIA_STORAGE=filesystem` is available for tests or standalone development and uses `MEMBER_PHOTO_DIR`. Without `MEDIA_STORAGE`, filesystem storage is used so image builds and isolated checks need no storage credentials. Filesystem mode retains the public local photo route. Compose does not provide a media volume; use S3 mode for durable container uploads. S3 failures never fall back to disk. Static assets remain local and are served by WhiteNoise. Existing local files are not automatically copied to a bucket.

## API documentation

| URL / path | Purpose |
|---|---|
| `/docs/` · `/docs/v1/` | Developer UI with feature menu (auth, payments, …) |
| `/openapi/v1.yaml` | Full v1 OpenAPI (alias: `/openapi.yaml`) |
| `/openapi/v1/{feature}.yaml` | Filtered OpenAPI for one feature |
| `/docs/features/` | Feature pack index (`Accept: application/json` or `?format=json`) |
| `/docs/features/{feature}/` | Narrative + sample requests (`?format=md` for raw) |
| [docs/openapi/v1.yaml](docs/openapi/v1.yaml) | Committed schema (`make schema`) |
| [docs/features/](docs/features/) | Committed packs + `index.json` |

**Agent-friendly refs:** point an agent at `/openapi/v1/auth.yaml` or
`/docs/features/auth/` to connect the whole auth API; use a single operationId
with the full schema for one endpoint. Regenerate with `make schema` after route
changes. See [AGENTS.md](AGENTS.md) for the maintenance checklist.

## API and authentication

See [API migration reference](docs/API_MIGRATION.md) for every old/new route, payload rules, examples, and integration differences. The committed [OpenAPI schema](docs/openapi/v1.yaml) describes the new contract (also live at `/openapi/v1.yaml`).

Member login uses phone OTP or verified Google/Firebase identity. Staff login uses TOTP. API credentials are Bearer HS256 access JWTs and opaque, hashed refresh tokens with one-time rotation. No password-grant API was added. Browser operator access is granted explicitly and uses Django sessions, password validation, CSRF protection, and login throttling.

Public signup saves a member account and the existing full profile form without purchasing a membership. Web and mobile restore completed unpaid accounts to **Account registered → Awaiting payment**, where the user can edit their information, pay online, or visit reception. Staff receive cash against that same registration using a server-calculated plan price. Successful cash collection or verified online settlement activates membership and starts its expiry. Both payment paths require a completed profile. Unpaid registrations cannot check in. Members require no authenticator; staff MFA remains required.

Example local OTP login:

```bash
curl -sS http://localhost:8080/api/v1/auth/otp/send/ \
  -H 'Content-Type: application/json' \
  -d '{"phone_e164":"+8801712345678","purpose":"onboarding"}'
# Use otp_session_id from the response:
curl -sS http://localhost:8080/api/v1/auth/otp/verify/ \
  -H 'Content-Type: application/json' \
  -d '{"otp_session_id":"REPLACE_WITH_SESSION_ID","code":"000000"}'
```

With the bootstrap setup token, call `/api/v1/auth/admin/mfa/setup/` with `phone_e164` and `setup_token`, pair the returned `otpauth_uri`, then call `/api/v1/auth/admin/mfa/confirm/` with those fields plus `totp_code`. Confirmation returns staff tokens and consumes the setup token. Subsequent login uses `/api/v1/auth/admin/unlock/` with phone and the current authenticator code. A TOTP step cannot be reused; wait for the next code after confirming enrollment.

## Providers and production configuration

The local default `OTP_DEV_BYPASS=true` avoids sending SMS and accepts `000000`; `EMAIL_DEV_BYPASS=true` returns a clearly identified development result. Both are forcibly disabled with `APP_ENV=prod`. Local Google and online-payment routes still require real provider configuration; they do not fabricate provider success.

- **Firebase:** set `FIREBASE_CREDENTIALS_FILE` to a readable service-account JSON file. In Docker, mount it read-only at that container path using a local Compose override. Only verified Google-provider ID tokens are accepted, with revocation checking.
- **SMS:** set `SMS_NET_BD_API_KEY` and optionally `SMS_NET_BD_SENDER_ID`. Requests use sms.net.bd's form API with a 10-second timeout.
- **SSLCommerz:** set store ID/password and `PUBLIC_BASE_URL`. Sandbox is enabled outside production by default. Register `{PUBLIC_BASE_URL}/api/v1/webhooks/sslcommerz/ipn/` with the provider. Both hosted checkout and Flutter SDK checkout (`checkout: "sdk"`) are supported. Credentials stay on the server.
- **Attendance:** set a private `ATTENDANCE_DEVICE_KEY`; device requests send it in `X-Device-Key`.
- **Encryption:** keep `TOTP_ENCRYPTION_KEY` private and stable. It accepts 32 raw bytes, 64 hex characters, or base64 encoding of 32 bytes. Losing/changing it prevents decrypting existing authenticator seeds.
- **Deployment:** set `APP_ENV=prod`, private Django/JWT keys, `ALLOWED_HOSTS`, HTTPS `PUBLIC_BASE_URL`, explicit CORS origins, and `CSRF_TRUSTED_ORIGINS`. Production rejects the shipped example signing keys, requires provider/device settings, disables bypasses/sandbox, and enables secure cookies, HTTPS redirects, and HSTS. Configure external `DATABASE_URL` and `MEDIA_STORAGE=s3` with the AWS bucket settings above; back up the database and bucket separately.
- **Reverse proxy:** set `TRUSTED_PROXY_IPS` to the exact addresses of your proxies. Configure those proxies to overwrite `X-Forwarded-Proto` and append the real source address to `X-Forwarded-For`. Forwarded headers from other addresses are ignored. This enables correct HTTPS detection, absolute pagination links, and per-client throttling behind TLS termination. Without a trusted proxy, Gunicorn must receive HTTPS-aware requests directly or `SECURE_SSL_REDIRECT` must be configured for your deployment. Readiness/liveness are exempt from HTTPS redirects for internal probes.

The operator console keeps user and financial records read-only. A browser super admin can open **Accounts → Staff profiles → a staff profile → Set up / reset MFA** to generate a private, one-time enrollment token after confirmation. This also supports recovering the initial super admin when its bootstrap token has expired. The token is shown only in the generation response, expires after `MFA_SETUP_TTL_SEC` (default 30 minutes), and is entered on the web sign-in page under **Set up your authenticator**. Resetting invalidates the previous authenticator and setup token; the operation is recorded in Django's admin history without the token. Browser operator login must have been provisioned separately (for example with `bootstrap_admin --browser-access`).

In the web staff portal, a signed-in super admin can generate the same token through **Staff → shield icon (Set up / reset MFA)**. Staff mutations otherwise use the APIs and shared services, retaining business validation and activity recording. OTP/session tables and encrypted authenticator secrets are not exposed in the console.

The recovery-email provider, notifications feed, and physical fingerprint-device protocol were incomplete in Go and remain outside the port. Recovery email returns 502 without the explicit development bypass. The dashboard retains its existing `has_unread_notifications: false` behavior.

## Verification

Run the full suite against a dedicated development/test PostgreSQL database. Its user must be allowed to create the isolated Django test database. The Compose test service uses your `DATABASE_URL` and filesystem storage; it never contacts MinIO/S3:

```bash
docker compose --profile test build test
docker compose --profile test run --rm test
```

For host-based development against a reachable PostgreSQL instance:

```bash
make check
make lint
make test
make schema
```

Tests use an isolated PostgreSQL test database, fake provider boundaries, and temporary media storage. They cover API workflows, authorization, schema/route inventory, constraints, rollback, parallel OTP/refresh/payment/check-in operations, date boundaries, upload limits, provider failures, and production/storage configuration. S3 signing uses dummy credentials without network requests; object lifecycle tests use a storage fake without filesystem paths. Tests do not contact Firebase, SMS, SSLCommerz, or live object storage.

## Organization

Django apps separate accounts, members, plans, payments, operations, attendance, and reporting. Serializers validate transport inputs; services own business operations and transactions; views enforce endpoint permissions and delegate to services. Django migrations own the fresh schema. No Celery, Redis, scheduler, or legacy database compatibility layer is required.
