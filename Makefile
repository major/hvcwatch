.PHONY: test lint typecheck complexity all

test:
	uv run pytest

lint:
	uv run ruff format

typecheck:
	uv run ty check src

complexity:
	uv run radon cc src/ -s -n C --no-assert

all: lint test typecheck complexity
