.DEFAULT_GOAL := help
.PHONY: help install dev-infra dev-infra-down db-create db-migrate db-revision \
        api app dev test test-api test-app lint lint-api lint-app typecheck \
        build build-api build-app up down logs clean

SHELL := /bin/bash

# Read .env so recipes see APP_DATABASE_URL and friends without exporting them
# by hand. Missing file is not an error — `make install` works before setup.
-include .env
export

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Setup ────────────────────────────────────────────────────────────────────

install: ## Install API and frontend dependencies
	cd api && pip install -e ".[dev]"
	cd application && npm install

# ── Local infrastructure ─────────────────────────────────────────────────────

dev-infra: ## Start Azure SQL Edge and create both databases
	docker compose up -d mssql db-init

dev-infra-cache: ## Start Azure SQL Edge plus Redis (only needed for >1 API replica)
	docker compose --profile cache up -d mssql db-init redis

dev-infra-down: ## Stop local infrastructure (keeps the data volume)
	docker compose down

db-create: ## Create the two databases (idempotent; dev-infra does this already)
	docker compose up db-init

db-migrate: ## Apply migrations to the app database
	cd api && alembic upgrade head

db-revision: ## Autogenerate a migration — make db-revision M="add widgets"
	cd api && alembic revision --autogenerate -m "$(M)"

# ── Run ──────────────────────────────────────────────────────────────────────

api: ## Run the API with reload on :8000 (Swagger at /docs)
	cd api && uvicorn app.main:app --reload --port 8000

app: ## Run the Next.js dev server on :3000
	cd application && npm run dev

dev: ## Everything in one command — database, migrations, API, and frontend
	@bash scripts/dev.sh

# ── Test and lint ────────────────────────────────────────────────────────────

test: test-api test-app ## Run every test suite

test-api: ## API unit tests — mocked DB, no server needed
	cd api && python -m pytest tests/ -q

test-app: ## Frontend unit tests
	cd application && npm run test

lint: lint-api lint-app ## Lint both layers

lint-api: ## ruff + mypy
	cd api && ruff check app/ tests/ alembic/ && mypy app/

lint-app: ## eslint
	cd application && npm run lint

typecheck: ## tsc --noEmit
	cd application && npm run type-check

# ── Containers ───────────────────────────────────────────────────────────────

build: build-api build-app ## Build both images

build-api: ## Build the API image
	docker build -t power-bi-platform-api:local ./api

build-app: ## Build the frontend image (bakes NEXT_PUBLIC_API_URL)
	docker build -t power-bi-platform-app:local \
	  --build-arg NEXT_PUBLIC_API_URL=$${NEXT_PUBLIC_API_URL:-http://localhost:8000} \
	  ./application

up: ## Run the whole stack in containers
	docker compose --profile full up -d --build

down: ## Stop the container stack
	docker compose --profile full down

logs: ## Tail container logs
	docker compose logs -f

clean: ## Remove containers and the database volume (destroys local data)
	docker compose --profile full --profile cache down -v
