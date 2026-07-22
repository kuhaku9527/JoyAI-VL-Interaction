# SPDX-License-Identifier: Apache-2.0
"""Pydantic models for memory-store v0.1 (spec §D-3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MemoryBlock(BaseModel):
    block_id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex)
    session_id: str | None = None
    content: str
    score: float = 1.0
    created_at: datetime | None = None
    last_hit_at: datetime | None = None
    hit_count: int = 0


class PushRequest(BaseModel):
    session_id: str
    blocks: list[MemoryBlock]


class PushResponse(BaseModel):
    pushed: int
    session_id: str


class RecallFilter(BaseModel):
    session_ids: list[str] | None = None
    created_after: datetime | None = None


class RecallRequest(BaseModel):
    query: str
    top_k: int = 8
    min_score: float = 0.3
    filter: RecallFilter | None = None


class RecallResponse(BaseModel):
    blocks: list[MemoryBlock]
