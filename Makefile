.PHONY: lint test run-api run-worker

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest -m "not eval and not network"

run-api:
	uv run python -m skywatch.api

run-worker:
	uv run python -m skywatch.pipeline.worker
