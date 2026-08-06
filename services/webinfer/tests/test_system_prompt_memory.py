"""Unit tests for compose_system_prompt_with_memory (memory-store v0.2 + ADR-0012 §6)."""

from system_prompts import (
    _clip_memory_blocks,
    _clip_wiki_blocks,
    compose_system_prompt,
    compose_system_prompt_with_memory,
    compose_voice_prompt,
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
    # PR #42 split the header so chat memory uses [Previous Memory] (zh header
    # kept the legacy \u672c\u5730\u77e5\u8bc6\u5e93 wording for backwards
    # compatibility); Local Wiki gets a separate [Local Wiki] section.
    assert "[Previous Memory]" in out
    assert "(id=a1)" in out
    assert "Pilot training done" in out


def test_english_header_for_default_language():
    blocks = [{"content": "We talked about Titan loadouts", "score": 0.7}]
    out = compose_system_prompt_with_memory(
        "BASE", character_prompts=None, language="en", memory_blocks=blocks
    )
    # Chat memory section is now under [Previous Memory]; the [Local Wiki]
    # heading is reserved for the separate wiki section.
    assert "[Previous Memory]" in out
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
    out = _clip_memory_blocks([{"block_id": "abc-123", "content": "hi", "score": 1.0}], "en")
    assert "(id=abc-123)" in out
    assert "hi" in out


# -- Local Wiki section (PR #42 follow-up to ADR-0012 §6) --------------------


def test_wiki_section_rendered_separately_under_local_wiki_header():
    """The [Local Wiki] tag is reserved for the wiki hits — chat memory must
    not include it any more so the two sections stay visually distinct."""
    chat = [{"block_id": "c1", "content": "pilot told me about his day", "score": 0.5}]
    wiki = [
        {
            "block_id": "w1",
            "content": "玛莲妮亚是化圣雪原的圣树boss",
            "namespace": "wiki:elden-ring",
            "source_url": "https://example/Malenia",
        }
    ]
    out = compose_system_prompt_with_memory(
        "BASE", language="zh-CN", memory_blocks=chat, wiki_blocks=wiki
    )
    assert "[Previous Memory]" in out
    assert "[Local Wiki]" in out
    # The wiki section should be rendered *after* the chat memory section.
    assert out.index("[Previous Memory]") < out.index("[Local Wiki]")
    assert "ns=wiki:elden-ring" in out
    assert "src=https://example/Malenia" in out
    assert "玛莲妮亚" in out


def test_wiki_section_skipped_when_empty():
    out = compose_system_prompt_with_memory("BASE", language="en", memory_blocks=[], wiki_blocks=[])
    assert out == compose_system_prompt("BASE", None, "en")
    assert "[Local Wiki]" not in out


def test_clip_wiki_carries_namespace_and_source_url():
    out = _clip_wiki_blocks(
        [
            {
                "block_id": "w1",
                "content": "boss 攻略",
                "namespace": "wiki:elden-ring",
                "source_url": "https://example/Boss",
            }
        ],
        "en",
    )
    assert "ns=wiki:elden-ring" in out
    assert "src=https://example/Boss" in out
    assert "boss 攻略" in out


def test_compose_voice_prompt_appends_tail_without_markdown_rule():
    out = compose_voice_prompt("BASE", character_prompts=["P1"], language="en")
    plain = compose_system_prompt_with_memory("BASE", character_prompts=["P1"], language="en")
    # Reuses the same composition (negative constraint: no separate copy).
    assert out.startswith(plain)
    # Strongest-constraint tail is present and sits at the very end.
    assert "[Voice Output Rules]" in out
    assert "Do NOT use markdown" in out
    assert "Do NOT use action cues like *(laughs)*" in out
    assert out.rstrip().endswith("then call the tool.")


def test_compose_voice_prompt_zh_tail():
    out = compose_voice_prompt("BASE", language="zh-CN")
    assert "[语音输出规则]" in out
    assert "不要使用 markdown" in out
    assert "先说出简短口语回复，再调用工具" in out  # noqa: RUF001 (intentional Chinese fullwidth comma)


def test_compose_voice_prompt_with_tool_section_before_tail():
    out = compose_voice_prompt("BASE", tool_section="TOOLS:\n- search", language="en")
    assert "TOOLS:" in out
    assert out.index("TOOLS:") < out.index("[Voice Output Rules]")


def test_compose_voice_prompt_not_a_separate_copy():
    plain = compose_system_prompt_with_memory("BASE", language="en")
    out = compose_voice_prompt("BASE", language="en")
    assert out.startswith(plain)
