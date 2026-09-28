# ==============================================================================
# brainsOS: Root Orchestration & Lifecycle Makefile
# ==============================================================================

SHELL := /usr/bin/env bash

VENV_DIR ?= .venv
PYTEST ?= $(if $(wildcard $(VENV_DIR)/bin/pytest),$(VENV_DIR)/bin/pytest,pytest)
RUFF ?= $(if $(wildcard $(VENV_DIR)/bin/ruff),$(VENV_DIR)/bin/ruff,ruff)
MYPY ?= $(if $(wildcard $(VENV_DIR)/bin/mypy),$(VENV_DIR)/bin/mypy,mypy)

.PHONY: help setup up down test lint emergency-stop

help:
	@echo "brainsOS Developer Lifecycle Commands:"
	@echo "  make setup          - Bootstrap environment (.env, data dirs, venv, packages)"
	@echo "  make up             - Synchronize agent manifest and start Docker fleet"
	@echo "  make down           - Stop all running Docker services"
	@echo "  make test           - Run full pytest test suite across packages"
	@echo "  make lint           - Run ruff linter and mypy type checks"
	@echo "  make emergency-stop - Instantly terminate all agent containers"

setup:
	@scripts/control/bootstrap-env.sh

up:
	@scripts/control/sync-agents.sh
	@docker compose up -d

down:
	@docker compose down

test:
	@$(PYTEST) packages/*/tests

lint:
	@$(RUFF) check packages/
	@$(MYPY) packages/

emergency-stop:
	@docker compose kill $$(docker compose ps --services 2>/dev/null | grep agent- || true)
