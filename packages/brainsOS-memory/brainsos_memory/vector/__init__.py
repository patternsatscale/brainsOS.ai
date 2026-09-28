"""Vector storage & semantic search abstractions for brainsOS."""

from brainsos_memory.vector.base import SearchResult, VectorStore
from brainsos_memory.vector.null import NullVectorStore

__all__ = ["VectorStore", "SearchResult", "NullVectorStore"]
