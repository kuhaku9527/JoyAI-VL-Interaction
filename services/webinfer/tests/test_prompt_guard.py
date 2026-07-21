"""Tests for the v3.34 prompt token guard.

The guard exists to keep requests inside the llama-server -c context
window. These tests pin the trim algorithm + the max-chars formula.
"""
from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

# Make the webinfer package importable when running pytest from repo root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import live_adapter as la  # noqa: E402  (after sys.path setup for repo-root pytest runs)


def _msg(role, text):
    return {"role": role, "content": text}


def test_compute_max_chars_zero_when_ctx_disabled():
    assert la._compute_prompt_guard_max_chars(0) == 0
    assert la._compute_prompt_guard_max_chars(-1) == 0
    assert la._compute_prompt_guard_max_chars(None) == 0


def test_compute_max_chars_default_for_16384_ctx():
    # 16384 * 3.0 chars/token * 0.85 safety = 41779
    assert la._compute_prompt_guard_max_chars(16384) == int(16384 * 3.0 * 0.85)


def test_estimate_chars_simple_string_messages():
    msgs = [
        _msg("system", "a" * 100),
        _msg("user", "b" * 50),
    ]
    # 100 + 50 + 2 * 16 (role + json framing) = 182
    assert la._estimate_messages_chars(msgs) == 182


def test_estimate_chars_handles_list_content_with_text_and_image():
    msgs = [
        _msg("system", "ctx"),
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "x" * 200},
                {"type": "image_url", "image_url": "data:..."},
            ],
        },
    ]
    # "ctx" (3) + text (200) + image placeholder (1024) + 2 * 16 framing
    assert la._estimate_messages_chars(msgs) == 3 + 200 + 1024 + 32


def test_estimate_chars_handles_missing_or_invalid_messages():
    assert la._estimate_messages_chars(None) == 0
    assert la._estimate_messages_chars([]) == 0
    # Each iteration still adds the 16-byte framing overhead, so three invalid
    # entries = 48 chars (16 * 3).
    assert la._estimate_messages_chars([None, {}, {"role": "user"}]) == 48


def test_trim_does_nothing_when_within_budget():
    msgs = [_msg("system", "sys"), _msg("user", "u1"), _msg("assistant", "a1")]
    out, removed = la._trim_messages_to_ctx(msgs, max_total_chars=10_000)
    assert out == msgs
    assert removed == 0


def test_trim_drops_oldest_user_assistant_turns_until_under_budget():
    msgs = [
        _msg("system", "sys"),
        _msg("user", "u" * 500),       # big old turn
        _msg("assistant", "a" * 500),
        _msg("user", "u" * 50),         # recent
        _msg("assistant", "a" * 50),    # recent
    ]
    out, removed = la._trim_messages_to_ctx(msgs, max_total_chars=200, min_recent=2)
    assert removed == 2
    assert out[0]["content"] == "sys"
    assert out[-2]["content"] == "u" * 50
    assert out[-1]["content"] == "a" * 50


def test_trim_always_preserves_system_message():
    msgs = [_msg("system", "sys"), _msg("user", "u" * 5000), _msg("assistant", "a" * 5000)]
    out, removed = la._trim_messages_to_ctx(msgs, max_total_chars=100, min_recent=2)
    # System preserved even when turns can't fit
    assert out[0]["content"] == "sys"
    assert removed >= 1


def test_trim_disabled_when_budget_is_zero():
    msgs = [_msg("system", "sys"), _msg("user", "u" * 5000)]
    out, removed = la._trim_messages_to_ctx(msgs, max_total_chars=0)
    assert out == msgs
    assert removed == 0


def test_trim_preserves_at_least_min_recent_turns():
    msgs = [
        _msg("system", "sys"),
        _msg("user", "u" * 1000),
        _msg("user", "u" * 1000),
        _msg("user", "u" * 1000),
    ]
    out, removed = la._trim_messages_to_ctx(msgs, max_total_chars=10, min_recent=2)
    # min_recent=2 -> at least last 2 user turns survive
    assert len(out) >= 3  # system + 2 recent
    assert out[0]["content"] == "sys"


def test_adapter_config_has_main_ctx_tokens_default():
    names = {f.name for f in fields(la.AdapterConfig)}
    assert "main_ctx_tokens" in names
    assert la.AdapterConfig().main_ctx_tokens == 16384
