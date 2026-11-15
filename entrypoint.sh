#!/bin/sh
set -eu

app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$app_dir"

# Load one consistent set of secrets for migrations, static files, and the server.
if [ "${GYMP_SECRETS_LOADED:-0}" != "1" ]; then
    if [ -n "${INFISICAL_TOKEN:-}" ]; then
        secret_cli=$(command -v infisical || true)
        if [ -z "$secret_cli" ]; then
            echo "Infisical CLI is missing from the image." >&2
            exit 127
        fi
        # Support the INFISICAL_API_URL name used by the deployment Compose file.
        export INFISICAL_DOMAIN="${INFISICAL_DOMAIN:-${INFISICAL_API_URL:-https://app.infisical.com/api}}"
        export INFISICAL_DISABLE_TELEMETRY=1
        echo "Loading application secrets from Infisical..."
        if [ -n "${INFISICAL_ENV:-}" ]; then
            exec "$secret_cli" run --silent --env "$INFISICAL_ENV" -- \
                env GYMP_SECRETS_LOADED=1 "$app_dir/entrypoint.sh" "$@"
        fi
        exec "$secret_cli" run --silent -- \
            env GYMP_SECRETS_LOADED=1 "$app_dir/entrypoint.sh" "$@"
    elif [ -n "${INFISICAL_API_URL:-}${INFISICAL_DOMAIN:-}" ]; then
        echo "INFISICAL_TOKEN is required when an Infisical endpoint is configured." >&2
        exit 1
    fi
fi

# Explicit commands (including local Compose's command) own their startup steps.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

port=${PORT:-8000}
case "$port" in
    ''|*[!0-9]*) echo "PORT must be a number between 1 and 65535." >&2; exit 1 ;;
esac
if [ "${#port}" -gt 5 ] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
    echo "PORT must be a number between 1 and 65535." >&2
    exit 1
fi

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn on port $port..."
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:$port" \
    --workers "${GUNICORN_WORKERS:-2}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --access-logfile /dev/null
