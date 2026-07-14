"""Regression: build_dynamic_system_content must not blow up on
qa_history entries whose ``archived_in_chunk`` is ``None``.

Before the fix, ``live_adapter.build_dynamic_system_content`` filtered with
``entry.get("archived_in_chunk", 0) < current_chunk_index``. ``dict.get(key,
default)`` only applies the default when the key is **missing**; an entry
that was created with ``archived_in_chunk: None`` (the default written by
``_update_text_qa_history`` for a fresh turn) made the comparison
``None < int`` and raised ``TypeError`` -- which the surrounding
``handle_chat_completions`` swallowed and turned into ``502 Bad Gateway``
to the browser. Visible to users as ``[LLM error: Server error '502 Bad
Gateway' for url 'http://127.0.0.1:8070/v1/chat/completions']``.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from live_adapter import build_dynamic_system_content  # noqa: E402


def test_none_archived_in_chunk_does_not_raise():
    memory_state = {
        "long_term_memory": "",
        "qa_history": [{
            "query": "what is in the frame?",
            "query_time": "2026-07-14T00:00:00",
            "responses": [["2026-07-14T00:00:01",
                            {"prediction": "hi", "decision": "response"}]],
            "archived_in_chunk": None,
            "text_path": True,
        }],
    }
    out = build_dynamic_system_content(
        current_query_text="what is in the frame?",
        memory_state=memory_state, current_chunk_index=2, language="en",
    )
    assert "what is in the frame?" in out
    assert "hi" in out


def test_zero_archived_in_chunk_is_treated_as_fresh():
    memory_state = {"long_term_memory": "", "qa_history": [{
        "query": "q1", "query_time": "t1",
        "responses": [["rt", {"prediction": "p", "decision": "response"}]],
        "archived_in_chunk": 0, "text_path": True,
    }]}
    out = build_dynamic_system_content(
        current_query_text="q1", memory_state=memory_state,
        current_chunk_index=2, language="en",
    )
    assert "q1" in out


def test_current_chunk_entry_drops_out_of_prompt():
    """Entry whose archived_in_chunk equals current_chunk_index is the
    in-flight turn and must be excluded from its own prompt (strict <)."""
    memory_state = {"long_term_memory": "", "qa_history": [{
        "query": "in-flight", "query_time": "t1",
        "responses": [["rt", {"prediction": "p", "decision": "response"}]],
        "archived_in_chunk": 2, "text_path": True,
    }]}
    out = build_dynamic_system_content(
        current_query_text="current", memory_state=memory_state,
        current_chunk_index=2, language="en",
    )
    assert "in-flight" not in out


def test_prior_chunk_entry_is_kept_in_prompt():
    """Entry from a prior chunk (archived_in_chunk < current_chunk_index)
    must remain visible so the model has cross-turn context."""
    memory_state = {"long_term_memory": "", "qa_history": [{
        "query": "prior-turn-context", "query_time": "t1",
        "responses": [["rt", {"prediction": "p", "decision": "response"}]],
        "archived_in_chunk": 1, "text_path": True,
    }]}
    out = build_dynamic_system_content(
        current_query_text="current", memory_state=memory_state,
        current_chunk_index=2, language="en",
    )
    assert "prior-turn-context" in out


def test_missing_archived_in_chunk_key_is_treated_as_fresh():
    memory_state = {"long_term_memory": "", "qa_history": [{
        "query": "fresh entry", "query_time": "t1",
        "responses": [["rt", {"prediction": "p", "decision": "response"}]],
        "text_path": True,
    }]}
    out = build_dynamic_system_content(
        current_query_text="fresh entry", memory_state=memory_state,
        current_chunk_index=2, language="en",
    )
    assert "fresh entry" in out
