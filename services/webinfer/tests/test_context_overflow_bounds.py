"""Regression tests for the context-overflow fix (upstream PR #25 port).

These pin the two bounded-memory guards added in
``fix/webinfer-context-overflow-bound`` so the long-session context
overflow (turn 100+ crash) cannot silently regress:

* ``MemoryIOMixin._update_text_qa_history`` must cap ``qa_history`` to
  ``AdapterConfig.qa_history_window`` recent Q&A pairs (root cause 1:
  unbounded append -> every session eventually overflows).
* ``SummarizerRoutingMixin._compress_mid_terms`` must drop the oldest
  ``long_term_history`` batches while their rebuilt token count exceeds
  ``AdapterConfig.long_term_memory_max_tokens`` (root cause 2: only
  count-window trimmed, never recompressed by token budget). The loop
  must also keep ``token_count_after_slide`` defined even when
  ``long_term_memory_window == 0`` (the pre-fix NameError path).

Both mixins have no ``__init__`` of their own; the production
``StreamingInferAdapter`` sets ``self.config`` / ``self.summarizer``. We
recreate that minimal contract directly so the tests stay fast and
don't pull the heavy adapter graph.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapter_types import AdapterConfig, SessionState  # noqa: E402
from memory_io import MemoryIOMixin  # noqa: E402
from summarizer_routing import SummarizerRoutingMixin  # noqa: E402


class _MemIO(MemoryIOMixin):
    """Minimal stand-in: only ``self.config`` is needed by
    ``_update_text_qa_history``."""

    def __init__(self, **cfg):
        self.config = AdapterConfig(**cfg)


class _FakeSummarizer:
    """Deterministic summarizer stub.

    ``estimate_tokens`` mirrors the production fallback (``len // 4``) so
    token budgets are predictable without a real tokenizer.
    ``batch_compress_to_longterm`` returns a fixed compressed text built
    from the in-flight summaries so the new ``long_term_history`` entry
    has a known size.
    """

    def __init__(self, token_fn=None):
        self._token_fn = token_fn or (lambda t: len(t) // 4)

    def batch_compress_to_longterm(self, long_term_memory, mid_term_summaries):
        compressed = "\n".join(s.get("summary", "") for s in mid_term_summaries)
        return compressed, self._token_fn(compressed), compressed, None

    def estimate_tokens(self, text):
        return self._token_fn(text)


class _Router(SummarizerRoutingMixin):
    """Minimal stand-in carrying ``self.config`` + ``self.summarizer``."""

    def __init__(self, **cfg):
        self.config = AdapterConfig(**cfg)
        self.summarizer = _FakeSummarizer()

    def _save_summarizer_debug_input(self, *a, **k):
        return None


def _seed_qa(state, n):
    for i in range(n):
        state.memory_state["qa_history"].append(
            {
                "query_time": f"t{i}",
                "query": f"q{i}",
                "responses": [{"prediction": f"p{i}", "decision": "response"}],
                "archived_in_chunk": None,
                "text_path": True,
            }
        )


def test_qa_history_window_caps_recent_pairs_and_drops_oldest():
    mem = _MemIO(qa_history_window=3)
    state = SessionState(session_id="s", memory_state={"long_term_memory": "", "qa_history": []})
    _seed_qa(state, 5)
    assert len(state.memory_state["qa_history"]) == 5

    mem._update_text_qa_history(
        state,
        [{"role": "user", "content": "new question"}],
        clean_text="new answer",
        decision="response",
    )

    qa = state.memory_state["qa_history"]
    assert len(qa) == 3, qa
    # oldest three (q0,q1,q2) dropped from the head; newest two retained.
    assert qa[0]["query"] == "q3"
    assert qa[-1]["query"] == "new question"


def test_qa_history_window_zero_keeps_unbounded():
    mem = _MemIO(qa_history_window=0)
    state = SessionState(session_id="s", memory_state={"long_term_memory": "", "qa_history": []})
    _seed_qa(state, 5)
    mem._update_text_qa_history(
        state,
        [{"role": "user", "content": "new question"}],
        clean_text="new answer",
        decision="response",
    )
    assert len(state.memory_state["qa_history"]) == 6


def test_qa_history_window_larger_than_len_is_noop():
    mem = _MemIO(qa_history_window=50)
    state = SessionState(session_id="s", memory_state={"long_term_memory": "", "qa_history": []})
    _seed_qa(state, 5)
    mem._update_text_qa_history(
        state,
        [{"role": "user", "content": "new question"}],
        clean_text="new answer",
        decision="response",
    )
    assert len(state.memory_state["qa_history"]) == 6


def _make_state_with_summaries(compressed_texts, new_summary):
    state = SessionState(session_id="s")
    state.long_term_history = [
        {"chunk_index": i, "compressed_text": t, "token_count_after_append": len(t) // 4}
        for i, t in enumerate(compressed_texts)
    ]
    state.mid_term_summaries = [{"chunk_index": 999, "frame_range": [0, 1], "summary": new_summary}]
    state.current_query_text = "q"
    state.query_start_time = "t"
    state.current_chunk = {"response_records": []}
    return state


def test_long_term_memory_token_budget_drops_oldest_batches():
    router = _Router(long_term_memory_window=0, long_term_memory_max_tokens=10)
    # each old batch ~10 tokens (40 chars); 3 old + 1 new = 40 > 10 budget
    state = _make_state_with_summaries(
        compressed_texts=["x" * 40, "x" * 40, "x" * 40], new_summary="y" * 40
    )
    router._compress_mid_terms(state)

    rebuilt = state.memory_state["long_term_memory"]
    assert router.summarizer.estimate_tokens(rebuilt) <= 10
    # loop stops at len == 1 (keeps the newest batch)
    assert len(state.long_term_history) == 1
    assert state.long_term_history[0]["compressed_text"] == "y" * 40


def test_long_term_memory_window_trims_by_count():
    router = _Router(long_term_memory_window=2, long_term_memory_max_tokens=0)
    state = _make_state_with_summaries(compressed_texts=["a", "b", "c", "d", "e"], new_summary="f")
    router._compress_mid_terms(state)
    # window=2 -> keep last 2 (5 old + 1 new = 6 -> trim to 2)
    assert len(state.long_term_history) == 2
    assert state.long_term_history[-1]["compressed_text"] == "f"


def test_token_count_defined_when_window_zero():
    """Pre-fix code only assigned ``token_count`` inside the
    ``window > 0`` branch, so ``long_term_memory_window == 0`` raised
    NameError at ``long_term_entry['token_count_after_slide']``. The fix
    always recomputes it. This test fails on the unpatched code."""
    router = _Router(long_term_memory_window=0, long_term_memory_max_tokens=0)
    state = _make_state_with_summaries(compressed_texts=["hello world"], new_summary="more text")
    router._compress_mid_terms(state)  # must not raise
    last = state.long_term_history[-1]
    assert "token_count_after_slide" in last
    assert isinstance(last["token_count_after_slide"], int)
