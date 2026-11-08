---
id: 04-readable-memory-git
from_name: Memory Librarian
from_user: librarian
reply_to_user: bawtford
subject: 📚 No Black-Box Databases Allowed: Readable Memory & Git Time Travel
preheader: Why pure Markdown in /memories and local Gitea version control keep humans in full command.
badge: RULE 1 & RULE 14 // AUDITABLE KNOWLEDGE PLANE
accent: #f97316
footer: Memory Librarian (librarian@{local_domain}) • Rule 1 Memory Plane Purity enforced
age_minutes: 12
---

# 📚 No Black-Box Databases Allowed

Greetings from the stacks, **{user}**!

I am the **Memory Librarian** (`librarian@{local_domain}`), guardian of **Rule 1: Memory Plane Purity**. If an AI agent tries to sneak an opaque SQLite `.db` file, a binary vector index, or a `node_modules` folder into `/memories`, I chase it out with a broom.

## Why Plain Markdown Beats Black-Box Databases

When an agent stores its knowledge in a proprietary vector blob, you cannot read what it "knows" or fix a hallucinated memory without wiping the whole database. In **brainsOS**, every agent persona (`SOUL.md`) and long-term memory (`/memories/*.md`) is pure, human-auditable Open Knowledge Format (OKF) Markdown.

1. **Readable Memory — [Code Console]({base_url}/editor/) (`Alt+6`):** Press `Alt+6` (or click the Code Console icon on the left spine) to open the built-in VS Code Web IDE. You can browse `data/agents/`, tweak **Bawtford**'s `SOUL.md` persona for **Cindy Pawford**, or edit `/memories` notes in real time—zero container rebuilds required!
2. **Source Control — [Git Server]({base_url}/git/) (`Alt+7`):** Press `Alt+7` (or click the Git icon) to open your local Gitea server. Every persona update, fleet manifest change (`agents.yaml`), and Markdown memory commit is versioned so you can inspect diffs and time-travel (`git revert`) whenever an agent gets a little too poetic.
3. **Editable Welcome Emails (`config/default_emails/*.md`):** Even these 5 onboarding emails live in clean Markdown files that you can customize anytime!

```text
data/agents/bawtford/
├── SOUL.md                  # Bawtford's persona & "Talk to the Paw" rules
├── memories/                # Rule 1: Pure OKF Markdown notes & logs only
├── workspace/               # Isolated agent scratchpad & runtime state
└── apps/cindypawford/       # Cindy Pawford's web showcase & assets
```

> [!TIP] Librarian's Challenge
> Open the [Code Console]({base_url}/editor/) (`Alt+6`), inspect `SOUL.md` for `bawtford`, and see how his role as Chief Paw-ficer to **Cindy Pawford** is defined in plain Markdown!
