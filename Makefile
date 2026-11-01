# SEO Engine — developer shortcuts.
#
# These wrap the commands the Build Specification's quality gate (§80) runs, so
# "does it pass?" is one target, not a remembered incantation.

.DEFAULT_GOAL := help
PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff
PYTEST ?= .venv/bin/pytest

.PHONY: help install migrate seed lint typecheck test test-fast security gate run worker up down

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install everything
	python3.12 -m venv .venv
	$(PYTHON) -m pip install -U pip
	$(PYTHON) -m pip install -e ".[dev,worker,llm,storage]"

migrate: ## Run database migrations to head
	$(PYTHON) -m alembic upgrade head

seed: ## Create the demonstration tenant
	$(PYTHON) -m seo_engine.database.seed --reset

lint: ## Lint and format-check
	$(RUFF) check .
	$(RUFF) format --check .

typecheck: ## Static type check
	$(PYTHON) -m mypy packages apps

test: ## Full test suite (needs PostgreSQL + Redis)
	$(PYTEST) -q

test-fast: ## Unit tests only (no database)
	$(PYTEST) -q tests/unit

security: ## Security regression tests only
	$(PYTEST) -q -m security

gate: lint typecheck test ## The MVP quality gate: lint + typecheck + full suite

run: ## Run the API locally with reload
	$(PYTHON) -m uvicorn seo_engine.api.main:app --reload

worker: ## Run the worker process
	$(PYTHON) -m seo_engine.worker

up: ## Start the full stack in Docker
	docker compose up --build

down: ## Stop the stack and remove volumes
	docker compose down -v
