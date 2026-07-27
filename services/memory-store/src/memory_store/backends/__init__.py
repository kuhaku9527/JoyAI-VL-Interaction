# SPDX-License-Identifier: Apache-2.0
"""MemoryBackend Protocol + factory (spec §D-4)."""

from __future__ import annotations

import os
from typing import Protocol

from ..models import MemoryBlock, RecallFilter


class MemoryBackend(Protocol):
    """Storage backend contract implemented by sqlite/psql/obsidian backends."""

    async def push(self, session_id: str, blocks: list[MemoryBlock]) -> int:
        """Persist a batch of memory blocks; returns the number stored."""
        ...

    async def recall(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: RecallFilter | None,
    ) -> list[MemoryBlock]:
        """Return the top-k memory blocks matching ``query`` under ``flt``."""
        ...

    async def health(self) -> dict:
        """Return a readiness/health snapshot for the backend."""
        ...

    def name(self) -> str:
        """Return the backend identifier name."""
        ...


def get_backend(sqlite_path: str | None = None) -> MemoryBackend:
    """Instantiate the configured storage backend (sqlite by default)."""
    name = os.getenv("MEMORY_BACKEND", "sqlite").lower()
    if name == "sqlite":
        from .sqlite_backend import SqliteBackend

        return SqliteBackend(sqlite_path or os.getenv("MEMORY_SQLITE_PATH", "./data/memory.sqlite"))
    if name == "psql":
        from .psql_backend import PsqlBackend

        return PsqlBackend()
    if name == "obsidian":
        from .obsidian_backend import ObsidianBackend

        return ObsidianBackend()
    raise ValueError(f"unknown backend: {name}")
