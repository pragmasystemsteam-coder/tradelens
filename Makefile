# TradeLens developer and operator commands (Detailed Design 6.8).
# Linux/macOS: make <target>.  Windows: mingw32-make <target> (see README).
# Container targets need Docker Compose v2 and deploy/.env.

ifeq ($(OS),Windows_NT)
PY_BOOT ?= py -3.12
PY := .venv/Scripts/python.exe
BIN := .venv/Scripts
# Git Bash rewrites container paths such as /app/config into C:/...; stop it for docker calls.
export MSYS_NO_PATHCONV := 1
else
PY_BOOT ?= python3.12
PY := .venv/bin/python
BIN := .venv/bin
endif

-include deploy/.env

COMPOSE := docker compose -f deploy/docker-compose.yml --env-file deploy/.env
ALEMBIC := $(PY) -m alembic -c backend/alembic.ini

.PHONY: help venv install test test-engine test-api lint-imports lint format typecheck check \
        migrate-sql doctor \
        build up down logs health psql migrate seed load-plans create-user init

help:
	@echo "Local:     venv install test test-engine test-api lint lint-imports typecheck check migrate-sql doctor verify-instruments web-check"
	@echo "Container: init build up down logs health psql migrate seed load-plans create-user test-db"

venv:
	$(PY_BOOT) -m venv .venv

install: venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e engine[dev] -e backend[dev]

# One command for every automated test (NFR-16). Integration tests run when
# TEST_DATABASE_URL points at a disposable PostgreSQL; otherwise they skip.
test: lint-imports
	$(PY) -m pytest

test-engine:
	$(PY) -m pytest engine/tests

test-api:
	$(PY) -m pytest backend/tests

# Architecture contracts (ADR-0001) and engine purity.
lint-imports:
	$(BIN)/lint-imports --config backend/pyproject.toml
	$(BIN)/lint-imports --config engine/pyproject.toml

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

typecheck:
	$(PY) -m mypy --config-file engine/pyproject.toml engine/src
	$(PY) -m mypy --config-file backend/pyproject.toml backend/src

# Everything a reviewer expects green before a commit.
check: lint typecheck test

# Print the SQL of every migration without a database (Alembic offline mode).
migrate-sql:
	$(ALEMBIC) upgrade head --sql

doctor:
	$(PY) -m tradelens.cli doctor deploy/.env

# Checks config/instruments.json against the market-data provider (offline checks always;
# LIVE=1 also asks Twelve Data's symbol search, 1 credit per instrument).
verify-instruments:
	$(PY) -m tradelens.cli verify-instruments config $(if $(LIVE),--live,)

# Type-check, lint and build both Next.js apps.
web-check:
	cd web && npm ci --no-audit --no-fund && npm run typecheck && npm run lint && npm run build
	cd admin-web && npm ci --no-audit --no-fund && npm run typecheck && npm run lint && npm run build

# Integration tests against a throwaway PostgreSQL 16 on 127.0.0.1:55432 (always removed afterwards).
test-db:
	$(PY) scripts/test_db.py

# ---- container targets ---------------------------------------------------
build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

health:
	$(COMPOSE) ps

psql:
	$(COMPOSE) exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

# Migrations run with the owner role; the app role never alters the schema.
migrate:
	$(COMPOSE) run --rm --no-deps -e DATABASE_MIGRATION_URL=$(DATABASE_MIGRATION_URL) api python -m alembic -c alembic.ini upgrade head

seed:
	$(COMPOSE) run --rm --no-deps -e DATABASE_MIGRATION_URL=$(DATABASE_MIGRATION_URL) api python -m tradelens.cli seed /app/config

# Upsert config/plans.json (plans, prices, country currencies, founder caps); also part of seed.
load-plans:
	$(COMPOSE) run --rm --no-deps -e DATABASE_MIGRATION_URL=$(DATABASE_MIGRATION_URL) -e RAZORPAY_MODE=$(RAZORPAY_MODE) api python -m tradelens.cli load-plans /app/config

# Demo or staff user with a manual plan: make create-user EMAIL=a@b.c ROLE=customer PLAN=pro_monthly
# (refuses when APP_ENV=production; prints a generated password once unless CREATE_USER_PASSWORD is set).
create-user:
	$(COMPOSE) run --rm --no-deps -e DATABASE_MIGRATION_URL=$(DATABASE_MIGRATION_URL) -e APP_ENV=$(APP_ENV) -e CREATE_USER_PASSWORD api python -m tradelens.cli create-user $(EMAIL) $(ROLE) $(PLAN)

init: doctor build
	$(COMPOSE) up -d postgres redis
	$(MAKE) migrate
	$(MAKE) seed
	$(COMPOSE) up -d
