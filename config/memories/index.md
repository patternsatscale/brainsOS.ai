# Project Titan: Memory Plane

Welcome to the **Project Titan Memory Plane**—the human-auditable, decoupled knowledge and governance hub for autonomous agent execution.

This workspace mounts the host filesystem (`/memories`) using the **Open Knowledge Format (OKF)**: pure, human-readable flat-file Markdown.

---

## 🧭 Memory Navigation

- **[[knowledge/README|📚 Knowledge Base]]** — Synthesized facts, architecture references, and research notes.
- **[[rules/README|🛡️ Operator Rules & Guardrails]]** — Active behavioral rules, privacy constraints, and operator directives.
- **[[logs/README|📜 Audit Logs & Traces]]** — Human-readable task logs, run summaries, and session records.
- **[[knowledge/working_memory|🧠 Working Memory]]** — Active agent scratchpad and current task context.

---

## ⚡ Quick Actions

${widgets.commandButton("Create Knowledge Note", "New Page: knowledge/")}
${widgets.commandButton("Create Operator Rule", "New Page: rules/")}
${widgets.commandButton("Create Session Log", "New Page: logs/")}

---

## 📋 Active Operator Rules

${some(query[[
  from p = index.subPages("rules")
  where p.name != "rules/README" and p.name != "rules/template"
  order by p.lastModified desc
  limit 10
  select templates.fullPageItem(p)
]]) or "_No custom operator rules defined yet. Add rules in [[rules/README|rules/]]._"}

---

## 📚 Recently Updated Knowledge

${some(query[[
  from p = index.subPages("knowledge")
  where p.name != "knowledge/README" and p.name != "knowledge/template"
  order by p.lastModified desc
  limit 10
  select templates.fullPageItem(p)
]]) or "_No custom knowledge notes yet._"}

---

## 📜 Recent Audit Logs

${some(query[[
  from p = index.subPages("logs")
  where p.name != "logs/README" and p.name != "logs/template"
  order by p.lastModified desc
  limit 10
  select templates.fullPageItem(p)
]]) or "_No session logs recorded yet._"}

---

> [!NOTE]
> **Memory Purity Enforcement**: Only Markdown (`.md`) files are allowed in this space. Binary files, SQLite databases, package caches, and virtualenvs are strictly barred to ensure zero-trust human auditability.
