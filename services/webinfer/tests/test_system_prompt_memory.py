"""Unit tests for compose_system_prompt_with_memory (memory-store v0.2)."""

import pytest

from system_prompts import (
    _clip_memory_blocks,
    compose_system_prompt,
    compose_system_prompt_with_memory,
)


def test_empty_memory_blocks_returns_plain_compose():
    base = "BASE"
    out = compose_system_prompt_with_memory(
        base, character_prompts=["P1"], language="en", memory_blocks=[]
    )
    assert out == compose_system_prompt(base, ["P1"], "en")


def test_none_memory_blocks_returns_plain_compose():
    out = compose_system_prompt_with_memory(
        "BASE", character_prompts=None, language="en", memory_blocks=None
    )
    assert out == compose_system_prompt("BASE", None, "en")


def test_chinese_header_for_zh_language():
    blocks = [{"block_id": "a1", "content": "Pilot training done", "score": 0.9}]
    out = compose_system_prompt_with_memory(
        "BASE", character_prompts=None, language="zh-CN", memory_blocks=blocks
    )
    # Chinese header should contain "\u672c\u5730\u77e5\u8bc6\u5e93"
    assert '\u672c\u5730\u77e5\u8bc6\u5e93' in out
    assert "(id=a1)" in out
    assert "Pilot training done" in out


def test_english_header_for_default_language():
    blocks = [{"content": "We talked about Titan loadouts", "score": 0.7}]
    out = compose_system_prompt_with_memory(
        "BASE", character_prompts=None, language="en", memory_blocks=blocks
    )
    assert "[Local Wiki]" in out
    assert "Titan loadouts" in out


def test_clip_drops_oversized_block_with_ellipsis():
    huge = "x" * 1500
    out = _clip_memory_blocks([{"content": huge}], "en")
    assert "\u2026" in out
    assert len(out) < 1200


def test_clip_total_capped():
    blocks = [{"content": "y" * 500} for _ in range(20)]
    out = _clip_memory_blocks(blocks, "en")
    assert len(out) < 4500


def test_clip_skips_non_dict_and_empty():
    out = _clip_memory_blocks([None, {}, {"content": "  "}, {"content": "real"}], "en")
    assert "real" in out
    assert out.count("- ") == 1


def test_clip_uses_block_id_when_present():
    out = _clip_memory_blocks(
        [{"block_id": "abc-123", "content": "hi", "score": 1.0}], "en"
    )
    assert "(id=abc-123)" in out
    assert "hi" in out