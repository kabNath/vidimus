.PHONY: help install dev test lint format typecheck clean build publish-test publish docs

PYTHON ?= python
PIP    ?= pip

help:
	@echo "Vidimus — common developer targets"
	@echo ""
	@echo "  make install      Install package in current environment"
	@echo "  make dev          Install package + dev dependencies + pre-commit hooks"
	@echo "  make test         Run the full test suite"
	@echo "  make lint         Run ruff lint checks"
	@echo "  make format       Auto-format code with ruff"
	@echo "  make typecheck    Run mypy"
	@echo "  make clean        Remove build artifacts and caches"
	@echo "  make build        Build sdist + wheel"
	@echo "  make publish-test Publish to TestPyPI"
	@echo "  make publish      Publish to PyPI (requires manual confirmation)"

install:
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[dev]"
	pre-commit install

test:
	$(PYTHON) -m pytest tests/ -v

test-quick:
	$(PYTHON) -m pytest tests/ -q

test-cov:
	$(PYTHON) -m pytest tests/ --cov=vidimus --cov-report=term-missing --cov-report=html

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

typecheck:
	mypy src/vidimus

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean
	$(PYTHON) -m build

publish-test: build
	$(PYTHON) -m twine upload --repository testpypi dist/*

publish: build
	@echo "About to publish to PyPI. This cannot be undone."
	@read -p "Type 'release' to confirm: " confirm && [ "$$confirm" = "release" ]
	$(PYTHON) -m twine upload dist/*

docs-serve:
	@echo "Docs site: not yet implemented. See docs/quickstart.md."

ci: lint test
	@echo "CI checks passed locally."
