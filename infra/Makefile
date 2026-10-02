# ==============================================================================
# brainsOS: Cloud Infrastructure Makefile (infra/)
# ==============================================================================

SHELL := /usr/bin/env bash

STAGE ?= $(if $(BRAINSOS_STAGE),$(BRAINSOS_STAGE),osx)

.PHONY: help deploy email-ingress diff

help:
	@echo "brainsOS Cloud Infrastructure Commands (infra/):"
	@echo "  make email-ingress  - Deploy AWS SES, S3, SQS & Sanitizer Lambda via SST (STAGE=$(STAGE))"
	@echo "  make deploy         - Deploy AWS infrastructure via SST (STAGE=$(STAGE))"
	@echo "  make diff           - Show SST diff (STAGE=$(STAGE))"

email-ingress: deploy

deploy:
	@set -a && [ -f ../.env ] && . ../.env && set +a; npx sst deploy --stage $(STAGE)

diff:
	@set -a && [ -f ../.env ] && . ../.env && set +a; npx sst diff --stage $(STAGE)
