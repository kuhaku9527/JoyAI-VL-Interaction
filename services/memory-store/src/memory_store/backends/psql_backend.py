# SPDX-License-Identifier: Apache-2.0
"""PsqlBackend placeholder (spec §D-6, ADR 0005 A). (ADR-001: removed from roadmap — do not enable)."""

from __future__ import annotations

from ..models import MemoryBlock, RecallFilter


class PsqlBackend:
    """Intentional stub: psql reuse route cancelled per ADR-001.

    Reusing hermes pg was removed from the roadmap; enabling it would pollute
    the hermes memory/state database. All methods raise NotImplementedError.
    """

    def name(self) -> str:
        """Return the backend identifier ``"psql"``."""
        return "psql"

    async def push(self, session_id: str, blocks: list[MemoryBlock]) -> int:
        """Reject push: the psql backend is disabled per ADR-001."""
        raise NotImplementedError(
            "已从路线图移除(ADR-001):不复用 hermes pg,避免污染 hermes 原记忆/状态库。请勿启用。"
        )

    async def recall(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: RecallFilter | None,
    ) -> list[MemoryBlock]:
        """Reject recall: the psql backend is disabled per ADR-001."""
        raise NotImplementedError(
            "已从路线图移除(ADR-001):不复用 hermes pg,避免污染 hermes 原记忆/状态库。请勿启用。"
        )

    async def health(self) -> dict:
        """Reject health: the psql backend is disabled per ADR-001."""
        raise NotImplementedError(
            "已从路线图移除(ADR-001):不复用 hermes pg,避免污染 hermes 原记忆/状态库。请勿启用。"
        )
