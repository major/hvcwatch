.PHONY: test lint typecheck complexity all

test:
	uv run pytest

lint:
	uv run ruff format

typecheck:
	uv run ty check src

complexity:
	uv run ruff check --select C901 src/

all: lint test typecheck complexity
