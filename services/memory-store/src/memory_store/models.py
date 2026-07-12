# SPDX-License-Identifier: Apache-2.0
"""Pydantic models for memory-store v0.1 (spec §D-3)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class MemoryBlock(BaseModel):
    block_id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex)
    session_id: str
    content: str
    score: float = 1.0
    created_at: datetime
    last_hit_at: Optional[datetime] = None
    hit_count: int = 0


class PushRequest(BaseModel):
    session_id: str
    blocks: List[MemoryBlock]


class PushResponse(BaseModel):
    pushed: int
    session_id: str


class RecallFilter(BaseModel):
    session_ids: Optional[List[str]] = None
    created_after: Optional[datetime] = None


class RecallRequest(BaseModel):
    query: str
    top_k: int = 8
    min_score: float = 0.3
    filter: Optional[RecallFilter] = None


class RecallResponse(BaseModel):
    blocks: List[MemoryBlock]
