"""Facade module for the webinfer adapter.

Keeps the historical import surface of ``live_adapter`` intact (console script
``joyvl-webinfer-adapter = live_adapter:main``, ``python live_adapter.py``, and
``from live_adapter import X`` in tests) while the implementation lives in
focused, single-responsibility submodules. See doc/adr/0007-split-live-adapter.md.
"""
from __future__ import annotations

from adapter_core import StreamingInferAdapter
from adapter_types import AdapterConfig, SessionState
from app import create_app, main, parse_args
from config import _env_bool, _env_float, _env_int, _split_paths, reset_chunk_state
from io_utils import (
    derive_light_out_dir,
    derive_model_output_name,
    resolve_save_dir,
    sanitize_output_name,
)
from prompt_building import (
    _compute_prompt_guard_max_chars,
    _estimate_messages_chars,
    _trim_messages_to_ctx,
    build_dynamic_system_content,
    build_static_system_content,
)
from response_format import (
    _chat_completion_response,
    _openai_error_response,
    _short,
    archive_chunk_response_records,
    build_model_input_record,
    extract_response_payload,
    normalize_model_output,
)

__all__ = [
    # public API
    "AdapterConfig", "SessionState", "reset_chunk_state",
    "normalize_model_output", "extract_response_payload",
    "sanitize_output_name", "derive_model_output_name", "resolve_save_dir", "derive_light_out_dir",
    "build_model_input_record", "build_static_system_content", "build_dynamic_system_content",
    "archive_chunk_response_records", "StreamingInferAdapter",
    "create_app", "parse_args", "main",
    # private helpers referenced by tests (la._xxx)
    "_compute_prompt_guard_max_chars", "_estimate_messages_chars", "_trim_messages_to_ctx",
    "_env_bool", "_env_int", "_env_float", "_split_paths",
    "_chat_completion_response", "_openai_error_response", "_short",
]


if __name__ == "__main__":
    main()
