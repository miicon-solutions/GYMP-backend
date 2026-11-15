# GYMA Django backend

Python 3.14, Django 5.2 LTS, Django REST Framework, and PostgreSQL. This is a complete, independently runnable port of the implemented Go backend. It uses a **new database** and a **breaking API contract**. The Go and Flutter projects are unchanged.

## Start with Docker

Run these commands in `GYMA_b`:

```bash
cp .env.example .env
# Edit .env; generate private Django/JWT secrets and a TOTP encryption key.
# A suitable TOTP_ENCRYPTION_KEY: python -c 'import secrets; print(secrets.token_hex(32))'
docker compose up --build -d
docker compose exec api python manage.py seed_dev
docker compose exec api python manage.py bootstrap_admin --phone +88017XXXXXXXX --name 'Gym Operator' --browser-access
```

Replace the phone placeholder with your actual Bangladesh phone number. `bootstrap_admin` prompts for an operator password only with `--browser-access`. It prints a **one-time setup token** for authenticator enrollment. Keep that token private. There are no seeded credentials, and the command refuses to replace an existing super admin.

The API listens at `http://localhost:8080`. Open `/docs/` for Swagger, `/openapi.yaml` for the schema, `/admin/` for the inspect-only operator console, `/health/` for database readiness, and `/health/live/` for liveness. Migrations run before Gunicorn starts. The initial migration installs default gym hours: Saturday–Thursday 06:00–22:00, Friday closed.

Compose uses its own project name, PostgreSQL database (`gyma_django`), persistent volumes, and host database port (`55432`). It does not connect to, import, or alter the Go database. Set `HTTP_PORT` if port 8080 is already occupied. `docker compose down` preserves data; deleting volumes intentionally resets this backend.

`seed_dev` adds the original monthly/quarterly/annual catalog math (rate 1500, admission 1500, standing discounts 0/500/3500). It is idempotent, creates no accounts, and is disabled in production. Plans can also be created through the staff API.

## Local Python development

Install Python 3.14 and `uv`, then:

```bash
uv sync --locked
docker compose up -d db
uv run python manage.py migrate
uv run python manage.py seed_dev
uv run python manage.py runserver 0.0.0.0:8080
```

Use the host PostgreSQL URL from `.env.example` for local Python. Compose overrides it with the internal `db` hostname. If your rootless Docker/network setup does not expose the database to host processes, run commands through `docker compose exec api` and use the container test workflow below.

## API and authentication

See [API migration reference](docs/API_MIGRATION.md) for every old/new route, payload rules, examples, and integration differences. The committed [OpenAPI schema](docs/openapi.yaml) describes the new contract. It is also generated live at `/openapi.yaml`.

Member login uses phone OTP or verified Google/Firebase identity. Staff login uses TOTP. API credentials are Bearer HS256 access JWTs and opaque, hashed refresh tokens with one-time rotation. No password-grant API was added. Browser operator access is granted explicitly and uses Django sessions, password validation, CSRF protection, and login throttling.

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
- **Deployment:** set `APP_ENV=prod`, private Django/JWT keys, `ALLOWED_HOSTS`, HTTPS `PUBLIC_BASE_URL`, explicit CORS origins, and `CSRF_TRUSTED_ORIGINS`. Production rejects the shipped example signing keys, requires provider/device settings, disables bypasses/sandbox, and enables secure cookies, HTTPS redirects, and HSTS. Preserve database and media volumes.
- **Reverse proxy:** set `TRUSTED_PROXY_IPS` to the exact addresses of your proxies. Configure those proxies to overwrite `X-Forwarded-Proto` and append the real source address to `X-Forwarded-For`. Forwarded headers from other addresses are ignored. This enables correct HTTPS detection, absolute pagination links, and per-client throttling behind TLS termination. Without a trusted proxy, Gunicorn must receive HTTPS-aware requests directly or `SECURE_SSL_REDIRECT` must be configured for your deployment. Readiness/liveness are exempt from HTTPS redirects for internal probes.

The operator console is deliberately inspect-only, including users and financial records. Staff mutations use the APIs and shared services, retaining business validation and activity recording. OTP/session tables and encrypted authenticator secrets are not exposed in the console.

The recovery-email provider, notifications feed, and physical fingerprint-device protocol were incomplete in Go and remain outside the port. Recovery email returns 502 without the explicit development bypass. The dashboard retains its existing `has_unread_notifications: false` behavior.

## Verification

Run the full PostgreSQL suite independently of host networking:

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

Tests use an isolated PostgreSQL test database, fake provider boundaries, and temporary media storage. They cover API workflows, authorization, schema/route inventory, constraints, rollback, parallel OTP/refresh/payment/check-in operations, date boundaries, upload limits, provider failures, and production configuration. They do not contact Firebase, SMS, or SSLCommerz.

## Organization

Django apps separate accounts, members, plans, payments, operations, attendance, and reporting. Serializers validate transport inputs; services own business operations and transactions; views enforce endpoint permissions and delegate to services. Django migrations own the fresh schema. No Celery, Redis, scheduler, or legacy database compatibility layer is required.
