"""Default no-op vector store fallback (pure flat-file Markdown mode)."""

from __future__ import annotations

from brainsos_memory.okf.models import OKFNote
from brainsos_memory.vector.base import SearchResult, VectorStore


class NullVectorStore(VectorStore):
    """Default no-op implementation when external vector DB is not configured."""

    def upsert_note(self, note: OKFNote) -> None:
        pass

    def query(self, query_text: str, limit: int = 5, category: str | None = None) -> list[SearchResult]:
        return []

    def delete_note(self, rel_path: str) -> None:
        pass
