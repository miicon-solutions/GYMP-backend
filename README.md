# GYMA Django backend

Python 3.14, Django 5.2 LTS, Django REST Framework, and PostgreSQL. This is a complete, independently runnable port of the implemented Go backend. It uses a **new database** and a **breaking API contract**. The Go project is unchanged; the Flutter client in `GYMA_a` targets this Django API.

## Start with Docker

Run these commands in `GYMA_b`:

```bash
cp .env.example .env
# Edit .env; generate private Django/JWT secrets and a TOTP encryption key.
# Set DATABASE_URL and the AWS_* settings for your external PostgreSQL and MinIO.
# A suitable TOTP_ENCRYPTION_KEY: python -c 'import secrets; print(secrets.token_hex(32))'
docker compose up --build -d
docker compose exec api python manage.py seed_dev
docker compose exec api python manage.py bootstrap_admin --phone +88017XXXXXXXX --name 'Gym Operator' --browser-access
```

Replace the phone placeholder with your actual Bangladesh phone number. `bootstrap_admin` prompts for an operator password only with `--browser-access`. It prints a **one-time setup token** for authenticator enrollment. Keep that token private. There are no seeded credentials, and the command refuses to replace an existing super admin.

The API listens at `http://localhost:8080`. Open `/docs/` for Swagger, `/openapi.yaml` for the schema, `/admin/` for the inspect-only operator console, `/health/` for database readiness, and `/health/live/` for liveness. Migrations run before Gunicorn starts. The initial migration installs default gym hours: Saturday–Thursday 06:00–22:00, Friday closed.

Compose runs the API; PostgreSQL and MinIO/S3 are managed separately. Create a dedicated empty PostgreSQL database for this backend and set `DATABASE_URL` to its connection URL. Do not point it at the Go database: startup runs Django migrations against the configured database. Set `HTTP_PORT` if port 8080 is already occupied. Stopping Compose leaves the external database and bucket untouched.

For PostgreSQL running in another Docker container with host port 5432 published, use `postgres://USER:PASSWORD@host.docker.internal:5432/DATABASE` from Compose. The file includes the Linux host-gateway mapping. Use your actual published port and URL-encode special characters in credentials. PostgreSQL must accept connections from the API container; a port published only on host loopback may be inaccessible through the gateway. Containers on a shared Docker network can instead use the database container's network hostname (attach the API using a local Compose override). `localhost` inside the API container refers to the API itself.

`seed_dev` adds the original monthly/quarterly/annual catalog math (rate 1500, admission 1500, standing discounts 0/500/3500). It is idempotent, creates no accounts, and is disabled in production. Plans can also be created through the staff API.

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
AWS_LOCATION=media
AWS_QUERYSTRING_EXPIRE=3600
```

Use MinIO's S3 API port (usually 9000), not its console port. The endpoint hostname/IP must resolve and be reachable from **both the backend and photo-viewing clients**: it appears in signed download URLs. A host LAN IP or shared DNS name works when both can reach it. Container-only names such as `minio` or `host.docker.internal` usually cannot be used by phones or other client machines. Do not rewrite the hostname in a signed URL; doing so invalidates its signature. Use HTTPS outside local development.

For AWS S3, leave `AWS_S3_ENDPOINT_URL` empty, set `AWS_S3_REGION_NAME` to the bucket's region, and use `AWS_S3_ADDRESSING_STYLE=virtual`. Set AWS access credentials and optionally `AWS_SESSION_TOKEN`, or leave them blank to use the deployment's IAM role/default AWS credential chain. Grant bucket listing and object read/write/delete access to the selected prefix. Keep public access blocked; no object ACL is sent.

`AWS_LOCATION` defaults to `media` and prefixes object keys; keep it stable once files have been uploaded. `AWS_QUERYSTRING_EXPIRE` defaults to 3600 seconds and accepts 1–604800 seconds. The API returns a freshly signed `photo_url` when a profile is fetched. Treat it as temporary: fetch the profile again after expiry instead of persisting the URL. Upload/replacement/deletion endpoints and the 5 MB JPEG/PNG/WebP validation remain unchanged. In S3 mode, the legacy public `/media/member-photos/` route returns 404.

`MEDIA_STORAGE=filesystem` is available for tests or standalone development and uses `MEMBER_PHOTO_DIR`. Without `MEDIA_STORAGE`, filesystem storage is used so image builds and isolated checks need no storage credentials. Filesystem mode retains the public local photo route. Compose does not provide a media volume; use S3 mode for durable container uploads. S3 failures never fall back to disk. Static assets remain local and are served by WhiteNoise. Existing local files are not automatically copied to a bucket.

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
- **Deployment:** set `APP_ENV=prod`, private Django/JWT keys, `ALLOWED_HOSTS`, HTTPS `PUBLIC_BASE_URL`, explicit CORS origins, and `CSRF_TRUSTED_ORIGINS`. Production rejects the shipped example signing keys, requires provider/device settings, disables bypasses/sandbox, and enables secure cookies, HTTPS redirects, and HSTS. Configure external `DATABASE_URL` and `MEDIA_STORAGE=s3` with the AWS bucket settings above; back up the database and bucket separately.
- **Reverse proxy:** set `TRUSTED_PROXY_IPS` to the exact addresses of your proxies. Configure those proxies to overwrite `X-Forwarded-Proto` and append the real source address to `X-Forwarded-For`. Forwarded headers from other addresses are ignored. This enables correct HTTPS detection, absolute pagination links, and per-client throttling behind TLS termination. Without a trusted proxy, Gunicorn must receive HTTPS-aware requests directly or `SECURE_SSL_REDIRECT` must be configured for your deployment. Readiness/liveness are exempt from HTTPS redirects for internal probes.

The operator console is deliberately inspect-only, including users and financial records. Staff mutations use the APIs and shared services, retaining business validation and activity recording. OTP/session tables and encrypted authenticator secrets are not exposed in the console.

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
