# ==============================================================================
# brainsOS: Root Orchestration & Lifecycle Makefile
# ==============================================================================

SHELL := /usr/bin/env bash

VENV_DIR ?= .venv
PYTEST ?= $(if $(wildcard $(VENV_DIR)/bin/pytest),$(VENV_DIR)/bin/pytest,pytest)
RUFF ?= $(if $(wildcard $(VENV_DIR)/bin/ruff),$(VENV_DIR)/bin/ruff,ruff)
MYPY ?= $(if $(wildcard $(VENV_DIR)/bin/mypy),$(VENV_DIR)/bin/mypy,mypy)

.PHONY: help setup up down stop-all nuke test lint emergency-stop runner-base runners runner-hermes runner-openai runner-claude backup restore

help:
	@echo "brainsOS Developer Lifecycle Commands:"
	@echo "  make setup          - Bootstrap environment (.env, data dirs, venv, packages)"
	@echo "  make up             - Start platform Docker services and shared runner"
	@echo "  make down           - Stop all Docker services and host control plane"
	@echo "  make stop-all       - Stop all Docker containers, host LiteLLM, Ollama, and workers"
	@echo "  make nuke           - Forcefully terminate all brainsOS containers and background processes (battery saver)"
	@echo "  make backup         - Create a full data plane backup archive"
	@echo "  make restore        - Restore data planes from latest archive (or ARCHIVE=<file>)"
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
	@echo "[INFO] Stopping host control plane daemons..."
	@scripts/control/start-control-plane.sh stop 2>/dev/null || true
	@echo "[INFO] Stopping Docker containers..."
	@docker compose down 2>/dev/null || true

stop-all: down
	@echo "[INFO] Terminating any residual host inference or gateway processes..."
	@pkill -f "litellm" 2>/dev/null || true
	@pkill -f "ollama serve" 2>/dev/null || true
	@pkill -9 -f "brainsos" 2>/dev/null || true
	@echo "[SUCCESS] All brainsOS services and host processes have been stopped."

nuke: stop-all
	@echo "[INFO] Ensuring all brainsOS containers are stopped..."
	@docker stop $$(docker ps -q --filter "name=brainsos" 2>/dev/null) 2>/dev/null || true
	@echo "[SUCCESS] Complete shutdown finished. System is idle and battery is preserved!"

test:
	@$(PYTEST) packages/*/tests

lint:
	@$(RUFF) check packages/
	@$(MYPY) packages/

emergency-stop:
	@docker compose kill hermes-runner 2>/dev/null || true

backup:
	@scripts/control/backup.sh

restore:
	@scripts/control/backup.sh --restore $(if $(ARCHIVE),$(ARCHIVE),latest)
