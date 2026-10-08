.DEFAULT_GOAL := help

ENV ?= development

# Shorthand: source env vars then run a command
run_with_env = bash -c "source scripts/set_env.sh $(ENV) && $(1)"

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
install:
	pip install uv
	uv sync
	uv run pre-commit install

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
dev:
	@$(call run_with_env,uv run python scripts/run_local.py --reload)

worker:
	@$(call run_with_env,uv run taskiq worker app.core.task_queue:broker app.workers.fund_sync app.workers.screenshot_import app.workers.memory_write)

staging:
	@$(call run_with_env,$(MAKE) _serve ENV=staging)

prod:
	@$(call run_with_env,$(MAKE) _serve ENV=production)

_serve:
	@$(call run_with_env,./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --loop uvloop)

# ---------------------------------------------------------------------------
# Database migrations
# ---------------------------------------------------------------------------
migrate:
	@$(call run_with_env,uv run alembic upgrade head)

migration:
	@if [ -z "$(MSG)" ]; then \
		echo "Usage: make migration MSG=\"describe your change\""; exit 1; \
	fi
	@$(call run_with_env,uv run alembic revision --autogenerate -m '$(MSG)')

migrate-downgrade:
	@$(call run_with_env,uv run alembic downgrade -1)

migrate-history:
	@$(call run_with_env,uv run alembic history --verbose)

# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
eval:
	@$(call run_with_env,python -m evals.main --interactive)

eval-quick:
	@$(call run_with_env,python -m evals.main --quick)

eval-no-report:
	@$(call run_with_env,python -m evals.main --no-report)

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------
test:
	@$(call run_with_env,uv run pytest -q)

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run pyright

check: lint typecheck
	@echo "All checks passed"

pre-commit:
	uv run pre-commit run --all-files

pre-commit-update:
	uv run pre-commit autoupdate

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
clean:
	rm -rf .venv __pycache__ .pytest_cache

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
help:
	@echo "Usage: make <target> [ENV=development|staging|production|test]"
	@echo ""
	@echo "Setup:"
	@echo "  install              Install deps, set up pre-commit hooks"
	@echo ""
	@echo "Server:"
	@echo "  dev                  Dev server with hot reload (port 8000)"
	@echo "  worker               Taskiq worker (fund sync + screenshot import)"
	@echo "  staging              Staging server"
	@echo "  prod                 Production server"
	@echo ""
	@echo "Database:"
	@echo "  migrate              Run migrations to latest (default ENV=development)"
	@echo "  migration MSG=...    Generate migration from model changes"
	@echo "  migrate-downgrade    Rollback last migration"
	@echo "  migrate-history      Show migration history"
	@echo ""
	@echo "Evaluation:"
	@echo "  eval                 Run evals (interactive)"
	@echo "  eval-quick           Run evals (default settings)"
	@echo "  eval-no-report       Run evals without report"
	@echo ""
	@echo "Code quality:"
	@echo "  test                 Pytest suite (unit + pure functions)"
	@echo "  lint                 Ruff lint check"
	@echo "  format               Ruff format"
	@echo "  typecheck            Pyright static type check"
	@echo "  check                Run lint + typecheck"
	@echo "  pre-commit           Run all pre-commit hooks"
	@echo "  pre-commit-update    Update pre-commit hook versions"
	@echo ""
	@echo "Misc:"
	@echo "  clean                Remove .venv, __pycache__, .pytest_cache"

.PHONY: install dev worker staging prod _serve \
        migrate migration migrate-downgrade migrate-history \
        eval eval-quick eval-no-report \
        lint format typecheck check pre-commit pre-commit-update test \
        clean help
