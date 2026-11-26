.PHONY: install run migrate test check lint format schema notify-expiry reconcile-access cron-expiry
install:
	uv sync --locked
run:
	uv run python manage.py runserver 0.0.0.0:8080
migrate:
	uv run python manage.py migrate
check:
	uv run python manage.py check
	uv run python manage.py makemigrations --check --dry-run
	uv run python manage.py build_api_docs --check
lint:
	uv run ruff check .
	uv run ruff format --check .
format:
	uv run ruff check --fix .
	uv run ruff format .
test:
	uv run pytest
schema:
	uv run python manage.py spectacular --file docs/openapi/v1.yaml --validate --fail-on-warn
	uv run python manage.py build_api_docs
# Daily host cron (Asia/Dhaka): membership expiring/expired push+SMS, then device access reconcile.
notify-expiry:
	uv run python manage.py notify_membership_expiry
reconcile-access:
	uv run python manage.py reconcile_device_access
cron-expiry: notify-expiry reconcile-access
