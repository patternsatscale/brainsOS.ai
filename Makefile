# ==============================================================================
# brainsOS: Root Orchestration & Lifecycle Makefile
# ==============================================================================

SHELL := /usr/bin/env bash

VENV_DIR ?= .venv
PYTEST ?= $(if $(wildcard $(VENV_DIR)/bin/pytest),$(VENV_DIR)/bin/pytest,pytest)
RUFF ?= $(if $(wildcard $(VENV_DIR)/bin/ruff),$(VENV_DIR)/bin/ruff,ruff)
MYPY ?= $(if $(wildcard $(VENV_DIR)/bin/mypy),$(VENV_DIR)/bin/mypy,mypy)

.PHONY: help setup env urls reload_env reload-env up down stop-all nuke test lint emergency-stop runner-base runners runner-hermes runner-openai runner-claude backup restore email-ingress email-test skills skills-sync langfuse langfuse-setup langfuse-status langfuse-stop langfuse-sync

STAGE ?= $(if $(BRAINSOS_STAGE),$(BRAINSOS_STAGE),osx)

help:
	@echo "brainsOS Developer Lifecycle Commands:"
	@echo "  make setup          - Bootstrap environment (.env, data dirs, venv, packages)"
	@echo "  make skills         - Synchronize default and data plane skills to .agents/skills and bundled package"
	@echo "  make env            - Generate .env with secure passwords, configure URLs, and rebuild"
	@echo "  make reload_env     - Reload .env, synchronize passwords across DBs/containers, and show URLs"
	@echo "  make urls           - Display all service URLs & credentials, and synchronize /etc/hosts"
	@echo "  make up             - Start platform Docker services and shared runner"
	@echo "  make down           - Stop all Docker services and host control plane"
	@echo "  make stop-all       - Stop all Docker containers, host LiteLLM, Ollama, and workers"
	@echo "  make langfuse       - Start Langfuse v4 distributed observability stack"
	@echo "  make langfuse-status- Check Langfuse health, containers, and OTel ingestion"
	@echo "  make nuke           - Forcefully terminate all brainsOS containers and background processes (battery saver)"
	@echo "  make backup         - Create a full data plane backup archive"
	@echo "  make restore        - Restore data planes from latest archive (or ARCHIVE=<file>)"
	@echo "  make test           - Run full pytest test suite across packages"
	@echo "  make email-ingress  - Deploy AWS SES, S3, SQS & Sanitizer Lambda via SST (STAGE=osx)"
	@echo "  make email-test     - Run automated email ingress verification harness (optional: ARGS=--e2e)"
	@echo "  make lint           - Run ruff linter and mypy type checks"
	@echo "  make runner-base    - Build base runner container image (brainsos-runner-base:latest)"
	@echo "  make runners        - Build all runner images (hermes, openai, claude)"
	@echo "  make emergency-stop - Instantly terminate agent runner container"

runner-base:
	docker build -t brainsos-runner-base:latest -f docker/runners/base/Dockerfile .

runner-hermes: runner-base
	@scripts/control/burn-hermes-config.sh
	docker compose build runner-hermes

burn-hermes:
	@scripts/control/burn-hermes-config.sh

runner-openai: runner-base
	docker compose build runner-openai

runner-claude: runner-base
	docker compose build runner-claude

runners: runner-base runner-hermes runner-openai runner-claude

portal-build:
	@cd packages/brainsOS-portal && npm run build

portal-setup:
	@scripts/setup/setup-portal.sh

portal-verify:
	@scripts/verify/verify-portal.sh

portal: portal-setup portal-verify

langfuse:
	@scripts/setup/setup-langfuse.sh start

langfuse-setup:
	@scripts/setup/setup-langfuse.sh setup

langfuse-status:
	@scripts/setup/setup-langfuse.sh status

langfuse-stop:
	@scripts/setup/setup-langfuse.sh stop

langfuse-sync:
	@scripts/setup/setup-langfuse.sh sync

setup:
	@scripts/control/bootstrap-env.sh

env:
	@scripts/control/generate-env.sh $(ARGS)

reload_env: reload-env

reload-env:
	@scripts/control/reload-env.sh $(ARGS)

refresh-env: reload-env
refresh_env: reload-env

urls:
	@scripts/control/show-urls.sh $(ARGS)

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

email-ingress:
	@set -a && [ -f .env ] && . .env && set +a && cd infra && npx sst deploy --stage $(STAGE)

email-test:
	@scripts/verify/verify-email-ingress.sh $(ARGS)

lint:
	@$(RUFF) check packages/
	@$(MYPY) packages/

emergency-stop:
	@docker compose kill hermes-runner 2>/dev/null || true

backup:
	@scripts/control/backup.sh

restore:
	@scripts/control/backup.sh --restore $(if $(ARCHIVE),$(ARCHIVE),latest)

skills: skills-sync

skills-sync:
	@if [ -x "$(VENV_DIR)/bin/brainsos-skills" ]; then \
		$(VENV_DIR)/bin/brainsos-skills sync --repo . --target .agents/skills; \
	elif command -v brainsos-skills >/dev/null 2>&1; then \
		brainsos-skills sync --repo . --target .agents/skills; \
	elif [ -d "config/default_skills" ]; then \
		mkdir -p .agents/skills; \
		cp -R config/default_skills/* .agents/skills/ 2>/dev/null || true; \
	fi
	@mkdir -p packages/brainsOS-skills/brainsos_skills/bundled
	@cp -R config/default_skills/* packages/brainsOS-skills/brainsos_skills/bundled/ 2>/dev/null || true
	@echo "⚡ Skills synchronized to .agents/skills and brainsOS-skills bundled package!"
