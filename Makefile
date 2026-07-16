.PHONY: lint test migrate seed run-api run-worker

lint:
	uv run ruff check .
	uv run ruff format --check .

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
