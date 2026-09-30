# ==============================================================================
# brainsOS: Root Orchestration & Lifecycle Makefile
# ==============================================================================

SHELL := /usr/bin/env bash

VENV_DIR ?= .venv
PYTEST ?= $(if $(wildcard $(VENV_DIR)/bin/pytest),$(VENV_DIR)/bin/pytest,pytest)
RUFF ?= $(if $(wildcard $(VENV_DIR)/bin/ruff),$(VENV_DIR)/bin/ruff,ruff)
MYPY ?= $(if $(wildcard $(VENV_DIR)/bin/mypy),$(VENV_DIR)/bin/mypy,mypy)

.PHONY: help setup up down test lint emergency-stop runner-base

help:
	@echo "brainsOS Developer Lifecycle Commands:"
	@echo "  make setup          - Bootstrap environment (.env, data dirs, venv, packages)"
	@echo "  make up             - Start platform Docker services and shared runner"
	@echo "  make down           - Stop all running Docker services"
	@echo "  make test           - Run full pytest test suite across packages"
	@echo "  make lint           - Run ruff linter and mypy type checks"
	@echo "  make runner-base    - Build base runner container image (brainsos-runner-base:latest)"
	@echo "  make runners        - Build all runner images (hermes, openai, claude)"
	@echo "  make emergency-stop - Instantly terminate agent runner container"

runner-base:
	docker build -t brainsos-runner-base:latest -f docker/runners/base/Dockerfile .

runner-hermes: runner-base
	docker compose build runner-hermes

runner-openai: runner-base
	docker compose build runner-openai

runner-claude: runner-base
	docker compose build runner-claude

runners: runner-base runner-hermes runner-openai runner-claude

setup:
	@scripts/control/bootstrap-env.sh

up:
	@docker compose up -d

down:
	@docker compose down

test:
	@$(PYTEST) packages/*/tests

lint:
	@$(RUFF) check packages/
	@$(MYPY) packages/

emergency-stop:
	@docker compose kill hermes-runner 2>/dev/null || true
