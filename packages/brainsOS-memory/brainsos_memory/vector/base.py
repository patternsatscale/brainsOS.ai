"""Abstract base class for brainsOS vector storage and semantic search."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from brainsos_memory.okf.models import OKFNote


@dataclass
class SearchResult:
    """Represents a vector or hybrid search result."""

    rel_path: str
    title: str
    score: float
    snippet: str
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(ABC):
    """Abstract VectorStore interface for memory indexing & retrieval."""

    @abstractmethod
    def upsert_note(self, note: OKFNote) -> None:
        """Embed and upsert note into vector index."""

    @abstractmethod
    def query(self, query_text: str, limit: int = 5, category: str | None = None) -> list[SearchResult]:
        """Query vector index for semantically similar notes."""

    @abstractmethod
    def delete_note(self, rel_path: str) -> None:
        """Remove note embedding from index."""
