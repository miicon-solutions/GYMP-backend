.PHONY: install run migrate test check lint format schema
install:
	uv sync --locked
run:
	uv run python manage.py runserver 0.0.0.0:8080
migrate:
	uv run python manage.py migrate
check:
	uv run python manage.py check
	uv run python manage.py makemigrations --check --dry-run
lint:
	uv run ruff check .
	uv run ruff format --check .
format:
	uv run ruff check --fix .
	uv run ruff format .
test:
	uv run pytest
schema:
	uv run python manage.py spectacular --file docs/openapi.yaml --validate --fail-on-warn
