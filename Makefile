# ==============================================================================
# brainsOS: Root Orchestration & Lifecycle Makefile
# ==============================================================================

SHELL := /usr/bin/env bash

VENV_DIR ?= .venv
PYTEST ?= $(if $(wildcard $(VENV_DIR)/bin/pytest),$(VENV_DIR)/bin/pytest,pytest)
RUFF ?= $(if $(wildcard $(VENV_DIR)/bin/ruff),$(VENV_DIR)/bin/ruff,ruff)
MYPY ?= $(if $(wildcard $(VENV_DIR)/bin/mypy),$(VENV_DIR)/bin/mypy,mypy)

.PHONY: help install setup env urls reload_env reload-env up down stop-all nuke destroy test lint emergency-stop runner-base runners runner-hermes runner-openai runner-claude backup restore email-ingress email-test skills skills-sync build images trust-ca ssl-wildcard deploy-infra models-pull models-check langfuse langfuse-setup langfuse-status langfuse-stop langfuse-sync update update-check prune-logs build-ami set-domain

STAGE ?= $(if $(BRAINSOS_STAGE),$(BRAINSOS_STAGE),osx)

help:
	@echo "brainsOS Developer Lifecycle Commands:"
	@echo "  make install        - Turnkey interactive appliance installer (env, setup, portal & credentials)"
	@echo "  make setup          - Turnkey bootstrap (.env, data dirs, venv, packages, portal & images)"
	@echo "  make update         - Universal platform update (git sync, container pull, migrations & rollback)"
	@echo "  make update-check   - Check current versions vs latest upstream releases"
	@echo "  make prune-logs     - Prune historical docker, journald, and service logs (ARGS=--dry-run)"
	@echo "  make build-ami      - Build private ARM64 appliance AMI from a git ref (ARGS='--ref vX.Y.Z [--dry-run]' | '--promote ami-...')"
	@echo "  make set-domain     - Configure custom domain (BYOD) & TLS mode (ARGS='--domain <fqdn> --email <addr> [--dns route53]')"
	@echo "  make models-pull    - Seed and pull required LLM weights into local Ollama"
	@echo "  make models-check   - Check presence of required LLM weights in local Ollama"
	@echo "  make build          - Build base runner and all platform container images"
	@echo "  make ssl-wildcard   - Configure public wildcard SSL via Route 53 & SST Ion (*.local.<zone>)"
	@echo "  make deploy-infra   - Deploy platform cloud infrastructure via SST Ion (Route 53, ACME IAM, SES)"
	@echo "  make trust-ca       - Export & install Caddy internal root CA into host trust store"
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
	@echo "  make destroy        - Reset OS (containers, volumes, daemons, .env; runtime data preserved unless --include-data)"
	@echo "  make backup         - Create a full data plane backup archive"
	@echo "  make restore        - Restore data planes from latest archive (or ARCHIVE=<file>)"
	@echo "  make test           - Run full pytest test suite across packages"
	@echo "  make email-ingress  - Deploy AWS SES, S3, SQS & Sanitizer Lambda via SST (STAGE=osx)"
	@echo "  make email-test     - Run automated email ingress verification harness (optional: ARGS=--e2e)"
	@echo "  make lint           - Run ruff linter and mypy type checks"
	@echo "  make runner-base    - Build base runner container image (brainsos-runner-base:latest)"
	@echo "  make runners        - Build all runner images (hermes, openai, claude)"
	@echo "  make emergency-stop - Instantly terminate agent runner container"

models-pull:
	@scripts/setup/setup-models.sh $(ARGS)

models-check:
	@scripts/setup/setup-models.sh --check

ssl-wildcard:
	@scripts/setup/setup-wildcard-ssl.sh $(ARGS)

deploy-infra:
	@scripts/setup/deploy-infra.sh $(ARGS)

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

build: runner-base
	docker compose build

images: build

portal-build:
	@cd packages/brainsOS-portal && npm run build

trust-ca:
	@scripts/setup/trust-caddy-ca.sh $(ARGS)

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

install:
	@scripts/control/install.sh $(ARGS)

setup:
	@scripts/control/bootstrap-env.sh $(ARGS)

env:
	@scripts/control/generate-env.sh $(ARGS)

reload_env: reload-env

reload-env:
	@scripts/control/reload-env.sh $(ARGS)

refresh-env: reload-env
refresh_env: reload-env

urls:
	@scripts/control/show-urls.sh $(ARGS)

update:
	@scripts/control/update.sh $(ARGS)

update-check:
	@scripts/control/update.sh --check $(ARGS)

prune-logs:
	@scripts/control/prune-logs.sh $(ARGS)

build-ami:
	@scripts/control/build-ami.sh $(ARGS)

set-domain:
	@scripts/control/set-domain.sh $(ARGS)

up: runner-base
	@if [ ! -f .env ]; then \
		echo "[ERROR] No .env file found in repository root."; \
		echo "Please run 'make setup' (recommended) or 'make env' to initialize your environment first."; \
		exit 1; \
	fi
	@if [ ! -f packages/brainsOS-portal/dist/index.html ]; then \
		echo "[INFO] Portal static bundle missing. Building packages/brainsOS-portal..."; \
		if [ -f scripts/setup/setup-portal.sh ]; then \
			scripts/setup/setup-portal.sh || (cd packages/brainsOS-portal && npm run build); \
		else \
			(cd packages/brainsOS-portal && npm run build); \
		fi; \
	fi
	@scripts/control/reload-env.sh --no-urls $(ARGS)

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

destroy:
	@scripts/control/destroy.sh $(ARGS)

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
