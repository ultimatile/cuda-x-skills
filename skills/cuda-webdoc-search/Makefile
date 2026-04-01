.PHONY: test coverage lint typecheck check

test:
	uv run --group test pytest tests/ -v

coverage:
	uv run --group test pytest tests/ --cov=. --cov-report=term-missing

lint:
	uvx ruff check .
	uvx ruff format --check .

typecheck:
	uvx pyright

check: lint typecheck test
