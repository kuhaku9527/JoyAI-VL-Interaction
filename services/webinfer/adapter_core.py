"""Coordinator / thin facade for ``StreamingInferAdapter``.

This module defines the single public class :class:`StreamingInferAdapter` as
a composition of five responsibility mixins:

    SessionMixin -> InferLoopMixin -> SummarizerRoutingMixin ->
    MemoryIOMixin -> PromptAssemblyMixin

The mixins live in their own single-responsibility modules
(``session``, ``infer_loop``, ``summarizer_routing``, ``memory_io``,
``prompt_assembly``). This module keeps only the class definition, the
``__init__`` that wires up instance state, and a re-export of the private
helper symbols historically importable from ``adapter_core`` so that
``from adapter_core import <x>`` and ``StreamingInferAdapter.__init__.__globals__``
contracts stay intact. No method bodies live here.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from adapter_types import AdapterConfig, SessionState
from config import _env_bool, _env_float, _env_int, _split_paths
from infer_loop import InferLoopMixin
from memory_io import MemoryIOMixin
from memory_store_client import MemoryStoreClient
from memory_summarizer import SummarizerModel
from openai import AsyncOpenAI
from prompt_assembly import PromptAssemblyMixin

# Re-export private helpers historically importable from this module so the
# ``from adapter_core import <x>`` contract and ``la._xxx`` references keep
# working. These symbols are defined in their milestone-1 source modules.
from prompt_building import (
    _compute_prompt_guard_max_chars,
    _estimate_messages_chars,
    _trim_messages_to_ctx,
)
from response_format import _chat_completion_response, _openai_error_response, _short
from session import SessionMixin
from summarizer_routing import SummarizerRoutingMixin

LOGGER = logging.getLogger("streaming_infer_adapter")


class StreamingInferAdapter(
    SessionMixin,
    InferLoopMixin,
    SummarizerRoutingMixin,
    MemoryIOMixin,
    PromptAssemblyMixin,
):
    """Real-time video-language streaming inference adapter.

    Composed from five single-responsibility mixins via multiple inheritance;
    see the module docstring for the responsibility split. The coordinator role
    (this module) owns only ``__init__`` and the public class identity.
    """
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


__all__ = [
    "StreamingInferAdapter",
    "_chat_completion_response",
    "_compute_prompt_guard_max_chars",
    "_env_bool",
    "_env_float",
    "_env_int",
    "_estimate_messages_chars",
    "_openai_error_response",
    "_short",
    "_split_paths",
    "_trim_messages_to_ctx",
]
