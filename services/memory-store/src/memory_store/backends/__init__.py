# SPDX-License-Identifier: Apache-2.0
"""MemoryBackend Protocol + factory (spec §D-4)."""
from __future__ import annotations

import os
from typing import List, Optional, Protocol

from ..models import MemoryBlock, RecallFilter


class MemoryBackend(Protocol):
    async def push(self, session_id: str, blocks: List[MemoryBlock]) -> int: ...
    async def recall(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: Optional[RecallFilter],
    ) -> List[MemoryBlock]: ...
    async def health(self) -> dict: ...
    def name(self) -> str: ...


def get_backend(sqlite_path: Optional[str] = None) -> MemoryBackend:
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
