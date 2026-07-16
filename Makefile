.PHONY: lint lint-ops test migrate seed run-api run-worker

lint:
	uv run ruff check .
	uv run ruff format --check .

# macOS-only checks for the ops surface (plutil ships with macOS).
lint-ops:
	shellcheck scripts/*.sh
	for plist in deploy/launchd/*.plist; do plutil -lint "$$plist" || exit 1; done

test:
	uv run pytest -m "not eval and not network"

migrate:
	uv run alembic upgrade head

seed:
	uv run python -m skywatch.db.seed

run-api:
	uv run python -m skywatch.api

run-worker:
	uv run python -m skywatch.pipeline.worker
