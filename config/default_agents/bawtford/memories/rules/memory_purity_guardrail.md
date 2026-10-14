---
title: Memory Plane Purity Guardrail
type: rules
active: true
priority: high
tags:
  - security
  - memory
  - guardrail
---

# Rule: Memory Plane Purity Guardrail

## 1. Directive & Constraint
The agent must never write binary files, databases, package caches, or runtime dumps into `/memories`. All long-term memories must be formatted as human-auditable Open Knowledge Format (OKF) Markdown notes.

## 2. Rationale
Zero-trust architecture mandates human auditability and prevention of database corruption.

## 3. Scope & Enforcement
Hard guardrail enforced across all tool executions and memory operations.
