"""Memory-layer abstraction. Today's impl is SQLite FTS5 (db.py); future
swaps (Milvus, graph DB) implement the same protocol.

Captured per the 2026 "memory as a service" architectural pattern —
the storage layer should be replaceable without rewriting the agent
that reads from it.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class MemoryLayer(Protocol):
    """The contract every storage backend must satisfy. db.py is the
    reference implementation.

    All methods are read-only with respect to the vault — writes go
    through scripts that then call `reindex(force=True)` here.
    """

    def reindex(self, force: bool = False) -> dict:
        """Rebuild the index from the on-disk vault. Returns counts."""
        ...

    def search(
        self,
        terms: Iterable[str],
        scope: str | None = None,
        branch: str | None = None,
        limit: int = 20,
        offset: int = 0,
        include_invalidated: bool = False,
    ) -> tuple[list[dict], int]:
        """Full-text search → (page_of_rows, total_count)."""
        ...

    def get_file(self, rel_path: str) -> dict | None:
        """Read one note's full body + frontmatter-derived fields."""
        ...

    def list_recent(self, scope: str, limit: int = 10) -> list[dict]:
        """Scope-bounded recent-first listing."""
        ...

    def link_graph(self, rel_path: str) -> dict:
        """Wikilink edges for a path."""
        ...

    def status(self) -> dict:
        """Vault layout + db path + counts."""
        ...


def default_layer() -> MemoryLayer:
    """Return the active memory layer. Today: SQLite FTS5 via db.py."""
    import db
    return db
