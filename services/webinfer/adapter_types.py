# ruff: noqa: RUF003
"""Dataclass definitions shared across the webinfer adapter (AdapterConfig, SessionState)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prompt_constants import DEFAULT_SYSTEM_PROMPT_EN

from config import reset_chunk_state

LOGGER = logging.getLogger("streaming_infer_adapter")


class ReentrantAsyncLock:
    """Asyncio lock that permits re-entrancy from the same task.

    ``asyncio.Lock`` is strictly non-reentrant: a coroutine that already
    holds the lock will deadlock if it attempts to acquire it again. The
    memory hooks (``memory_io._memory_warmup`` / ``_memory_recall``) acquire
    ``SessionState.lock`` internally, while ``handle_text_chat`` holds that
    same lock across the entire ``_handle_text_payload`` call -- including
    the ``_memory_recall`` invocation. On the text-chat path this produced a
    self-deadlock that hung the request forever (CI ``pytest (webinfer)``
    stalled for >= 55 min).

    This wrapper allows the *owning* task (identified via
    ``asyncio.current_task()``) to re-enter without blocking, while still
    serialising distinct tasks through the underlying ``asyncio.Lock``. It
    therefore fixes the deadlock without dropping any of the existing lock
    coverage -- concurrent requests on the same session remain mutually
    exclusive, so no new data race is introduced.

    Note: like ``asyncio.Lock``, if a task holding the lock is cancelled
    mid-acquire (depth > 1) the underlying lock may stay held and
    ``_owner`` points at a dead task, blocking later acquirers. Current
    call sites use ``async with`` and run to completion, so this is not
    exercised in practice; long-held lock sections would need explicit
    cancellation handling.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task | None = None
        self._depth = 0

    async def __aenter__(self) -> ReentrantAsyncLock:
        """Acquire the lock on context entry (re-entrant for the owning task)."""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Release one level of lock ownership on context exit."""
        self.release()

    async def acquire(self) -> bool:
        """Acquire the lock, allowing re-entry by the current task.

        Returns ``True`` once acquired, matching ``asyncio.Lock.acquire``.
        """
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("ReentrantAsyncLock must be used inside an asyncio task")
        if self._owner is task:
            self._depth += 1
            return True
        await self._lock.acquire()
        self._owner = task
        self._depth = 1
        return True

    def release(self) -> None:
        """Release one level of lock ownership.

        Only the owning task may release. A release attempted by any other
        task is forwarded to the underlying ``asyncio.Lock.release``: that
        raises ``RuntimeError`` only when the underlying lock is not currently
        held, and would silently release the owner's lock when it is -- so a
        non-owner release is unsupported, not a safe misuse check. Always
        release from the owning task.
        """
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("ReentrantAsyncLock must be used inside an asyncio task")
        if self._owner is task:
            self._depth -= 1
            if self._depth <= 0:
                self._owner = None
                self._depth = 0
                self._lock.release()
            return
        # Not the owner: forward to the underlying lock. Raises RuntimeError
        # only when the underlying lock is free; if the owner holds it this
        # silently releases the owner's lock, so non-owner release is unsupported.
        self._lock.release()

    def locked(self) -> bool:
        """Return True if held by any task (owner set or underlying lock acquired)."""
        return self._owner is not None or self._lock.locked()


@dataclass
class AdapterConfig:
    """Runtime configuration for the streaming-inference adapter service."""

    host: str = "127.0.0.1"
    port: int = 8070
    adapter_model: str = "streaming-infer-adapter"
    main_api_base: str = "http://127.0.0.1:7060/v1"
    main_model: str = "streamingharness-8b"
    main_backends: tuple[dict[str, str], ...] = ()
    api_key: str = "EMPTY"
    allowed_local_image_roots: tuple[str, ...] = ()
    frame_seconds: float = 1.0
    max_pixels: int = 262144
    main_max_tokens: int = 128
    # v3.34: llama-server -c context window (sync with run-windows.env MAIN_CTX_TOKENS).
    # Visual pipeline + 3-layer memory + accumulated turns can blow past it.
    # webinfer estimates total chars in _build_main_http_messages and trims the
    # oldest user/assistant turns when the budget (main_ctx_tokens * 3 chars * 0.85)
    # is exceeded.
    main_ctx_tokens: int = 16384
    main_temperature: float = 0.8
    main_top_p: float = 0.9
    main_top_k: int = 40
    main_repetition_penalty: float = 1.0
    main_presence_penalty: float = 0.0
    honor_inbound_generation_params: bool = False
    chunk: int = 200
    compress_every_n_chunks: int = 5
    async_summary_lead_frames: int = 10
    use_prompt_as_query: bool = True
    force_silence_before_query: bool = True
    keep_qa_history: bool = True
    qa_history_window: int = 12  # 0 = 禁用(旧无界行为)；保留最近 N 轮问答
    normalize_output: bool = True
    enable_summarizer: bool = True
    summarizer_model: str = "/tmp/models/Qwen3-VL-4B-Instruct"  # noqa: S108
    summarizer_api_base: str = "http://127.0.0.1:8065/v1"
    longterm_model: str = "/tmp/models/Qwen3-VL-4B-Instruct"  # noqa: S108
    longterm_api_base: str = "http://127.0.0.1:8065/v1"
    summarizer_max_pixels: int = 262144
    summarizer_key_frames: int = 0
    summarizer_phase_seconds: float = 10.0
    mid_term_max_tokens: int = 4000
    mid_term_target_tokens: int = 3000
    long_term_max_tokens: int = 2000
    long_term_target_tokens: int = 1000
    mid_term_temperature: float = 0.8
    mid_term_top_p: float = 0.9
    mid_term_top_k: int = 40
    mid_term_repetition_penalty: float = 1.1
    mid_term_presence_penalty: float = 0.0
    long_term_temperature: float = 1.0
    long_term_top_p: float = 1.0
    long_term_top_k: int = 80
    long_term_repetition_penalty: float = 1.1
    long_term_presence_penalty: float = 0.0
    long_term_memory_window: int = 40
    long_term_memory_max_tokens: int = 1800  # 0 = 禁用；重建 long_term_memory 的累计 token 预算
    request_timeout_seconds: float = 300.0
    session_timeout_seconds: float = 3600.0
    out_dir: str | None = None
    light_out_dir: str | None = None
    debug_input_dir: str | None = None
    save_root: str | None = None
    output_model_name: str = ""
    per_session_dirs: bool = True
    save_model_inputs: bool = True
    save_debug_inputs: bool = False
    summarizer_debug: bool = False
    frame_save_dir: str = "/tmp/streaming_adapter_frames"  # noqa: S108
    language: str = "en"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT_EN
    character_prompts_enabled: bool = True
    character_prompt_paths: tuple[str, ...] = ()
    memory_store_url: str = "http://127.0.0.1:8996"
    memory_store_enabled: bool = True


@dataclass
class SessionState:
    """Per-session mutable state for the streaming-inference adapter."""

    session_id: str
    lock: ReentrantAsyncLock = field(default_factory=ReentrantAsyncLock)
    frame_count: int = 0
    turn_count: int = 0
    chunk_index: int = 1
    current_chunk: dict[str, Any] = field(default_factory=reset_chunk_state)
    memory_state: dict[str, Any] = field(
        default_factory=lambda: {"long_term_memory": "", "qa_history": []}
    )
    current_query_text: str | None = None
    query_start_time: str | None = None
    query_in_current_chunk: bool = False
    mid_term_summaries: list[dict[str, Any]] = field(default_factory=list)
    mid_term_history: list[dict[str, Any]] = field(default_factory=list)
    long_term_history: list[dict[str, Any]] = field(default_factory=list)
    long_term_compression_next_index: int = 1
    async_summary_segment: dict[str, Any] = field(default_factory=reset_chunk_state)
    async_next_summary_target_turns: int = 0
    async_next_summary_index: int = 1
    async_pending_summary_jobs: list[dict[str, Any]] = field(default_factory=list)
    predictions: list[dict[str, Any]] = field(default_factory=list)
    session_started_at: float = field(default_factory=time.time)
    output_path: Path | None = None
    light_output_path: Path | None = None
    debug_input_dir: Path | None = None
    session_out_dir: str | None = None
    session_light_out_dir: str | None = None
    session_frame_dir: Path | None = None
    session_frame_counter: int = 0
    chunk_start_input_saved: set[int] = field(default_factory=set)
    last_access: float = field(default_factory=time.time)
    _pending_qa_archive: tuple[str, str | None] | None = field(default=None, repr=False)
    _pending_write_task: asyncio.Task | None = field(default=None, repr=False)
    # Memory-store v0.2 fields (live adapter spec D-9):
    _memory_block_cache: list = field(default_factory=list)
    # Local Wiki live-recall cache (ADR-0012 §6, integration analysis 2026-07-28).
    # Populated on every chat turn via ``MemoryIOMixin._memory_recall``; read
    # by ``PromptAssemblyMixin._build_memory_prompt`` so the model sees
    # looked-up reference material in a separate [Local Wiki] section.
    _memory_wiki_cache: list = field(default_factory=list)
    _memory_warmed: asyncio.Event = field(default_factory=asyncio.Event)
    _memory_pushed: bool = False
    _memory_warmup_task: asyncio.Task | None = field(default=None, repr=False)
