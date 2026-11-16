PYTHON ?= python3

.PHONY: install test lint format typecheck check

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .

typecheck:
	mypy src

check: lint typecheck test
