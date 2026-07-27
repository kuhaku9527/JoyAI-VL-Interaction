# SPDX-License-Identifier: Apache-2.0
"""ObsidianBackend placeholder (spec §D-6)."""

from __future__ import annotations

from ..models import MemoryBlock, RecallFilter


class ObsidianBackend:
    """Placeholder backend for the planned Obsidian vault integration (spec §D-6)."""

    def name(self) -> str:
        """Return the backend identifier ``"obsidian"``."""
        return "obsidian"

    async def push(self, session_id: str, blocks: list[MemoryBlock]) -> int:
        """Reject push: Obsidian backend is not implemented yet (planned v0.3+)."""
        raise NotImplementedError("v0.3+ 落地")

    async def recall(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: RecallFilter | None,
    ) -> list[MemoryBlock]:
        """Reject recall: Obsidian backend is not implemented yet (planned v0.3+)."""
        raise NotImplementedError("v0.3+ 落地")

    async def health(self) -> dict:
        """Reject health: Obsidian backend is not implemented yet (planned v0.3+)."""
        raise NotImplementedError("v0.3+ 落地")
