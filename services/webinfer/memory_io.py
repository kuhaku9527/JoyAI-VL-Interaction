"""Memory I/O mixin: memory-store warmup/recall/push and qa_history archive.

Defines :class:`MemoryIOMixin`, which carries the memory-store read/write
hooks and the qa_history text-path archive helpers previously on
``StreamingInferAdapter``.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from adapter_types import SessionState
from response_format import archive_chunk_response_records

LOGGER = logging.getLogger("streaming_infer_adapter")


class MemoryIOMixin:
    """Memory-store read/write and qa_history archive."""

    # -------------------------------------------------------------------
    # Memory-store v0.2 hooks (live adapter spec D-9).
    # All hooks are no-ops if the memory_store client is disabled or
    # unreachable; the adapter never blocks the main request path on them.
    # -------------------------------------------------------------------
    async def _memory_warmup(self, state):
        """Pull blocks for this session from memory-store and cache.

        Safe to call concurrently for the same session -- only the first
        result is kept. The completion signal is an ``asyncio.Event`` that is
        set ONLY after the cache has actually been filled, so concurrent
        callers never observe a "warmed" state with an empty cache (#4).
        On failure the event is left unset, making the warmup retryable
        instead of permanently degrading to a dead cache.
        """
        if state._memory_warmed.is_set():
            return
        # Hold the session lock across the (slow) warmup await so concurrent
        # warmups/reads serialize: the first caller pulls once and sets the
        # event, the rest see it already set and return. asyncio.Lock is not
        # reentrant, so callers must not hold state.lock when invoking this.
        async with state.lock:
            if state._memory_warmed.is_set():
                return
            try:
                blocks = await self.memory_store.warmup(state.session_id)
            except Exception as exc:
                LOGGER.warning("memory warmup failed for %s: %s", state.session_id, exc)
                return
            if blocks:
                state._memory_block_cache = blocks
                LOGGER.info(
                    "memory warmup %s: pulled %d block(s)",
                    state.session_id,
                    len(blocks),
                )
            state._memory_warmed.set()

    async def _memory_recall(self, state, question):
        """Per-question recall. Uses warmup cache; warms up if needed.

        The first question a Pilot asks may arrive before the warmup task
        finished (fire-and-forget on session create). In that case we wait
        briefly for the warmup so the first answer benefits from previous
        session memory without a separate round-trip.
        """
        if not question:
            async with state.lock:
                return list(state._memory_block_cache)
        if not state._memory_warmed.is_set():
            # warmup takes the lock internally; we must NOT hold it here to
            # avoid reentrancy deadlock on the non-reentrant asyncio.Lock.
            await self._memory_warmup(state)
        # v0.1 spec skips per-question rerank -- the cache is the answer.
        # v0.3+ may add per-question hot-fetch against the live query.
        async with state.lock:
            return list(state._memory_block_cache)

    async def _memory_push(self, state):
        """Push session memory blocks to memory-store at session end.

        Concatenates ``mid_term_summaries`` (skeleton entries) and
        ``long_term_history`` (compressed batch texts) into a single push.
        Idempotent: repeated calls return 0 the second time.
        """
        if state._memory_pushed or not self.memory_store.is_enabled:
            return 0
        state._memory_pushed = True
        blocks = []
        for entry in state.mid_term_summaries or []:
            if not isinstance(entry, dict):
                continue
            text = entry.get("summary_text") or entry.get("text") or ""
            if not text:
                continue
            blocks.append({"content": text, "score": 1.0})
        for entry in state.long_term_history or []:
            if not isinstance(entry, dict):
                continue
            text = entry.get("compressed_text") or ""
            if not text:
                continue
            blocks.append({"content": text, "score": 1.0})
        if not blocks:
            return 0
        try:
            pushed = await self.memory_store.push(state.session_id, blocks)
        except Exception as exc:
            LOGGER.warning("memory push failed for %s: %s", state.session_id, exc)
            return 0
        if pushed:
            LOGGER.info("memory push %s: persisted %d block(s)", state.session_id, pushed)
        return pushed

    def _update_text_qa_history(
        self,
        state: SessionState,
        api_messages: list[dict[str, Any]],
        clean_text: str,
        decision: str,
    ) -> None:
        # Append the latest user/assistant pair to the session qa_history
        # so subsequent calls inherit the same context. Deliberately
        # ignores system messages and tool-style payloads; only the
        # last user turn is recorded (matches existing helper behaviour).
        if not self.config.keep_qa_history:
            return
        last_user_text = ""
        for message in reversed(api_messages):
            if message.get("role") == "user" and isinstance(message.get("content"), str):
                last_user_text = message["content"]
                break
        if not last_user_text:
            return
        qa_history = state.memory_state.setdefault("qa_history", [])
        now_iso = datetime.fromtimestamp(time.time()).isoformat(timespec="seconds")
        existing = None
        for entry in qa_history:
            if entry.get("query") == last_user_text and entry.get("query_time") == now_iso:
                existing = entry
                break
        if existing is None:
            qa_history.append(
                {
                    "query_time": now_iso,
                    "query": last_user_text,
                    "responses": [{"prediction": clean_text, "decision": decision}],
                    "archived_in_chunk": None,
                    "text_path": True,
                }
            )
        else:
            existing.setdefault("responses", []).append(
                {"prediction": clean_text, "decision": decision}
            )

        # Bound qa_history the same way long_term_history is bounded (upstream PR #25
        # root cause 1): without this, every session eventually overflows the main
        # model context window regardless of max_model_len.
        window = int(self.config.qa_history_window or 0)
        if window > 0 and len(qa_history) > window:
            del qa_history[: len(qa_history) - window]

    def _execute_pending_qa_archive(self, state: SessionState) -> None:
        if state._pending_qa_archive is None:
            return
        old_query, old_start_time = state._pending_qa_archive
        archive_chunk_response_records(
            state.current_chunk,
            state.memory_state,
            old_query,
            old_start_time,
            chunk_index=state.chunk_index,
        )
        state.current_chunk["response_records"] = []
        state._pending_qa_archive = None
