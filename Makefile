# TradeLens developer and operator commands (Detailed Design 6.8).
# Linux/macOS: make <target>.  Windows: mingw32-make <target> (see README).
# Container targets need Docker Compose v2 and deploy/.env.

ifeq ($(OS),Windows_NT)
PY_BOOT ?= py -3.12
PY := .venv/Scripts/python.exe
BIN := .venv/Scripts
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
        build up down logs health psql migrate seed init

help:
	@echo "Local:     venv install test test-engine test-api lint lint-imports typecheck check migrate-sql doctor"
	@echo "Container: init build up down logs health psql migrate seed"

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

init: doctor build
	$(COMPOSE) up -d postgres redis
	$(MAKE) migrate
	$(MAKE) seed
	$(COMPOSE) up -d
