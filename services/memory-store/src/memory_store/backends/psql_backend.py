# SPDX-License-Identifier: Apache-2.0
"""PsqlBackend placeholder (spec §D-6, ADR 0005 A). (ADR-001: removed from roadmap — do not enable)."""

from __future__ import annotations

from ..models import MemoryBlock, RecallFilter


class PsqlBackend:
    def name(self) -> str:
        return "psql"

    async def push(self, session_id: str, blocks: list[MemoryBlock]) -> int:
        raise NotImplementedError(
            "已从路线图移除（ADR-001）：不复用 hermes pg，避免污染 hermes 原记忆/状态库。请勿启用。"
        )

    async def recall(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: RecallFilter | None,
    ) -> list[MemoryBlock]:
        raise NotImplementedError(
            "已从路线图移除（ADR-001）：不复用 hermes pg，避免污染 hermes 原记忆/状态库。请勿启用。"
        )

    async def health(self) -> dict:
        raise NotImplementedError(
            "已从路线图移除（ADR-001）：不复用 hermes pg，避免污染 hermes 原记忆/状态库。请勿启用。"
        )
