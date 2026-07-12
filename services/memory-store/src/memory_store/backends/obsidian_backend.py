# SPDX-License-Identifier: Apache-2.0
"""ObsidianBackend placeholder (spec §D-6)."""
from __future__ import annotations

from typing import List, Optional

from ..models import MemoryBlock, RecallFilter


class ObsidianBackend:
    def name(self) -> str:
        return "obsidian"

    async def push(self, session_id: str, blocks: List[MemoryBlock]) -> int:
        raise NotImplementedError("v0.3+ 落地")

    async def recall(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: Optional[RecallFilter],
    ) -> List[MemoryBlock]:
        raise NotImplementedError("v0.3+ 落地")

    async def health(self) -> dict:
        raise NotImplementedError("v0.3+ 落地")
