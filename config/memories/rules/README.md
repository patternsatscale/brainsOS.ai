---
title: Operator Rules & Guardrails Specification
type: rules
created: 2026-09-06
tags:
  - okf
  - rules
  - guardrails
---

# Operator Rules & Guardrails (`rules/`)

The `rules/` directory houses behavioral directives, security constraints, and operational preferences set by human operators.

## Rule Lifecycle & Ingestion

1. **Active Rule Injection**: Rules marked with `active: true` in their frontmatter (or active by default) are synthesized into Hermes's prompt context by the `hermes-okf` plugin.
2. **Immediate Effect**: When an operator modifies or adds a rule file in SilverBullet (`http://memory.titan.local`), it is immediately included in the next agent reasoning turn.
3. **Budgeting**: Total rule context is capped to preserve context budget (max 2,500 characters on 4k setups; expanded on 32k GX10).
4. **Starter Template**: Use [[rules/template|rules/template.md]] when defining new guardrails.
