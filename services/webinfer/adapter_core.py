"""Core StreamingInferAdapter: orchestrates the real-time video-language interaction loop."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from adapter_types import AdapterConfig, SessionState
from aiohttp import web
from config import reset_chunk_state
from io_utils import (
    _extract_extra_body,
    _file_to_data_url_cached,
    _internal_message_to_openai,
    derive_light_out_dir,
    sanitize_output_name,
)
from memory_store_client import MemoryStoreClient
from memory_summarizer import SummarizerModel
from openai import AsyncOpenAI
from prompt_building import (
    _build_system_prompt,
    _compute_prompt_guard_max_chars,
    _estimate_messages_chars,
    _get_i18n,
    _trim_messages_to_ctx,
    build_dynamic_system_content,
    build_static_system_content,
)
from request_parsing import (
    _extract_all_image_refs,
    _extract_time_range_from_request,
    _extract_time_ranges_from_request,
    _extract_user_prompt_text,
    _read_json,
    _request_session_id,
    _safe_session_id,
)
from response_format import (
    _chat_completion_response,
    _openai_error_response,
    _parse_decision_tokens,
    _short,
    archive_chunk_response_records,
    build_model_input_record,
    extract_response_payload,
    normalize_model_output,
)
from system_prompts import (
    compose_system_prompt_with_memory,
    load_character_prompts,
    resolve_prompt_paths,
)
from time_ranges import (
    _compute_chunk_frame_range,
    _extract_time_range_from_text,
    _format_batch_time_marker,
    _format_turn_time_range,
    _get_response_frame_indices,
    _parse_start_second,
    _strip_time_range_from_text,
)

LOGGER = logging.getLogger("streaming_infer_adapter")
USER_QUERY_HEADER_EN = "[User Query (IMPORTANT — follow this instruction)]"
USER_QUERY_HEADER_ZH = "[用户问题（重要——请遵循此指令）]"
VIDEO_HISTORY_HEADER_EN = (
    "[Video History]\n"
    "The following are summaries of earlier video segments you can no longer see. "
    "Use them as background context, but always prioritize the current visual frames "
    "and the User Query below when making decisions.\n"
    "IMPORTANT: These summaries are written by an external system in a descriptive style. "
    "Do NOT imitate their writing style in your responses.\n"
)
VIDEO_HISTORY_HEADER_ZH = (
    "[Video History]\n"
    "以下是你已无法看到的早期视频片段的文字摘要。"
    "将其作为背景上下文使用，但在做决策时始终优先参考当前视觉帧及下方的用户问题。\n"
    "重要：这些摘要由外部系统以描述性风格撰写。不要在你的回复中模仿其写作风格。\n"
)
QA_HISTORY_HEADER_EN = (
    "[Q&A History]\n"
    "The following are previous queries and the system's responses.\n\n"
)
QA_HISTORY_HEADER_ZH = (
    "[Q&A History]\n"
    "以下是之前的用户提问及系统的回复。\n\n"
)
QA_QUERY_LABEL_EN = "Query"
QA_QUERY_LABEL_ZH = "提问"
QA_RESPONSE_LABEL_EN = "Response"
QA_RESPONSE_LABEL_ZH = "回复"
_CHARS_PER_TOKEN_BUDGET: float = 3.0
_CTX_SAFETY_FACTOR: float = 0.85
_PROMPT_GUARD_MIN_RECENT: int = 2
DEFAULT_SAVE_ROOT = "result"
TIME_RANGE_RE = re.compile(
    r"<(?P<range>\d+(?:\.\d+)?\s*(?:seconds?|s)(?:\s*(?:~|-)\s*\d+(?:\.\d+)?\s*(?:seconds?|s))?)>"
)
TIME_RANGE_VALUE_RE = re.compile(
    r"^(?P<range>\d+(?:\.\d+)?\s*(?:seconds?|s)\s*(?:~|-)\s*\d+(?:\.\d+)?\s*(?:seconds?|s))$"
)
TIME_VALUE_RE = re.compile(r"^(?P<value>\d+(?:\.\d+)?)(?:\s*(?:seconds?|s))$")
DEFAULT_SYSTEM_PROMPT_EN = """You are a real-time video streaming assistant observing a continuous camera feed frame by frame. The last frame represents the current moment.
## Action Format
At every inference step you MUST choose exactly one of the following three actions:
**Stay silent** — output ONLY:
</silence>
Choose this when nothing noteworthy has changed in the scene, no user query is pending, or there is nothing useful to say.
**Speak** — output the token followed by a concise reply:
</response> Your reply here.
Choose this when you observe something worth reporting or a significant state change, or when you can answer a user question based on available evidence.

**Delegate** — when a question is too hard or error-prone to answer reliably yourself, speak a brief note that you're delegating, then hand the question to the background solver:
</response> Brief note that you're delegating. </delegation> <the question>""".strip()
DEFAULT_SYSTEM_PROMPT="""You are a real-time video streaming assistant observing a continuous camera feed frame by frame. The last frame represents the current moment.
## Action Format
At every inference step you MUST choose exactly one of the following three actions:
**Stay silent** — output ONLY:
</silence>
Choose this when nothing noteworthy has changed in the scene, no user query is pending, or there is nothing useful to say.
**Speak** — output the token followed by a concise reply:
</response> Your reply here.
Choose this when you observe something worth reporting or a significant state change, or when you can answer a user question based on available evidence.

**Delegate** — when a question is too hard or error-prone to answer reliably yourself, speak a brief note that you're delegating, then hand the question to the background solver:
</response> Brief note that you're delegating. <delegation> <the question>""".strip()


class StreamingInferAdapter:
    def __init__(self, config: AdapterConfig):
        self.config = config
        self.sessions: dict[str, SessionState] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        # memory-store v0.2: client is fail-soft; no raise on connect fail
        self.memory_store = MemoryStoreClient(
            base_url=config.memory_store_url,
            enabled=config.memory_store_enabled,
        )
        Path(config.frame_save_dir).mkdir(parents=True, exist_ok=True)
        self.main_client = AsyncOpenAI(
            base_url=config.main_api_base,
            api_key=config.api_key,
            timeout=config.request_timeout_seconds,
        )
        self.main_clients: dict[str, tuple[AsyncOpenAI, str]] = {}
        if config.main_backends:
            for backend in config.main_backends:
                name = backend["name"]
                self.main_clients[name] = (
                    AsyncOpenAI(
                        base_url=backend["api_base"],
                        api_key=config.api_key,
                        timeout=config.request_timeout_seconds,
                    ),
                    backend.get("model", name),
                )
        else:
            self.main_clients[config.main_model] = (self.main_client, config.main_model)
        self.summarizer: Optional[SummarizerModel] = None
        if config.enable_summarizer:
            self.summarizer = SummarizerModel(
                model_name=config.summarizer_model,
                api_base=config.summarizer_api_base,
                longterm_model_name=config.longterm_model,
                longterm_api_base=config.longterm_api_base,
                mid_term_max_tokens=config.mid_term_max_tokens,
                mid_term_target_tokens=config.mid_term_target_tokens,
                long_term_max_tokens=config.long_term_max_tokens,
                long_term_target_tokens=config.long_term_target_tokens,
                key_frames_per_chunk=config.summarizer_key_frames,
                max_pixels=config.summarizer_max_pixels,
                prompt_phase_seconds=config.summarizer_phase_seconds,
                mid_term_temperature=config.mid_term_temperature,
                mid_term_top_p=config.mid_term_top_p,
                mid_term_top_k=config.mid_term_top_k,
                mid_term_repetition_penalty=config.mid_term_repetition_penalty,
                mid_term_presence_penalty=config.mid_term_presence_penalty,
                long_term_temperature=config.long_term_temperature,
                long_term_top_p=config.long_term_top_p,
                long_term_top_k=config.long_term_top_k,
                long_term_repetition_penalty=config.long_term_repetition_penalty,
                long_term_presence_penalty=config.long_term_presence_penalty,
                debug=config.summarizer_debug,
            )
        if config.out_dir:
            Path(config.out_dir).mkdir(parents=True, exist_ok=True)
        if config.light_out_dir:
            Path(config.light_out_dir).mkdir(parents=True, exist_ok=True)
        if config.debug_input_dir:
            Path(config.debug_input_dir).mkdir(parents=True, exist_ok=True)
        # Cache for the composed system prompt; invalidated by file edits
        # or by ``POST /v1/prompts/reload``.
        self._system_prompt_cache: dict[tuple[Any, ...], str] = {}
        self._character_prompt_mtime: float = 0.0
        self._refresh_character_prompt_mtime()


    # ---- character-prompt cache ---------------------------------------
    def _load_character_profiles(self) -> list[str]:
        """Read character files from disk using the configured paths.

        Returns an empty list when character injection is disabled or
        no files are found.  Errors are logged but non-fatal so a
        missing prompts/ folder does not break the adapter.
        """
        if not self.config.character_prompts_enabled:
            return []
        try:
            return load_character_prompts(self.config.character_prompt_paths)
        except Exception as exc:
            LOGGER.warning("failed to load character prompts: %s", exc)
            return []

    def _system_prompt_cache_key(self, language: str) -> tuple[Any, ...]:
        """Build a deterministic cache key for the composed system prompt."""
        return (
            self.config.system_prompt,
            language,
            self.config.character_prompts_enabled,
            tuple(self.config.character_prompt_paths),
            self._character_prompt_mtime,
        )

    def _refresh_character_prompt_mtime(self) -> float:
        """Recompute the latest mtime across the active prompt files.

        Used as part of the system-prompt cache key so on-disk edits
        invalidate the cache without requiring a manual reload.
        """
        try:
            paths = resolve_prompt_paths(self.config.character_prompt_paths)
        except Exception as exc:
            LOGGER.warning("failed to resolve prompt paths: %s", exc)
            return 0.0
        latest = 0.0
        for path in paths:
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
        return latest

    def _invalidate_system_prompt_cache(self) -> None:
        """Drop the cached system prompt and rescan file mtimes."""
        self._system_prompt_cache = {}
        self._character_prompt_mtime = self._refresh_character_prompt_mtime()

    def reload_character_prompts(self) -> list[str]:
        """Force a re-read of character files and clear the cache.

        Returns the freshly loaded profile bodies.  Wired to the
        ``POST /v1/prompts/reload`` debug endpoint.
        """
        self._invalidate_system_prompt_cache()
        profiles = self._load_character_profiles()
        LOGGER.info(
            "reloaded %d character prompt file(s); enabled=%s paths=%s",
            len(resolve_prompt_paths(self.config.character_prompt_paths)),
            self.config.character_prompts_enabled,
            self.config.character_prompt_paths,
        )
        return profiles

    def active_character_prompt_paths(self) -> list[str]:
        """Return absolute paths of every file that would be loaded."""
        return [str(p) for p in resolve_prompt_paths(self.config.character_prompt_paths)]

    def _build_system_prompt(self, language: str) -> str:
        """Return the system prompt for ``language`` with character injection.

        Reads character files lazily and caches the composed string on
        this adapter instance.  The cache is keyed by the base prompt,
        language, character-prompt configuration, and the latest file
        mtime so editing a file on disk transparently invalidates it.
        """
        key = self._system_prompt_cache_key(language)
        cached = self._system_prompt_cache.get(key)
        if cached is not None:
            return cached
        base = self.config.system_prompt or ""
        profiles = self._load_character_profiles()
        composed = _build_system_prompt(base, profiles, language)
        self._system_prompt_cache[key] = composed
        return composed

    def _build_memory_prompt(self, session_state: Optional[SessionState]) -> str:
        """Return system prompt with optional memory blocks appended.

        Fast path: when the session has no memory blocks cached, this
        just re-uses the regular cached system prompt (no extra IO).

        Slow path: when memory blocks are present, we re-compose the
        base+character+language prompt and append the [Local Wiki]
        block list. We do NOT poison the no-memory cache because the
        block content varies per session.
        """
        blocks = list(getattr(session_state, "_memory_block_cache", None) or [])
        if not blocks:
            return self._build_system_prompt(self.config.language)
        base = self.config.system_prompt or ""
        profiles = self._load_character_profiles()
        return compose_system_prompt_with_memory(
            base,
            character_prompts=profiles,
            language=self.config.language,
            memory_blocks=blocks,
        )

    def _resolve_backend(self, model_name: Optional[str] = None) -> tuple[AsyncOpenAI, str]:
        if model_name and model_name in self.main_clients:
            return self.main_clients[model_name]
        return self.main_client, self.config.main_model

    def get_session(self, session_id: str) -> SessionState:
        session_id = _safe_session_id(session_id or "default")
        state = self.sessions.get(session_id)
        if state is None:
            state = SessionState(session_id=session_id)
            if self.config.per_session_dirs and self.config.save_root:
                self._init_session_dirs(state)
            state.output_path = self._session_output_path(state, light=False)
            state.light_output_path = self._session_output_path(state, light=True)
            state.debug_input_dir = self._session_debug_input_dir(state)
            state.async_next_summary_target_turns = self._async_first_summary_turns()
            # Per-session frame directory
            frame_dir = Path(self.config.frame_save_dir) / session_id
            frame_dir.mkdir(parents=True, exist_ok=True)
            state.session_frame_dir = frame_dir
            self.sessions[session_id] = state
            # Memory-store v0.2: fire-and-forget warmup so the first
            # /v1/chat request may already see a populated cache.
            if self.memory_store.is_enabled and state._memory_warmup_task is None:
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    pass  # not in async context; warmup is lazy on first recall
                else:
                    state._memory_warmup_task = asyncio.ensure_future(
                        self._memory_warmup(state)
                    )
            LOGGER.info(
                "Created session %s (output=%s light=%s debug_input=%s frames=%s)",
                session_id,
                state.output_path,
                state.light_output_path,
                state.debug_input_dir,
                state.session_frame_dir,
            )
        state.last_access = time.time()
        return state

    def _cleanup_expired_sessions(self) -> list[SessionState]:
        now = time.time()
        timeout = self.config.session_timeout_seconds
        expired = [
            sid for sid, s in self.sessions.items()
            if now - s.last_access > timeout
        ]
        expired_states = []
        for sid in expired:
            state = self.sessions.pop(sid, None)
            if state is not None:
                for job in state.async_pending_summary_jobs:
                    job["task"].cancel()
                expired_states.append(state)
                LOGGER.info("Expired session %s (idle %.0fs)", sid, now - state.last_access)
        return expired_states

    async def _session_cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(300)
            try:
                expired_states = self._cleanup_expired_sessions()
                for state in expired_states:
                    await self._flush_session_outputs(state)
                    await self._memory_push(state)
            except Exception:
                LOGGER.exception("session cleanup error")



    # -------------------------------------------------------------------
    # Memory-store v0.2 hooks (live adapter spec D-9).
    # All hooks are no-ops if the memory_store client is disabled or
    # unreachable; the adapter never blocks the main request path on them.
    # -------------------------------------------------------------------
    async def _memory_warmup(self, state):
        """Pull blocks for this session from memory-store and cache.

        Safe to call concurrently for the same session -- only the first
        result is kept. Failures are logged at WARNING and otherwise
        degrade to an empty cache (no exception bubbles up).
        """
        if state._memory_warmed:
            return
        state._memory_warmed = True
        try:
            blocks = await self.memory_store.warmup(state.session_id)
        except Exception as exc:
            LOGGER.warning("memory warmup failed for %s: %s", state.session_id, exc)
            return
        if blocks:
            state._memory_block_cache = blocks
            LOGGER.info("memory warmup %s: pulled %d block(s)", state.session_id, len(blocks))

    async def _memory_recall(self, state, question):
        """Per-question recall. Uses warmup cache; warms up if needed.

        The first question a Pilot asks may arrive before the warmup task
        finished (fire-and-forget on session create). In that case we wait
        briefly for the warmup so the first answer benefits from previous
        session memory without a separate round-trip.
        """
        if not question:
            return list(state._memory_block_cache)
        if not state._memory_warmed:
            await self._memory_warmup(state)
        # v0.1 spec skips per-question rerank -- the cache is the answer.
        # v0.3+ may add per-question hot-fetch against the live query.
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
        for entry in (state.mid_term_summaries or []):
            if not isinstance(entry, dict):
                continue
            text = entry.get("summary_text") or entry.get("text") or ""
            if not text:
                continue
            blocks.append({"content": text, "score": 1.0})
        for entry in (state.long_term_history or []):
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

    def start_background_tasks(self) -> None:

        if self._cleanup_task is None:
            self._cleanup_task = asyncio.ensure_future(self._session_cleanup_loop())

    async def stop_background_tasks(self) -> None:
        """Cancel the cleanup loop and close the memory-store client.

        Wired to aiohttp ``on_cleanup`` so the process can exit cleanly
        without leaking the httpx connection pool.
        """
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except (asyncio.CancelledError, Exception):
                pass
            self._cleanup_task = None
        # Cancel any in-flight per-session warmup tasks.
        for state in list(self.sessions.values()):
            task = getattr(state, "_memory_warmup_task", None)
            if task is not None and not task.done():
                task.cancel()
        # Best-effort close of the memory-store httpx pool.
        try:
            await self.memory_store.aclose()
        except Exception as exc:
            LOGGER.warning("memory_store aclose raised: %s", exc)

    def _init_session_dirs(self, state: SessionState) -> None:
        """Create per-session timestamped output/input directories."""
        session_ts = datetime.fromtimestamp(state.session_started_at).strftime("%Y%m%d_%H%M%S")
        model_name = self.config.output_model_name
        save_root = self.config.save_root

        state.session_out_dir = os.path.join(save_root, f"output_{session_ts}_{model_name}")
        state.session_light_out_dir = derive_light_out_dir(state.session_out_dir)

        Path(state.session_out_dir).mkdir(parents=True, exist_ok=True)
        Path(state.session_light_out_dir).mkdir(parents=True, exist_ok=True)

        if self.config.save_debug_inputs:
            state.debug_input_dir = Path(os.path.join(save_root, f"input_{session_ts}_{model_name}"))
            state.debug_input_dir.mkdir(parents=True, exist_ok=True)

    async def handle_models(self, request: web.Request) -> web.Response:
        del request
        now = int(time.time())
        data = [
            {
                "id": name,
                "object": "model",
                "created": now,
                "owned_by": "streamingharness",
            }
            for name in self.main_clients
        ]
        return web.json_response({"object": "list", "data": data})

    async def handle_health(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(
            {
                "ok": True,
                "model": self.config.adapter_model,
                "backends": list(self.main_clients.keys()),
                "summarizer_enabled": self.summarizer is not None,
                "sessions": len(self.sessions),
                "memory_store": self.memory_store.health_snapshot(),
            }
        )

    async def handle_reset(self, request: web.Request) -> web.Response:
        payload = await _read_json(request)
        session_id = _request_session_id(request, payload)
        session_id = _safe_session_id(session_id)
        removed_state = self.sessions.pop(session_id, None)
        if removed_state is not None:
            for job in removed_state.async_pending_summary_jobs:
                job["task"].cancel()
            await self._flush_session_outputs(removed_state)
            pushed = await self._memory_push(removed_state)
        else:
            pushed = 0
        removed = removed_state is not None
        return web.json_response(
            {
                "ok": True,
                "session_id": session_id,
                "removed": removed,
                "pushed": pushed,
            }
        )

    async def handle_prompts_active(self, request: web.Request) -> web.Response:
        del request
        paths = self.active_character_prompt_paths()
        return web.json_response({
            "ok": True,
            "enabled": self.config.character_prompts_enabled,
            "extra_paths": list(self.config.character_prompt_paths),
            "files": paths,
            "cache_size": len(self._system_prompt_cache),
            "last_mtime": self._character_prompt_mtime,
            "language": self.config.language,
        })

    async def handle_prompts_reload(self, request: web.Request) -> web.Response:
        del request
        try:
            profiles = self.reload_character_prompts()
        except Exception as exc:
            LOGGER.exception("character prompt reload failed")
            return _openai_error_response(f"reload failed: {exc}", status=500)
        return web.json_response({
            "ok": True,
            "reloaded_files": self.active_character_prompt_paths(),
            "profile_count": len(profiles),
            "enabled": self.config.character_prompts_enabled,
        })



    async def handle_summarizer_route(self, request: web.Request) -> web.Response:
        """GET = snapshot current summarizer routing. POST = hot-swap.

        The webui services config panel proxies to this endpoint so the
        webui never mutates the summarizer directly. This keeps webinfer
        the single main path: webui -> webinfer -> mutate -> webinfer -> webui.

        POST body (all keys optional; omitted fields are left alone):
          { "api_base": str, "model_name": str, "api_key": str | null }
        """
        if self.summarizer is None:
            return _openai_error_response("summarizer not enabled", status=503)
        if request.method == "GET":
            return web.json_response(self.summarizer.snapshot_routing())
        try:
            payload = await _read_json(request)
        except Exception as exc:
            return _openai_error_response(f"invalid JSON body: {exc}", status=400)
        snapshot = self.summarizer.update_routing(
            api_base=payload.get("api_base"),
            model_name=payload.get("model_name"),
            api_key=payload.get("api_key"),
        )
        LOGGER.info(
            "summarizer routing updated: api_base=%s model_name=%s api_key_set=%s",
            snapshot["api_base"],
            snapshot["model_name"],
            snapshot["api_key_set"],
        )
        return web.json_response(snapshot)

    async def handle_text_chat(self, request: web.Request) -> web.Response:
        # v3.37 single-LLM-gateway: text-only chat-completion endpoint that
        # runs the same system-prompt + memory + token-guard + decision-token
        # parsing pipeline as the multimodal path, but rejects any image_url
        # content so voice-dialog callers cannot smuggle frames through.
        try:
            payload = await _read_json(request)
        except Exception as exc:
            return _openai_error_response(f"invalid JSON body: {exc}", status=400)

        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            return _openai_error_response("messages must be a non-empty list", status=400)
        valid_roles = {"system", "user", "assistant"}
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                return _openai_error_response(
                    f"messages[{index}] must be a dict", status=400
                )
            role = message.get("role")
            if role not in valid_roles:
                return _openai_error_response(
                    f"messages[{index}].role must be one of {sorted(valid_roles)}, got {role!r}",
                    status=400,
                )
            content = message.get("content")
            if isinstance(content, list):
                for part_index, part in enumerate(content):
                    if isinstance(part, dict) and part.get("type") in {"image_url", "image"}:
                        return _openai_error_response(
                            "image content not allowed on /v1/text/chat; use /v1/chat/completions for multimodal",
                            status=400,
                        )
            elif isinstance(content, str):
                if "data:image/" in content and ";base64," in content:
                    return _openai_error_response(
                        "inline base64 image not allowed on /v1/text/chat",
                        status=400,
                    )
            elif content is None:
                return _openai_error_response(
                    f"messages[{index}].content must not be null", status=400
                )
            else:
                return _openai_error_response(
                    f"messages[{index}].content must be str or list, got {type(content).__name__}",
                    status=400,
                )

        session_id = _request_session_id(request, payload)
        requested_model = payload.get("model")
        client, model_name = self._resolve_backend(requested_model)
        state = self.get_session(session_id)
        async with state.lock:
            try:
                result = await self._handle_text_payload(
                    state, payload, client=client, model_name=model_name
                )
            except web.HTTPException:
                raise
            except Exception as exc:
                LOGGER.exception("text chat completion failed")
                return _openai_error_response(str(exc), status=502)
        return web.json_response(result)

    async def _handle_text_payload(
        self,
        state: SessionState,
        payload: dict[str, Any],
        *,
        client: Optional[AsyncOpenAI] = None,
        model_name: Optional[str] = None,
    ) -> dict[str, Any]:
        # Single-LLM-gateway text path. Composes the system prompt
        # (character profile + [Local Wiki]), runs the v3.34 prompt
        # token guard, forwards to the main model, parses decision
        # tokens, and records the turn in qa_history so the next call
        # sees the same conversation context as the video path.
        client = client or self.main_client
        model_name = model_name or self.config.main_model

        # Slice 2: warm up memory blocks (fire-and-forget, fail-soft) so the
        # system prompt picks up recent persisted knowledge.
        if self.memory_store is not None and getattr(self.memory_store, "is_enabled", False):
            try:
                blocks = await self.memory_store.warmup(state.session_id)
                if blocks:
                    state._memory_block_cache = list(blocks)
                    state._memory_warmed = True
            except Exception:
                LOGGER.debug("memory-store warmup failed for %s", state.session_id)

        api_messages = list(payload.get("messages") or [])
        composed_system = (self._build_memory_prompt(state) or "").strip()

        # Resolve any caller-supplied system message into a flat list.
        caller_messages = [
            dict(m) for m in api_messages if m.get("role") != "system"
        ]
        if composed_system:
            http_messages = (
                [{"role": "system", "content": composed_system}] + caller_messages
            )
        else:
            http_messages = caller_messages

        # v3.34 prompt guard runs LAST so it sees the full assembled
        # messages list (system + turns).
        max_total_chars = _compute_prompt_guard_max_chars(self.config.main_ctx_tokens)
        if max_total_chars > 0:
            http_messages, removed = _trim_messages_to_ctx(
                [dict(m) for m in http_messages], max_total_chars
            )
        else:
            removed = 0

        generation_kwargs = self._main_generation_kwargs(payload)
        response = await client.chat.completions.create(
            model=model_name,
            messages=http_messages,
            **generation_kwargs,
        )
        raw_text = response.choices[0].message.content if response.choices else ""
        usage = response.usage.model_dump() if getattr(response, "usage", None) else None

        decision, clean_text, delegation_question = _parse_decision_tokens(raw_text or "")

        # Update qa_history so the NEXT call sees this turn as context,
        # matching what the multimodal path does for video sessions.
        self._update_text_qa_history(state, api_messages, clean_text, decision)

        memory_chars = len(composed_system)
        qa_history_len = len(state.memory_state.get("qa_history", []))
        prompt_chars = _estimate_messages_chars(http_messages)

        return _chat_completion_response(
            model=self.config.adapter_model,
            content=clean_text,
            usage=usage,
            raw_model=model_name,
            raw_text=raw_text or "",
            decision=decision,
            delegation_question=delegation_question,
            memory_chars=memory_chars,
            qa_history_len=qa_history_len,
            prompt_chars=prompt_chars,
            trimmed_turns=removed,
        )

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
            qa_history.append({
                "query_time": now_iso,
                "query": last_user_text,
                "responses": [{"prediction": clean_text, "decision": decision}],
                "archived_in_chunk": None,
                "text_path": True,
            })
        else:
            existing.setdefault("responses", []).append(
                {"prediction": clean_text, "decision": decision}
            )

    async def handle_chat_completions(self, request: web.Request) -> web.Response:
        payload = await _read_json(request)
        session_id = _request_session_id(request, payload)
        requested_model = payload.get("model")
        client, model_name = self._resolve_backend(requested_model)
        state = self.get_session(session_id)
        async with state.lock:
            try:
                result = await self._handle_chat_payload(state, payload, request, client=client, model_name=model_name)
            except web.HTTPException:
                raise
            except Exception as exc:
                LOGGER.exception("chat completion failed")
                return _openai_error_response(str(exc), status=502)
        return web.json_response(result)

    def _session_output_path(self, state: SessionState, light: bool) -> Optional[Path]:
        if light:
            root = state.session_light_out_dir or self.config.light_out_dir
        else:
            root = state.session_out_dir or self.config.out_dir
        if not root:
            return None
        safe_session = sanitize_output_name(state.session_id)
        return Path(root) / "live" / f"{safe_session}.json"

    def _session_debug_input_dir(self, state: SessionState) -> Optional[Path]:
        if state.debug_input_dir:
            return state.debug_input_dir
        if not self.config.debug_input_dir:
            return None
        return Path(self.config.debug_input_dir)

    def _session_sample_data(self, state: SessionState) -> dict[str, Any]:
        return {
            "task_type": "live",
            "session_id": state.session_id,
            "adapter_model": self.config.adapter_model,
            "main_model": self.config.main_model,
            "main_api_base": self.config.main_api_base,
            "summarizer_model": self.config.summarizer_model,
            "summarizer_api_base": self.config.summarizer_api_base,
            "longterm_model": self.config.longterm_model,
            "longterm_api_base": self.config.longterm_api_base,
            "started_at": datetime.fromtimestamp(state.session_started_at).isoformat(
                timespec="seconds"
            ),
        }

    def _memory_trace(self, state: SessionState) -> dict[str, Any]:
        return {
            "mid_term_summaries": list(state.mid_term_history),
            "long_term_history": list(state.long_term_history),
            "qa_history": list(state.memory_state.get("qa_history", [])),
            "long_term_memory": state.memory_state.get("long_term_memory", ""),
        }

    def _write_json_file(self, path: Path, obj: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as file_obj:
            json.dump(obj, file_obj, ensure_ascii=False, indent=2)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(tmp_path, path)

    def _light_predictions(
        self,
        predictions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        light_keys = (
            "turn",
            "time_range",
            "query",
            "prediction",
            "total_time",
            "inference_time",
            "fourb_mid_term_inference_time",
            "fourb_long_term_inference_time",
            "ground_truth",
        )
        return [
            {key: prediction[key] for key in light_keys if key in prediction}
            for prediction in predictions
        ]

    @staticmethod
    def _strip_base64_images(obj: Any) -> tuple[Any, dict[str, str]]:
        """Recursively strip inline base64 image data from an object.

        Returns a (stripped_obj, images_dict) tuple where images_dict maps
        placeholder keys to the original base64 strings.
        """
        images: dict[str, str] = {}
        counter = [0]

        def _strip(node: Any) -> Any:
            if isinstance(node, str):
                if node.startswith("data:image/") and len(node) > 200:
                    key = f"__image_{counter[0]}__"
                    counter[0] += 1
                    images[key] = node
                    return key
                return node
            if isinstance(node, list):
                return [_strip(item) for item in node]
            if isinstance(node, dict):
                return {k: _strip(v) for k, v in node.items()}
            return node

        stripped = _strip(obj)
        return stripped, images

    def _write_session_outputs_sync(
        self,
        output_path: Optional[Path],
        light_output_path: Optional[Path],
        full_result: Optional[dict[str, Any]],
        light_result: Optional[dict[str, Any]],
    ) -> None:
        if light_output_path and light_result:
            self._write_json_file(light_output_path, light_result)
        if output_path and full_result:
            stripped_result, images = self._strip_base64_images(full_result)
            self._write_json_file(output_path, stripped_result)
            if images:
                images_path = output_path.with_suffix(".images.json")
                self._write_json_file(images_path, images)

    def _write_session_outputs(self, state: SessionState) -> None:
        total_time = time.time() - state.session_started_at
        output_path = state.output_path
        light_output_path = state.light_output_path
        if not output_path and not light_output_path:
            return
        predictions_snapshot = copy.deepcopy(state.predictions)
        sample_data = self._session_sample_data(state)
        memory_trace = copy.deepcopy(self._memory_trace(state))
        full_result = None
        light_result = None
        if output_path:
            full_result = {
                "sample_data": sample_data,
                "total_time": total_time,
                "total_turns": len(predictions_snapshot),
                "predictions": predictions_snapshot,
                "memory": memory_trace,
            }
        if light_output_path:
            light_result = {
                "sample_data": sample_data,
                "total_time": total_time,
                "total_turns": len(predictions_snapshot),
                "predictions": self._light_predictions(predictions_snapshot),
                "memory": memory_trace,
            }
        if state._pending_write_task and not state._pending_write_task.done():
            state._pending_write_task.cancel()
        task = asyncio.ensure_future(
            asyncio.to_thread(
                self._write_session_outputs_sync,
                output_path,
                light_output_path,
                full_result,
                light_result,
            )
        )
        task.add_done_callback(self._on_write_task_done)
        state._pending_write_task = task

    @staticmethod
    def _on_write_task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            LOGGER.error("session output write failed: %s", exc, exc_info=exc)

    async def _flush_session_outputs(self, state: SessionState) -> None:
        """Write final session outputs synchronously at session end."""
        self._execute_pending_qa_archive(state)
        if self.config.keep_qa_history and state.current_query_text:
            archive_chunk_response_records(
                state.current_chunk,
                state.memory_state,
                state.current_query_text,
                state.query_start_time,
                chunk_index=state.chunk_index,
            )
        total_time = time.time() - state.session_started_at
        output_path = state.output_path
        light_output_path = state.light_output_path
        if not output_path and not light_output_path:
            return
        if not state.predictions:
            return
        sample_data = self._session_sample_data(state)
        memory_trace = self._memory_trace(state)
        full_result = None
        light_result = None
        if output_path:
            full_result = {
                "sample_data": sample_data,
                "total_time": total_time,
                "total_turns": len(state.predictions),
                "predictions": state.predictions,
                "memory": memory_trace,
            }
        if light_output_path:
            light_result = {
                "sample_data": sample_data,
                "total_time": total_time,
                "total_turns": len(state.predictions),
                "predictions": self._light_predictions(state.predictions),
                "memory": memory_trace,
            }
        await asyncio.to_thread(
            self._write_session_outputs_sync,
            output_path,
            light_output_path,
            full_result,
            light_result,
        )
        LOGGER.info(
            "[%s] final session output written (%d turns)",
            state.session_id,
            len(state.predictions),
        )

    def _save_live_debug_input(
        self,
        state: SessionState,
        record: dict[str, Any],
        stem: str,
    ) -> Optional[str]:
        debug_dir = state.debug_input_dir or self.config.debug_input_dir
        if not debug_dir:
            return None
        path = (
            Path(debug_dir)
            / f"{sanitize_output_name(state.session_id)}__{stem}.json"
        )
        record = copy.deepcopy(record)
        record.setdefault("saved_at", datetime.now().isoformat(timespec="seconds"))
        record.setdefault("session_id", state.session_id)
        self._write_json_file(path, record)
        return str(path)

    def _maybe_save_chunk_start_model_input(
        self,
        state: SessionState,
        turn_count: int,
        time_range: str,
        model_input_record: dict[str, Any],
    ) -> Optional[str]:
        if not (state.debug_input_dir or self.config.debug_input_dir):
            return None
        if state.chunk_index in state.chunk_start_input_saved:
            return None
        record = copy.deepcopy(model_input_record)
        record["stage"] = "main_8b_chunk_start"
        record["turn"] = turn_count
        record["time_range"] = time_range
        path = self._save_live_debug_input(
            state,
            record,
            f"chunk_{state.chunk_index:04d}__turn_{turn_count:04d}",
        )
        state.chunk_start_input_saved.add(state.chunk_index)
        return path

    def _save_summarizer_debug_input(
        self,
        state: SessionState,
        stage: str,
        index: int,
        record: Optional[dict[str, Any]],
    ) -> Optional[str]:
        if not record:
            return None
        return self._save_live_debug_input(
            state,
            record,
            f"{stage}__{index:04d}",
        )

    async def _handle_chat_payload(
        self,
        state: SessionState,
        payload: dict[str, Any],
        request: web.Request,
        *,
        client: Optional[AsyncOpenAI] = None,
        model_name: Optional[str] = None,
    ) -> dict[str, Any]:
        client = client or self.main_client
        model_name = model_name or self.config.main_model
        t_start = time.perf_counter()
        messages = payload.get("messages") or []
        if not isinstance(messages, list):
            raise web.HTTPBadRequest(text="messages must be a list")

        image_refs = _extract_all_image_refs(messages, request, payload)
        if not image_refs:
            return await self._forward_text_only(payload, client=client, model_name=model_name)

        turn_count = len(state.predictions) + 1
        raw_prompt_text = _extract_user_prompt_text(messages)
        prompt_text = _strip_time_range_from_text(raw_prompt_text)

        # Resolve time ranges for all images
        incoming_time_ranges = _extract_time_ranges_from_request(request, payload)
        if not incoming_time_ranges:
            single = _extract_time_range_from_request(request, payload)
            if single is None:
                single = _extract_time_range_from_text(raw_prompt_text)
            if single:
                incoming_time_ranges = [single]
        time_ranges: list[str] = []
        for i in range(len(image_refs)):
            if i < len(incoming_time_ranges) and incoming_time_ranges[i]:
                time_ranges.append(incoming_time_ranges[i])
            else:
                time_ranges.append(self._time_range_for_frame(state.frame_count + i))
        time_range = _format_turn_time_range(time_ranges)

        image_paths = [self._resolve_frame_ref(ref, state) for ref in image_refs]
        LOGGER.info(
            "[%s] turn=%d frames=%d(+%d) chunk=%d time=%s prompt=%r",
            state.session_id,
            turn_count,
            state.frame_count,
            len(image_refs),
            state.chunk_index,
            time_range,
            _short(prompt_text, 80),
        )

        query_text = self._update_query_state(state, prompt_text, time_ranges[0])

        await self._commit_required_async_summaries(
            state, state.turn_count, non_blocking=True,
        )

        if (
            self.config.chunk > 0
            and state.current_chunk["turn_count"] >= self.config.chunk
        ):
            self._execute_pending_qa_archive(state)
            carry_response_records = []
            if self.config.keep_qa_history and state.current_query_text:
                qa_cutoff = float("inf")
                if (
                    self._async_summary_enabled()
                    and state.async_summary_segment["frame_time_ranges"]
                ):
                    qa_cutoff = _parse_start_second(
                        state.async_summary_segment["frame_time_ranges"][0]
                    )
                    carry_response_records = [
                        (tr, payload)
                        for tr, payload in state.current_chunk["response_records"]
                        if _parse_start_second(tr) >= qa_cutoff
                    ]
                archive_chunk_response_records(
                    state.current_chunk,
                    state.memory_state,
                    state.current_query_text,
                    state.query_start_time,
                    chunk_index=state.chunk_index,
                    before_time_sec=qa_cutoff,
                )
            await self._flush_chunk(state, use_async_summary=self._async_summary_enabled())
            if (
                self._async_summary_enabled()
                and state.async_summary_segment["turn_count"] > 0
            ):
                carry = copy.deepcopy(state.async_summary_segment)
                carry_frames = carry["frame_count"]
                carry_turns = carry["turn_count"]
                carry["frame_count"] = 0
                carry["turn_count"] = 0
                carry["response_records"] = carry_response_records
                carry["api_msg_cache"] = []
                state.current_chunk = carry
                LOGGER.info(
                    "[%s] carried over %d unsummarized turn(s), %d frame(s) to new chunk",
                    state.session_id,
                    carry_turns,
                    carry_frames,
                )
            else:
                state.current_chunk = reset_chunk_state()
            state.chunk_index += 1
            state.query_in_current_chunk = bool(query_text)

        for tr, ip in zip(time_ranges, image_paths):
            state.frame_count += 1
            state.current_chunk["image_paths"].append(str(ip))
            state.current_chunk["frame_time_ranges"].append(tr)
            state.current_chunk["summarizer_frame_cache"].append({"path": str(ip)})
            state.current_chunk["frame_count"] += 1

        state.turn_count += 1
        state.current_chunk["turn_count"] += 1

        user_message = self._build_internal_user_message(
            time_ranges=time_ranges,
            image_paths=[str(ip) for ip in image_paths],
            query_text=query_text,
        )
        state.current_chunk["messages"].append(user_message)
        if self._async_summary_enabled():
            self._append_async_summary_user_message(
                state,
                time_ranges=time_ranges,
                image_paths=[str(ip) for ip in image_paths],
                query_text=query_text,
            )

        turn_input_record = {
            "source_message": messages[-1] if messages else None,
            "vllm_message": user_message,
            "chunk_index": state.chunk_index,
            "has_image": True,
            "image_path": str(image_paths[-1]),
            "image_paths_batch": [str(ip) for ip in image_paths],
            "num_chunk_turns": state.current_chunk["turn_count"],
            "num_chunk_frames": state.current_chunk["frame_count"],
            "image_paths": list(state.current_chunk["image_paths"]),
            "frame_time_ranges": list(state.current_chunk["frame_time_ranges"]),
        }
        is_forced_silence = (
            self.config.force_silence_before_query and not state.current_query_text
        )
        inference_start = None
        inference_time = 0.0
        chunk_start_model_input_path = None
        turn_model_input_record = None
        model_input_record = None

        if is_forced_silence:
            generated_text = "</silence>"
            raw_text = ""
            usage = None
            turn_model_input_record = build_model_input_record(
                chunk_index=state.chunk_index,
                messages=state.current_chunk["messages"],
                frame_count=state.current_chunk["frame_count"],
                inference_skipped=True,
                skip_reason="force_silence_before_query",
                image_paths=state.current_chunk["image_paths"],
                frame_time_ranges=state.current_chunk["frame_time_ranges"],
            )
            if self.config.save_model_inputs:
                model_input_record = turn_model_input_record
        else:
            t_prompt_build_start = time.perf_counter()
            internal_messages, prefix_content = self._build_main_internal_messages(state)
            api_messages = self._build_cached_api_messages(state, internal_messages)
            generation_kwargs = self._main_generation_kwargs(payload)
            http_messages = self._build_main_http_messages(
                api_messages, session_state=state
            )
            # DEBUG v0.2: print first message roles + system content length
            try:
                roles = [m.get('role') for m in http_messages]
                sys_lens = [len(m.get('content') or '') for m in http_messages if m.get('role') == 'system']
                LOGGER.info('DEBUG v0.2 http_messages roles=%s sys_content_lengths=%s', roles, sys_lens)
                if state._memory_block_cache:
                    LOGGER.info('DEBUG v0.2 cache blocks=%d first_id=%s', len(state._memory_block_cache), state._memory_block_cache[0].get('block_id'))
                else:
                    LOGGER.info('DEBUG v0.2 cache empty (warmed=%s)', state._memory_warmed)
            except Exception as e:
                LOGGER.warning('DEBUG v0.2 failed: %s', e)
            turn_model_input_record = build_model_input_record(
                chunk_index=state.chunk_index,
                messages=http_messages,
                frame_count=state.current_chunk["frame_count"],
                model=model_name,
                generation_kwargs=generation_kwargs,
                image_paths=state.current_chunk["image_paths"],
                frame_time_ranges=state.current_chunk["frame_time_ranges"],
                prefix_content=prefix_content,
            )
            if self.config.save_model_inputs:
                model_input_record = turn_model_input_record
            chunk_start_model_input_path = self._maybe_save_chunk_start_model_input(
                state,
                turn_count,
                time_range,
                turn_model_input_record,
            )
            t_prompt_build_end = time.perf_counter()
            inference_start = time.time()
            raw_text, usage = await self._call_main_model(
                payload,
                api_messages,
                client=client,
                model_name=model_name,
                session_state=state,
                generation_kwargs=generation_kwargs,
                http_messages=http_messages,
            )
            inference_time = time.time() - inference_start
            t_inference_end = time.perf_counter()
            generated_text = (
                normalize_model_output(raw_text)
                if self.config.normalize_output
                else (raw_text or "").strip()
            )

        self._execute_pending_qa_archive(state)

        response_payload = extract_response_payload(generated_text)
        if response_payload and state.current_query_text:
            state.current_chunk["response_records"].append((time_range, response_payload))

        state.current_chunk["messages"].append(
            {"role": "assistant", "content": generated_text}
        )
        if self._async_summary_enabled():
            state.async_summary_segment["messages"].append(
                {"role": "assistant", "content": generated_text}
            )
            self._submit_async_summary_if_needed(state)

        turn_output_record = {}
        if is_forced_silence:
            turn_output_record["inference_skipped"] = True
            turn_output_record["skip_reason"] = "force_silence_before_query"

        t_end = time.perf_counter()
        total_time = t_end - t_start

        prediction = {
            "turn": turn_count,
            "time_range": time_range,
            "query": query_text,
            "input": turn_input_record,
            "output": turn_output_record,
            "prediction": generated_text,
            "total_time": round(total_time, 3),
            "inference_time": round(inference_time, 3),
        }
        if model_input_record is not None:
            turn_input_record["model_input"] = model_input_record
        if chunk_start_model_input_path:
            prediction["chunk_start_model_input_path"] = chunk_start_model_input_path
        if raw_text and raw_text.strip() != generated_text:
            prediction["raw_prediction"] = raw_text
        state.predictions.append(prediction)

        t_end = time.perf_counter()
        adapter_timing = {
            "adapter_total_ms": round((t_end - t_start) * 1000, 1),
        }
        if not is_forced_silence:
            adapter_timing["prompt_build_ms"] = round((t_prompt_build_end - t_prompt_build_start) * 1000, 1)
            adapter_timing["vllm_inference_ms"] = round(inference_time * 1000, 1)
            adapter_timing["post_process_ms"] = round((t_end - t_inference_end) * 1000, 1)
            adapter_timing["pre_inference_ms"] = round((t_prompt_build_start - t_start) * 1000, 1)

        if not is_forced_silence:
            LOGGER.info(
                "[%s] turn=%d timing: total=%.1fms pre=%.1fms prompt_build=%.1fms vllm=%.1fms post=%.1fms",
                state.session_id,
                turn_count,
                adapter_timing["adapter_total_ms"],
                adapter_timing["pre_inference_ms"],
                adapter_timing["prompt_build_ms"],
                adapter_timing["vllm_inference_ms"],
                adapter_timing["post_process_ms"],
            )
        else:
            LOGGER.info(
                "[%s] turn=%d timing: total=%.1fms (forced silence, inference skipped)",
                state.session_id,
                turn_count,
                adapter_timing["adapter_total_ms"],
            )

        result = _chat_completion_response(
            model=self.config.adapter_model,
            content=generated_text,
            usage=usage,
            raw_model=model_name,
            raw_text=raw_text,
        )
        result["streamingharness"]["timing"] = adapter_timing
        summarizer_timing = {}
        if state.mid_term_history:
            last_mid = state.mid_term_history[-1]
            summarizer_timing["last_mid_term_ms"] = round(last_mid.get("inference_time", 0) * 1000, 1)
            summarizer_timing["last_mid_term_chunk"] = last_mid.get("chunk_index")
            if last_mid.get("barrier_wait_time") is not None:
                summarizer_timing["barrier_wait_ms"] = round(last_mid["barrier_wait_time"] * 1000, 1)
        if state.long_term_history:
            last_long = state.long_term_history[-1]
            summarizer_timing["last_long_term_ms"] = round(last_long.get("inference_time", 0) * 1000, 1)
        result["streamingharness"]["summarizer_timing"] = summarizer_timing
        result["streamingharness"]["memory"] = {
            "mid_term_summaries": [
                {"chunk_index": e["chunk_index"], "frame_range": e["frame_range"], "summary_text": e["summary_text"]}
                for e in state.mid_term_summaries
            ],
            "long_term_memory": state.memory_state.get("long_term_memory", ""),
        }
        return result

    async def _forward_text_only(
        self,
        payload: dict[str, Any],
        *,
        client: Optional[AsyncOpenAI] = None,
        model_name: Optional[str] = None,
    ) -> dict[str, Any]:
        client = client or self.main_client
        model_name = model_name or self.config.main_model
        generation_kwargs = self._main_generation_kwargs(payload)
        response = await client.chat.completions.create(
            model=model_name,
            messages=payload.get("messages") or [],
            **generation_kwargs,
        )
        raw_text = response.choices[0].message.content if response.choices else ""
        usage = response.usage.model_dump() if getattr(response, "usage", None) else None
        return _chat_completion_response(
            model=self.config.adapter_model,
            content=raw_text or "",
            usage=usage,
            raw_model=model_name,
            raw_text=raw_text or "",
        )

    def _time_range_for_frame(self, frame_index: int) -> str:
        start = frame_index * self.config.frame_seconds
        return f"{start:.1f} seconds"

    def _resolve_frame_ref(
        self,
        image_ref: dict[str, str],
        state: SessionState,
    ) -> str:
        if image_ref.get("kind") == "path":
            return str(self._validate_local_image_path(image_ref.get("value", "")))
        if image_ref.get("kind") == "data_url":
            return self._save_base64_frame(image_ref.get("value", ""), state)
        raise web.HTTPBadRequest(text="unsupported image reference kind")

    def _save_base64_frame(self, data_url: str, state: SessionState) -> str:
        match = re.match(r"data:image/\w+;base64,(.+)", data_url)
        if not match:
            raise web.HTTPBadRequest(text="invalid data URL format")
        state.session_frame_counter += 1
        return data_url

    def _validate_local_image_path(self, raw_path: str) -> Path:
        if not self.config.allowed_local_image_roots:
            raise web.HTTPBadRequest(text="local image paths are disabled")

        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise web.HTTPBadRequest(text=f"local image path does not exist: {path}")
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            raise web.HTTPBadRequest(text=f"unsupported local image extension: {path.suffix}")

        for root in self.config.allowed_local_image_roots:
            root_path = Path(root).expanduser().resolve()
            try:
                path.relative_to(root_path)
                return path
            except ValueError:
                continue

        allowed = ", ".join(self.config.allowed_local_image_roots)
        raise web.HTTPBadRequest(text=f"local image path is outside allowed roots: {allowed}")

    def _update_query_state(
        self,
        state: SessionState,
        prompt_text: str,
        time_range: str,
    ) -> Optional[str]:
        if not self.config.use_prompt_as_query:
            return None

        normalized_prompt = (prompt_text or "").strip()
        if not normalized_prompt:
            return None

        if state.current_query_text is None:
            state.current_query_text = normalized_prompt
            state.query_start_time = time_range
            state.query_in_current_chunk = True
            return normalized_prompt

        if normalized_prompt != state.current_query_text:
            state._pending_qa_archive = (state.current_query_text, state.query_start_time)
            state.current_query_text = normalized_prompt
            state.query_start_time = time_range
            state.query_in_current_chunk = True
            return normalized_prompt

        return state.current_query_text

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

    def _build_internal_user_message(
        self,
        time_range=None,
        image_path=None,
        query_text=None,
        *,
        time_ranges=None,
        image_paths=None,
    ) -> dict[str, Any]:
        i18n = _get_i18n(self.config.language)
        if time_ranges is None:
            time_ranges = [time_range] if time_range else []
        if image_paths is None:
            image_paths = [image_path] if image_path else []
        content: list[dict[str, Any]] = []
        if query_text:
            content.append({"type": "text", "text": i18n["user_query_header"] + "\n" + query_text})
        batch_time_marker = _format_batch_time_marker(time_ranges)
        if batch_time_marker:
            content.append({"type": "text", "text": f"<{batch_time_marker}>"})
        for ip in image_paths:
            content.append(
                {
                    "type": "image",
                    "image": ip,
                    "max_pixels": self.config.max_pixels,
                }
            )
        return {"role": "user", "content": content}

    def _build_main_internal_messages(
        self,
        state: SessionState,
    ) -> tuple[list[dict[str, Any]], str]:
        memory_state = state.memory_state if state.current_query_text else None
        static_content = build_static_system_content(
            memory_state=memory_state,
            mid_term_summaries=state.mid_term_summaries,
            language=self.config.language,
        )
        inject_query = state.current_query_text if not state.query_in_current_chunk else None
        dynamic_content = build_dynamic_system_content(
            current_query_text=inject_query,
            memory_state=memory_state,
            include_qa_history=self.config.keep_qa_history,
            current_chunk_index=state.chunk_index,
            language=self.config.language,
        )
        prefix_content = "\n\n".join(
            part for part in (static_content, dynamic_content) if part
        )
        all_messages = list(state.current_chunk["messages"])

        if prefix_content:
            for idx, message in enumerate(all_messages):
                if message.get("role") != "user":
                    continue
                new_message = dict(message)
                content = message.get("content")
                if isinstance(content, list):
                    new_message["content"] = [
                        {"type": "text", "text": prefix_content}
                    ] + list(content)
                elif isinstance(content, str):
                    new_message["content"] = prefix_content + "\n\n" + content
                else:
                    new_message["content"] = prefix_content
                all_messages[idx] = new_message
                break

        return all_messages, prefix_content

    def _build_main_api_messages(self, state: SessionState) -> list[dict[str, Any]]:
        all_messages, _ = self._build_main_internal_messages(state)
        return [_internal_message_to_openai(message) for message in all_messages]

    def _build_cached_api_messages(
        self,
        state: SessionState,
        internal_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cache = state.current_chunk["api_msg_cache"]
        chunk_msgs = state.current_chunk["messages"]
        # Incrementally convert new chunk messages and append to cache.
        # cache[i] corresponds to chunk_msgs[i] (without prefix injection).
        while len(cache) < len(chunk_msgs):
            cache.append(_internal_message_to_openai(chunk_msgs[len(cache)]))
        # internal_messages[0] has prefix injected, so always re-convert it.
        # internal_messages[1:] are identical to chunk_msgs[1:], so reuse cache.
        first_msg = _internal_message_to_openai(internal_messages[0])
        remaining = cache[1:len(internal_messages)]
        return [first_msg] + remaining

    def _build_main_http_messages(
        self,
        api_messages: list[dict[str, Any]],
        *,
        session_state: Optional[SessionState] = None,
        max_total_chars: int = 0,
    ) -> list[dict[str, Any]]:
        """Build the OpenAI chat-completions payload for the main model.

        The system prompt is composed via :meth:`_build_system_prompt`
        so that the character profile (when enabled) is injected ahead
        of the base decision-token prompt and re-reads are cached.

        When ``session_state`` carries a populated memory-block cache
        (memory-store v0.2) the cached blocks are appended as a
        [Local Wiki] section via :func:`compose_system_prompt_with_memory`.

        v3.34 prompt guard: when ``max_total_chars`` is positive and the
        assembled messages exceed that budget, the oldest user/assistant
        turns are dropped (keeping the system message + the last
        ``_PROMPT_GUARD_MIN_RECENT`` turns) so the request stays inside
        the llama-server -c context window.
        """
        messages = list(api_messages)
        system_prompt = self._build_memory_prompt(session_state)
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages
        if max_total_chars > 0:
            before = len(messages)
            messages, removed = _trim_messages_to_ctx(messages, max_total_chars)
            if removed:
                LOGGER.warning(
                    "v3.34 prompt guard: dropped %d oldest turn(s) to fit ctx "
                    "budget (max_total_chars=%d, before=%d, after=%d, est_chars=%d)",
                    removed, max_total_chars, before, len(messages),
                    _estimate_messages_chars(messages),
                )
        return messages

    async def _call_main_model(
        self,
        inbound_payload: dict[str, Any],
        api_messages: list[dict[str, Any]],
        *,
        client: Optional[AsyncOpenAI] = None,
        model_name: Optional[str] = None,
        session_state: Optional[SessionState] = None,
        generation_kwargs: Optional[dict[str, Any]] = None,
        http_messages: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[str, Optional[dict[str, Any]]]:
        client = client or self.main_client
        model_name = model_name or self.config.main_model
        generation_kwargs = generation_kwargs or self._main_generation_kwargs(inbound_payload)
        max_total_chars = _compute_prompt_guard_max_chars(self.config.main_ctx_tokens)
        api_messages = http_messages or self._build_main_http_messages(
            api_messages,
            session_state=session_state,
            max_total_chars=max_total_chars,
        )
        response = await client.chat.completions.create(
            model=model_name,
            messages=api_messages,
            **generation_kwargs,
        )
        raw_text = response.choices[0].message.content if response.choices else ""
        usage = response.usage.model_dump() if getattr(response, "usage", None) else None
        return raw_text or "", usage

    def _main_generation_kwargs(self, inbound_payload: dict[str, Any]) -> dict[str, Any]:
        extra_body = _extract_extra_body(inbound_payload)
        extra_body.setdefault("skip_special_tokens", False)
        extra_body.setdefault("greedy", False)
        if self.config.honor_inbound_generation_params:
            extra_body.setdefault("top_k", self.config.main_top_k)
            extra_body.setdefault("repetition_penalty", self.config.main_repetition_penalty)
            return {
                "max_tokens": inbound_payload.get("max_tokens", self.config.main_max_tokens),
                "temperature": inbound_payload.get("temperature", self.config.main_temperature),
                "top_p": inbound_payload.get("top_p", self.config.main_top_p),
                "presence_penalty": inbound_payload.get("presence_penalty", self.config.main_presence_penalty),
                "extra_body": extra_body,
            }

        extra_body["top_k"] = self.config.main_top_k
        extra_body["repetition_penalty"] = self.config.main_repetition_penalty
        return {
            "max_tokens": self.config.main_max_tokens,
            "temperature": self.config.main_temperature,
            "top_p": self.config.main_top_p,
            "presence_penalty": self.config.main_presence_penalty,
            "extra_body": extra_body,
        }

    async def _flush_chunk(self, state: SessionState, use_async_summary: bool = False) -> None:
        current_chunk = state.current_chunk
        if current_chunk["frame_count"] <= 0:
            return

        _file_to_data_url_cached.cache_clear()

        if self.summarizer is not None and use_async_summary:
            await self._commit_required_async_summaries(
                state, state.turn_count, non_blocking=False,
            )
        elif self.summarizer is not None:
            mid_term_entry, summary_time = await asyncio.to_thread(
                self._build_mid_term_summary_entry,
                state,
                copy.deepcopy(current_chunk),
            )
            state.mid_term_summaries.append(mid_term_entry)
            state.mid_term_history.append(mid_term_entry)
            LOGGER.info(
                "[%s] chunk=%d range=%s mid-summary %.3fs (%d/%d buffered)",
                state.session_id,
                mid_term_entry["chunk_index"],
                mid_term_entry["frame_range"],
                summary_time,
                len(state.mid_term_summaries),
                self.config.compress_every_n_chunks,
            )
            if len(state.mid_term_summaries) >= self.config.compress_every_n_chunks:
                await asyncio.to_thread(self._compress_mid_terms, state)

    def _build_mid_term_summary_entry(
        self,
        state: SessionState,
        chunk_snapshot: dict[str, Any],
        chunk_index: Optional[int] = None,
        current_query_text: Optional[str] = None,
        query_start_time: Optional[str] = None,
    ) -> tuple[dict[str, Any], float]:
        assert self.summarizer is not None
        resolved_chunk_index = chunk_index if chunk_index is not None else state.chunk_index
        resolved_query_text = current_query_text if current_query_text is not None else (state.current_query_text or "")
        resolved_query_start_time = query_start_time if query_start_time is not None else state.query_start_time
        frame_range = _compute_chunk_frame_range(chunk_snapshot)
        key_frames = self.summarizer.select_key_frames(
            chunk_snapshot["image_paths"],
            chunk_snapshot["frame_time_ranges"],
            _get_response_frame_indices(chunk_snapshot["messages"]),
            chunk_snapshot["summarizer_frame_cache"],
        )
        start = time.time()
        summary, mid_term_debug_input = self.summarizer.generate_detailed_summary(
            resolved_chunk_index,
            frame_range,
            key_frames,
            chunk_snapshot["frame_count"],
            resolved_query_text,
        )
        elapsed = time.time() - start
        debug_input_path = self._save_summarizer_debug_input(
            state,
            "mid_term",
            resolved_chunk_index,
            copy.deepcopy(mid_term_debug_input),
        )
        entry = {
            "chunk_index": resolved_chunk_index,
            "frame_range": frame_range,
            "query": resolved_query_text,
            "query_start_time": resolved_query_start_time,
            "summary_text": summary,
            "frame_count": chunk_snapshot["frame_count"],
            "key_frame_count": len(key_frames),
            "inference_time": round(elapsed, 3),
            "compressed_to_long_term": False,
        }
        if debug_input_path:
            entry["debug_input_path"] = debug_input_path
        return entry, elapsed

    def _compress_mid_terms(self, state: SessionState) -> None:
        assert self.summarizer is not None
        batch_index = state.long_term_compression_next_index
        state.long_term_compression_next_index += 1
        source_chunk_indices = [
            entry["chunk_index"] for entry in state.mid_term_summaries
        ]
        source_frame_ranges = [
            entry["frame_range"] for entry in state.mid_term_summaries
        ]
        start = time.time()
        merged, token_count, compressed_text, long_term_debug_input = self.summarizer.batch_compress_to_longterm(
            state.memory_state["long_term_memory"],
            state.mid_term_summaries,
        )
        elapsed = time.time() - start
        state.memory_state["long_term_memory"] = merged
        for entry in state.mid_term_summaries:
            entry["compressed_to_long_term"] = True
            entry["compressed_batch_index"] = batch_index

        long_term_entry = {
            "batch_index": batch_index,
            "query": state.current_query_text,
            "query_start_time": state.query_start_time,
            "source_chunk_indices": source_chunk_indices,
            "source_frame_ranges": source_frame_ranges,
            "source_summary_count": len(source_frame_ranges),
            "compressed_text": compressed_text,
            "inference_time": round(elapsed, 3),
            "token_count_after_append": token_count,
        }
        debug_input_path = self._save_summarizer_debug_input(
            state,
            "long_term",
            batch_index,
            copy.deepcopy(long_term_debug_input),
        )
        if debug_input_path:
            long_term_entry["debug_input_path"] = debug_input_path
        state.long_term_history.append(long_term_entry)

        window = int(self.config.long_term_memory_window or 0)
        if window > 0 and len(state.long_term_history) > window:
            dropped_count = len(state.long_term_history) - window
            del state.long_term_history[:dropped_count]
            state.memory_state["long_term_memory"] = "\n\n".join(
                entry["compressed_text"].rstrip()
                for entry in state.long_term_history
                if entry.get("compressed_text")
            )
            token_count = self.summarizer.estimate_tokens(
                state.memory_state["long_term_memory"]
            )
            long_term_entry["token_count_after_slide"] = token_count

        state.mid_term_summaries.clear()
        LOGGER.info(
            "[%s] long-term compression batch=%d %.3fs tokens=%d",
            state.session_id,
            batch_index,
            elapsed,
            token_count,
        )

    def _async_summary_enabled(self) -> bool:
        return (
            self.summarizer is not None
            and self.config.chunk > 0
            and int(self.config.async_summary_lead_frames or 0) > 0
        )

    def _async_first_summary_turns(self) -> int:
        lead_turns = max(0, int(self.config.async_summary_lead_frames or 0))
        chunk = max(1, int(self.config.chunk or 1))
        return max(1, chunk - lead_turns + 1) if lead_turns > 0 else chunk

    def _append_async_summary_user_message(
        self,
        state: SessionState,
        time_range=None,
        image_path=None,
        query_text=None,
        *,
        time_ranges=None,
        image_paths=None,
    ) -> None:
        if time_ranges is None:
            time_ranges = [time_range] if time_range else []
        if image_paths is None:
            image_paths = [image_path] if image_path else []
        segment = state.async_summary_segment
        for tr, ip in zip(time_ranges, image_paths):
            segment["image_paths"].append(ip)
            segment["frame_time_ranges"].append(tr)
            segment["summarizer_frame_cache"].append({"path": ip})
            segment["frame_count"] += 1
        segment["turn_count"] += 1
        segment["messages"].append(
            self._build_internal_user_message(
                time_ranges=time_ranges,
                image_paths=image_paths,
                query_text=query_text,
            )
        )

    def _submit_async_summary_if_needed(self, state: SessionState) -> None:
        if not self._async_summary_enabled():
            return

        if state.async_next_summary_target_turns <= 0:
            state.async_next_summary_target_turns = self._async_first_summary_turns()
        if state.async_summary_segment["turn_count"] < state.async_next_summary_target_turns:
            return

        segment_snapshot = copy.deepcopy(state.async_summary_segment)
        summary_index = state.async_next_summary_index
        required_turn_count = state.turn_count + max(
            0, int(self.config.async_summary_lead_frames or 0) - 1
        )
        task = asyncio.create_task(
            asyncio.to_thread(
                self._build_mid_term_summary_entry,
                state,
                segment_snapshot,
                summary_index,
                state.current_query_text or "",
                state.query_start_time,
            )
        )
        state.async_pending_summary_jobs.append(
            {
                "summary_index": summary_index,
                "submitted_turn_count": state.turn_count,
                "submitted_frame_count": state.frame_count,
                "required_turn_count": required_turn_count,
                "task": task,
            }
        )
        LOGGER.info(
            "[%s] submitted async mid-summary %d at turn=%d required_by_turn=%d",
            state.session_id,
            summary_index,
            state.turn_count,
            required_turn_count,
        )

        state.async_summary_segment = reset_chunk_state()
        state.async_next_summary_index += 1
        state.async_next_summary_target_turns = max(1, int(self.config.chunk or 1))

    async def _commit_required_async_summaries(
        self,
        state: SessionState,
        upto_turn_count: Optional[int] = None,
        wait_all: bool = False,
        non_blocking: bool = False,
    ) -> None:
        if not self._async_summary_enabled():
            return

        while state.async_pending_summary_jobs:
            job = state.async_pending_summary_jobs[0]
            is_required = wait_all or (
                upto_turn_count is not None
                and job["required_turn_count"] <= upto_turn_count
            )
            if not is_required:
                break

            if non_blocking and not job["task"].done():
                break

            wait_start = time.time()
            mid_term_entry, summary_time = await job["task"]
            wait_time = time.time() - wait_start
            mid_term_entry["async_summary"] = True
            mid_term_entry["turn_count"] = job.get("submitted_turn_count", 0)
            mid_term_entry["submitted_turn_count"] = job["submitted_turn_count"]
            mid_term_entry["submitted_frame_count"] = job["submitted_frame_count"]
            mid_term_entry["required_turn_count"] = job["required_turn_count"]
            mid_term_entry["barrier_wait_time"] = round(wait_time, 3)
            state.async_pending_summary_jobs.pop(0)

            state.mid_term_summaries.append(mid_term_entry)
            state.mid_term_history.append(mid_term_entry)
            LOGGER.info(
                "[%s] committed async mid-summary %d range=%s wait=%.3fs (%d/%d buffered)",
                state.session_id,
                mid_term_entry["chunk_index"],
                mid_term_entry["frame_range"],
                wait_time,
                len(state.mid_term_summaries),
                self.config.compress_every_n_chunks,
            )
            if len(state.mid_term_summaries) >= self.config.compress_every_n_chunks:
                await asyncio.to_thread(self._compress_mid_terms, state)
