# brainsOS-skills

**brainsOS-skills** is the decoupled skills, planning protocols, and operational discipline engine for **brainsOS.ai**.

It programmatically codifies, discovers, validates, and renders agent skills and planning archetypes across the brainsOS platform core, runtime runners (`brainsos-runner`), and pair-programming agents (Antigravity, Claude, LiteLLM).

---

## 📦 Features

- **Standardized Skill Schema**: Pydantic models for frontmatter metadata, triggers, procedural steps, and execution guidelines.
- **Canonical Planning Protocols**:
  - `plan`: Core Strategic Planning & 3-Step GitHub Epic Management ([`PLANNING.md`](../../PLANNING.md)).
  - `plan-design`: UI/UX Prototyping, Design Tokens & Live Mockup Alignment Protocol.
  - `plan-pr`: Developer Advocacy, Public Copy, Milestone Goals & README Positioning ("The PR Guy").
  - `agents-discipline`: Operational guardrails, zero-trust rules (Rules 1–14), and pre-commit review gates ([`AGENTS.md`](../../AGENTS.md)).
- **Multi-Runtime Exporting**:
  - Export to Antigravity Workspace Skills (`.agents/skills/`).
  - Render prompt injections for autonomous runners (`packages/brainsOS-runner`).
  - Human-auditable Open Knowledge Format (OKF) Markdown compliance.
- **CLI Utilities (`brainsos-skills`)**:
  - `brainsos-skills list`: Inspect all available skills and triggers.
  - `brainsos-skills validate`: Validate frontmatter and markdown structure against schemas.
  - `brainsos-skills sync`: Sync bundled canonical skills into the workspace `.agents/skills/` directory.

---

## 🚀 Quickstart

```python
from brainsos_skills import SkillRegistry, load_bundled_skills

# Discover and load all bundled canonical skills
registry = SkillRegistry()
load_bundled_skills(registry)

# Retrieve a specialized planning skill
design_skill = registry.get("plan-design")
print(design_skill.name)
print(design_skill.description)

# Render formatted prompt injection for agent runners
prompt_context = design_skill.render_context()
```

---

## 🛠️ CLI Usage

```bash
# List all registered skills
brainsos-skills list

# Validate workspace skills
brainsos-skills validate --path .agents/skills

# Sync bundled skills into active workspace
brainsos-skills sync --target .agents/skills
```
