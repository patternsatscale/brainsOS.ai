"""Vector storage & semantic search abstractions for Project Titan."""

from titan_memory.vector.base import SearchResult, VectorStore
from titan_memory.vector.null import NullVectorStore

__all__ = ["VectorStore", "SearchResult", "NullVectorStore"]
