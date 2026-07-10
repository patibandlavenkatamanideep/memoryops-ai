"""Pluggable vector-search backends (v1.7, ADR-021).

The vector index is the one store-specific part of retrieval; the authoritative
`Repository` keeps governed state. Every backend upholds the same contract:
tenant isolation, deletion, and no governance bypass. See `base.py`.
"""

from __future__ import annotations

from .base import VectorIndex, VectorMatch
from .factory import create_vector_index
from .memory_index import InMemoryVectorIndex

__all__ = ["VectorIndex", "VectorMatch", "InMemoryVectorIndex", "create_vector_index"]
