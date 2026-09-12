# Project Titan: `titan-memory` (L5: Memory & Tools)

Welcome to the **Titan Memory Module**! This package is the single source of truth for knowledge representation, Open Knowledge Format (OKF) storage, memory purity enforcement, and vector indexing across Project Titan.

---

## 1. Architectural Boundaries (Inviolable Rules)

Any memory contribution must strictly observe two foundational rules:

### Rule 1: Memory Plane Purity (`/memories`)
* The `/memories` directory is **strictly reserved for human-auditable, flat Markdown files** (`.md`).
* **NEVER** write SQLite databases (`.db`), vector indexes, Python caches (`__pycache__`), or binary blobs directly inside `/memories`.
* Derived indices (e.g. Qdrant data, Chroma, LanceDB) must live in a separate data directory outside `/memories` or inside a dedicated container volume.

### Rule 7: Information Compartmentalization
* Persona prompts, notes, and memory tools must **never** leak backend infrastructure names (e.g. internal database connection strings, host sockets, daemon paths) into agent context.

---

## 2. Directory Layout & Extension Points

```text
titan_memory/
├── __init__.py          # Public API: OKFNote, OKFEngine, PurityGuard
├── okf/
│   ├── models.py        # OKFNote schema, YAML frontmatter parser & serializer
│   ├── purity.py        # Extension & path traversal validators (Rule 1)
│   └── engine.py        # OKFEngine for CRUD operations on notes & rule synthesis
├── vector/              # ◄── EXTENSION POINT: CONTRIBUTE VECTOR STORES HERE
│   ├── base.py          # Abstract VectorStore SPI (embed, upsert, query)
│   └── null.py          # NullVectorStore (default flat-markdown fallback)
└── tools/
    ├── registry.py      # Universal memory tools (read_okf_note, write_okf_note, synthesize_active_rules)
    └── hermes_adapter.py # Thin adapter for Hermes tool registry
tests/                   # Unit tests running instantly via pytest
├── test_models.py
├── test_purity.py
└── test_engine.py
```

---

## 3. Quickstart & Local Development

Run the test suite locally:
```bash
# In ProjectTitan root or packages/titan_memory:
pytest packages/titan_memory/tests
```

### Implementing a Vector Store (e.g. Qdrant / Chroma)
1. Subclass `titan_memory.vector.base.VectorStore` in `titan_memory/vector/qdrant.py`.
2. Implement:
   * `upsert_note(note: OKFNote) -> None`
   * `query(query_text: str, limit: int = 5) -> List[SearchResult]`
   * `delete_note(rel_path: str) -> None`
3. Add unit tests under `tests/test_vector.py`.
