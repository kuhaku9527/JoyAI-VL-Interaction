"""Memory I/O mixin: memory-store warmup/recall/push and qa_history archive.

Defines :class:`MemoryIOMixin`, which carries the memory-store read/write
hooks and the qa_history text-path archive helpers previously on
``StreamingInferAdapter``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any

from adapter_types import SessionState
from response_format import archive_chunk_response_records

# --- ADR-0014 JSONL event emission (services/common/event_json.py) ----------
try:

    def _ensure_event_json_importable() -> None:
        """Put ``services/common`` on ``sys.path`` by walking up from this file.

        Returns without inserting if the shared emitter cannot be located;
        the subsequent import then raises ImportError, which is caught below
        and downgraded to a logged no-op (约法三章: not silent, just not fatal).
        """
        here = os.path.dirname(os.path.abspath(__file__))
        cur = here
        while True:
            common = os.path.join(cur, "services", "common")
            if os.path.exists(os.path.join(common, "event_json.py")):
                if common not in sys.path:
                    sys.path.insert(0, common)
                return
            parent = os.path.dirname(cur)
            if parent == cur:
                return
            cur = parent

    _ensure_event_json_importable()
    from event_json import emit_event
except ImportError:
    logging.getLogger(__name__).warning(
        "event_json emitter unavailable; JSONL event emission disabled "
        "(packaged build without services/common on path?)"
    )

    def emit_event(*_args, **_kwargs):
        """No-op fallback used only when the shared emitter is unavailable.

        Logged once above (not silent) per 约法三章 - never swallow the failure.
        """
        return None


LOGGER = logging.getLogger("streaming_infer_adapter")

# ---------------------------------------------------------------------------
# Local Wiki live-recall (ADR-0012 §6, integration analysis 2026-07-28).
# ---------------------------------------------------------------------------
# These defaults are read on every chat turn from the inherited
# ``StreamingInferAdapter.config``; the env vars are the deployment override.
# Operators can shrink the recall set per deployment by setting
# ``WIKI_RECALL_NAMESPACES="wiki:elden-ring,wiki:hl2"`` — GLobs (``wiki:*``)
# are expanded by the memory-store backend.
_WIKI_DEFAULTS = {
    "namespaces": ["wiki:*"],
    "top_k": 5,
    "min_score": 0.0,
    "enabled": True,
}


def _wiki_settings(config) -> dict[str, Any]:
    """Resolve wiki recall settings from config (with env fallback)."""
    enabled = _config_or_env(
        config,
        "WIKI_RECALL_ENABLED",
        default=_WIKI_DEFAULTS["enabled"],
        cast=_to_bool,
    )
    namespaces = _config_or_env(
        config,
        "WIKI_RECALL_NAMESPACES",
        default=_WIKI_DEFAULTS["namespaces"],
        cast=_parse_namespaces,
    )
    top_k = _config_or_env(
        config,
        "WIKI_RECALL_TOP_K",
        default=_WIKI_DEFAULTS["top_k"],
        cast=int,
    )
    min_score = _config_or_env(
        config,
        "WIKI_RECALL_MIN_SCORE",
        default=_WIKI_DEFAULTS["min_score"],
        cast=float,
    )
    return {
        "enabled": enabled,
        "namespaces": namespaces,
        "top_k": max(1, int(top_k)),
        "min_score": float(min_score),
    }


def _config_or_env(config, env_name: str, *, default, cast):
    """Pick a config attribute (if present) else fall back to the env / default.

    Env wins over config when both are set — operators can override from
    the deployment without touching the adapter config.
    """
    config_value = None
    if config is not None and hasattr(config, env_name.lower()):
        try:
            config_value = cast(getattr(config, env_name.lower()))
        except (TypeError, ValueError):
            config_value = None
    raw = os.environ.get(env_name)
    if raw is None:
        return (
            config_value
            if config_value is not None
            else (cast(default) if not isinstance(default, list) else list(default))
        )
    return cast(raw)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def _parse_namespaces(raw: Any) -> list[str]:
    """Accept either a list (typed config) or a comma-separated string (env).

    The list branch is the no-op fast path; the string branch handles the
    ``WIKI_RECALL_NAMESPACES="wiki:a,wiki:b"`` deployment form.
    """
    if isinstance(raw, list):
        return [str(s).strip() for s in raw if str(s).strip()]
    text = str(raw)
    if text.startswith("[") and text.endswith("]"):
        # Tolerate a stringified list (``"['wiki:a','wiki:b']"``) — happens
        # when the config field is itself a list that gets str()-ed by env.
        inner = text[1:-1]
        return [s.strip().strip("'\"") for s in inner.split(",") if s.strip()]
    return [s.strip() for s in text.split(",") if s.strip()]


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

        ADR-0012 §6 live recall (2026-07-28): in addition to the warmup cache,
        a per-question Local Wiki semantic recall is fired in parallel. The
        result is stashed on ``state._memory_wiki_cache`` so the prompt
        builder can render it as a separate ``[Local Wiki]`` section. The
        wiki call is fail-open: any error is logged and the chat goes on
        with chat memory only.
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
            chat_blocks = list(state._memory_block_cache)
        # Local Wiki live recall (separate from chat memory) — see
        # reports/local-wiki-chat-integration-analysis-20260728.md.
        # Fire-and-forget: do NOT block the chat path on memory-store.
        # The first request after a session start may miss wiki content,
        # but subsequent calls in the same session will see the populated
        # ``_memory_wiki_cache``. Rationale: wiki recall is enrichment,
        # not a blocker; awaiting it inline added up to 5s per chat turn
        # when memory-store was slow/dead (DRIFT-2/D-022 in 决策/).
        self._schedule_wiki_recall(state, question)
        return chat_blocks

    def _schedule_wiki_recall(self, state, question: str) -> None:
        """Schedule a fire-and-forget Local Wiki recall.

        The task updates ``state._memory_wiki_cache`` on success; the
        next ``_memory_recall`` call (or the prompt builder) reads it.
        Errors are logged and swallowed — the chat path must not raise.
        """
        if not question:
            return

        async def _runner() -> None:
            try:
                wiki_blocks = await self._memory_wiki_recall(state, question)
            except Exception as exc:  # fail-open: never raise
                emit_event(
                    "webinfer",
                    "wiki_recall_fail",
                    level="warn",
                    session_id=state.session_id,
                    extra={"error_type": type(exc).__name__, "context": "background_schedule"},
                )
                LOGGER.warning(
                    "wiki background recall failed for %s: %s",
                    state.session_id,
                    exc,
                )
                return
            if wiki_blocks:
                async with state.lock:
                    state._memory_wiki_cache = list(wiki_blocks)

        try:
            task = asyncio.create_task(_runner())
        except RuntimeError:
            # No running loop (e.g. unit-test with no event loop) — skip.
            return
        # Track the task on state so it is not GCed before completion
        # and so the session lifecycle can await it on shutdown.
        existing = getattr(state, "_memory_wiki_tasks", None)
        if existing is not None:
            existing.add(task)
            task.add_done_callback(existing.discard)

    async def _memory_wiki_recall(self, state, question: str) -> list[dict[str, Any]]:
        """Per-question Local Wiki semantic recall.

        Fail-open: any error logs a warning and returns [] so the chat never
        blocks on wiki.
        """
        settings = _wiki_settings(getattr(self, "config", None))
        if not settings["enabled"]:
            return []
        client = getattr(self, "memory_store", None)
        if client is None or not bool(
            getattr(client, "is_enabled", getattr(client, "enabled", False))
        ):
            return []
        try:
            blocks = await client.recall(
                question,
                top_k=settings["top_k"],
                min_score=settings["min_score"],
                namespaces=settings["namespaces"],
            )
        except Exception as exc:  # fail-open: never raise, but report loudly (约法三章)
            emit_event(
                "webinfer",
                "wiki_recall_fail",
                level="error",
                session_id=state.session_id,
                extra={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "query_chars": len(question or ""),
                },
            )
            LOGGER.warning(
                "local-wiki recall failed: type=%s msg=%s query=%r",
                type(exc).__name__,
                exc,
                question,
            )
            # Marker so the caller can distinguish "no hit" from "errored"
            # (fail-open: the chat path still gets [] and carries on).
            state._memory_wiki_error = True
            return []
        emit_event(
            "webinfer",
            "wiki_recall",
            level="info",
            session_id=state.session_id,
            extra={"blocks": len(blocks)},
        )
        # Latest recall succeeded (or legitimately returned empty) — clear the
        # error marker so the caller's distinction stays accurate.
        state._memory_wiki_error = False
        # The wiki recall goes through the namespace filter at the backend
        # level — see ``MemoryStoreClient.recall``'s ``session_id`` arg and
        # ``/v1/blocks/recall``'s ``filter.namespaces`` field. When the
        # session_id is None we ask the client to scope explicitly.
        if not blocks:
            return []
        # Tag every block so the renderer can render them as a separate wiki
        # section. The backend already populates ``namespace`` / ``source_url``
        # (memory-store PR #36 schema); we only stamp the source marker.
        for b in blocks:
            if isinstance(b, dict):
                b.setdefault("source", "wiki")
        return blocks

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
