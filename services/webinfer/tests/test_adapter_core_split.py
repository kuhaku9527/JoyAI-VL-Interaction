"""Contract test locking the Milestone-2 ``adapter_core`` structure split.

After the mechanical split of the former 1992-line ``adapter_core`` monolith
into five single-responsibility mixins (``session``, ``prompt_assembly``,
``memory_io``, ``summarizer_routing``, ``infer_loop``) plus a thin coordinator
facade, this test pins the *external contract* that must stay intact:

* ``StreamingInferAdapter`` is still importable from ``live_adapter``;
* its MRO order is exactly the designed mixin order
  (Session -> InferLoop -> SummarizerRouting -> MemoryIO -> PromptAssembly);
* every method named in design §2.1 (66 numbered) **plus** the 5 extracted
  ``_chat_payload_*`` sub-steps is present on the class;
* ``live_adapter.__all__`` still re-exports the 10 private helpers (§7.2);
* ``__init__.__globals__`` carries ``AdapterConfig`` / ``SessionState``.

This is a regression guard: if a future refactor drops a method, changes the
MRO, or removes a re-exported symbol, this test must fail loudly.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from infer_loop import InferLoopMixin  # noqa: E402
from live_adapter import StreamingInferAdapter  # noqa: E402
from live_adapter import __all__ as LIVE_ADAPTER_ALL  # noqa: E402
from memory_io import MemoryIOMixin  # noqa: E402
from prompt_assembly import PromptAssemblyMixin  # noqa: E402
from session import SessionMixin  # noqa: E402
from summarizer_routing import SummarizerRoutingMixin  # noqa: E402

# 66 methods from design §2.1, in mixin landing order, plus the 5 extracted
# ``_chat_payload_*`` sub-steps (§7.3) which are also part of the new surface.
SPLIT_METHOD_NAMES = [
    "__init__",
    # session.py — SessionMixin (25)
    "get_session",
    "_cleanup_expired_sessions",
    "_session_cleanup_loop",
    "start_background_tasks",
    "stop_background_tasks",
    "_init_session_dirs",
    "handle_models",
    "handle_health",
    "handle_reset",
    "handle_prompts_active",
    "handle_prompts_reload",
    "_session_output_path",
    "_session_debug_input_dir",
    "_session_sample_data",
    "_memory_trace",
    "_write_json_file",
    "_light_predictions",
    "_strip_base64_images",
    "_write_session_outputs_sync",
    "_write_session_outputs",
    "_on_write_task_done",
    "_flush_session_outputs",
    "_save_live_debug_input",
    "_maybe_save_chunk_start_model_input",
    "_save_summarizer_debug_input",
    # prompt_assembly.py — PromptAssemblyMixin (14)
    "_load_character_profiles",
    "_system_prompt_cache_key",
    "_refresh_character_prompt_mtime",
    "_invalidate_system_prompt_cache",
    "reload_character_prompts",
    "active_character_prompt_paths",
    "_build_system_prompt",
    "_build_memory_prompt",
    "_build_internal_user_message",
    "_build_main_internal_messages",
    "_build_main_api_messages",
    "_build_cached_api_messages",
    "_build_main_http_messages",
    "_main_generation_kwargs",
    # memory_io.py — MemoryIOMixin (5)
    "_memory_warmup",
    "_memory_recall",
    "_memory_push",
    "_update_text_qa_history",
    "_execute_pending_qa_archive",
    # summarizer_routing.py — SummarizerRoutingMixin (9)
    "handle_summarizer_route",
    "_flush_chunk",
    "_build_mid_term_summary_entry",
    "_compress_mid_terms",
    "_async_summary_enabled",
    "_async_first_summary_turns",
    "_append_async_summary_user_message",
    "_submit_async_summary_if_needed",
    "_commit_required_async_summaries",
    # infer_loop.py — InferLoopMixin (12)
    "_resolve_backend",
    "handle_text_chat",
    "_handle_text_payload",
    "handle_chat_completions",
    "_handle_chat_payload",
    "_forward_text_only",
    "_time_range_for_frame",
    "_resolve_frame_ref",
    "_save_base64_frame",
    "_validate_local_image_path",
    "_update_query_state",
    "_call_main_model",
    # extracted _chat_payload_* sub-steps (5, §7.3)
    "_chat_payload_resolve_frames",
    "_chat_payload_advance_chunk",
    "_chat_payload_append_turn",
    "_chat_payload_build_and_infer",
    "_chat_payload_finalize",
]

# §7.2 private helpers that must remain re-exported via live_adapter.__all__
PRIVATE_SYMBOLS_7_2 = [
    "_compute_prompt_guard_max_chars",
    "_estimate_messages_chars",
    "_trim_messages_to_ctx",
    "_env_bool",
    "_env_int",
    "_env_float",
    "_split_paths",
    "_chat_completion_response",
    "_openai_error_response",
    "_short",
]

EXPECTED_MRO = (
    StreamingInferAdapter,
    SessionMixin,
    InferLoopMixin,
    SummarizerRoutingMixin,
    MemoryIOMixin,
    PromptAssemblyMixin,
    object,
)


def test_live_adapter_import_surface():
    """The single public class is still reachable from the facade."""
    import live_adapter

    assert hasattr(live_adapter, "StreamingInferAdapter")
    assert live_adapter.StreamingInferAdapter is StreamingInferAdapter


def test_mro_order_is_design_exact():
    """MRO must be the designed mixin order, end to end."""
    assert StreamingInferAdapter.__mro__ == EXPECTED_MRO, [
        c.__name__ for c in StreamingInferAdapter.__mro__
    ]


def test_all_design_methods_present():
    """Every method named in design §2.1 (+ 5 sub-steps) exists on the class."""
    missing = [name for name in SPLIT_METHOD_NAMES if not hasattr(StreamingInferAdapter, name)]
    assert not missing, f"Missing methods on StreamingInferAdapter: {missing}"
    # 66 numbered methods from §2.1 + 5 extracted _chat_payload_* sub-steps
    assert len(SPLIT_METHOD_NAMES) == 71


@pytest.mark.parametrize("symbol", PRIVATE_SYMBOLS_7_2)
def test_live_adapter_all_includes_private_symbol(symbol):
    """Each §7.2 private helper is re-exported through live_adapter.__all__."""
    assert symbol in LIVE_ADAPTER_ALL


def test_init_globals_carry_config_and_state():
    """The coordinator __init__ module must expose AdapterConfig / SessionState."""
    globals_ns = StreamingInferAdapter.__init__.__globals__
    assert "AdapterConfig" in globals_ns
    assert "SessionState" in globals_ns
    assert globals_ns["AdapterConfig"] is not None
    assert globals_ns["SessionState"] is not None
