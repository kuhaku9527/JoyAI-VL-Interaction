# SPDX-License-Identifier: Apache-2.0
"""PsqlBackend placeholder (spec §D-6, ADR 0005 A)."""
from __future__ import annotations

from typing import List, Optional

from ..models import MemoryBlock, RecallFilter


class PsqlBackend:
    def name(self) -> str:
        return "psql"

    async def push(self, session_id: str, blocks: List[MemoryBlock]) -> int:
        raise NotImplementedError("待 Phase B：复用 hermes-agent pg 实例")

    async def recall(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: Optional[RecallFilter],
    ) -> List[MemoryBlock]:
        raise NotImplementedError("待 Phase B：复用 hermes-agent pg 实例")

    async def health(self) -> dict:
        raise NotImplementedError("待 Phase B：复用 hermes-agent pg 实例")
