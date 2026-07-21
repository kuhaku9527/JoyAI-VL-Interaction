"""Prompt-assembly mixin: character-profile cache, system/memory prompts, and main message assembly.

Defines :class:`PromptAssemblyMixin`, which carries the role-prompt assembly,
character-profile caching, memory-prompt construction, main message-body
assembly, and generation-kwargs helpers previously on ``StreamingInferAdapter``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from adapter_types import SessionState
from io_utils import _extract_extra_body, _internal_message_to_openai
from prompt_building import (
    _build_system_prompt,
    _estimate_messages_chars,
    _get_i18n,
    _trim_messages_to_ctx,
    build_dynamic_system_content,
    build_static_system_content,
)
from system_prompts import (
    compose_system_prompt_with_memory,
    load_character_prompts,
    resolve_prompt_paths,
)
from time_ranges import _format_batch_time_marker

LOGGER = logging.getLogger("streaming_infer_adapter")


class PromptAssemblyMixin:
    """Role-prompt assembly and main message construction."""

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
