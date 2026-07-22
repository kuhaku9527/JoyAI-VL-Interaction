# SPDX-License-Identifier: Apache-2.0
"""ObsidianBackend placeholder (spec §D-6)."""

from __future__ import annotations

from ..models import MemoryBlock, RecallFilter


class ObsidianBackend:
    def name(self) -> str:
        return "obsidian"

    async def push(self, session_id: str, blocks: list[MemoryBlock]) -> int:
        raise NotImplementedError("v0.3+ 落地")

    async def recall(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: RecallFilter | None,
    ) -> list[MemoryBlock]:
        raise NotImplementedError("v0.3+ 落地")

    async def health(self) -> dict:
        raise NotImplementedError("v0.3+ 落地")
