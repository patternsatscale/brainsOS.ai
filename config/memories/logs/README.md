---
title: Audit Logs Specification
type: logs
created: 2026-09-06
tags:
  - okf
  - logs
  - audit
---

# Audit Logs & Traces (`logs/`)

The `logs/` directory contains human-auditable execution logs, session summaries, and diagnostic traces recorded by the agent or operator.

## Guidelines

1. **Human Auditability**: All logs must be standard Markdown files with timestamps.
2. **Never Dumped into LLM Context**: Historical logs are stored on disk and inspected via SilverBullet or on-demand tool calls; they are never dumped into the prompt context.
3. **Session Structure**: Every session log should document the objective, actions executed, tool invocations, and exit status.
4. **Starter Template**: Use [[logs/template|logs/template.md]] when logging sessions.
