"""Unit tests for ``tts_adapter.strip_markdown``.

These verify that the lightweight pre-TTS Markdown stripper removes the
markers that would otherwise be read aloud by the speech model, while
preserving the underlying natural-language text.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the sibling ``tts_adapter`` module importable. ``tts_adapter`` has
# module-level imports of websockets/fastapi/uvicorn, which must be available
# in the test interpreter (they are, in the joyai-main environment).
TTS_DIR = Path(__file__).resolve().parents[1]
if str(TTS_DIR) not in sys.path:
    sys.path.insert(0, str(TTS_DIR))

from tts_adapter import strip_markdown  # noqa: E402


def test_plain_text_passthrough():
    assert strip_markdown("你好世界") == "你好世界"


def test_empty_string_passthrough():
    assert strip_markdown("") == ""


def test_bold_asterisks_stripped():
    assert strip_markdown("**粗体**") == "粗体"


def test_bold_underscores_stripped():
    assert strip_markdown("__粗体__") == "粗体"


def test_heading_stripped():
    assert strip_markdown("# 标题") == "标题"


def test_italic_asterisk_stripped():
    assert strip_markdown("*斜体*") == "斜体"


def test_inline_code_stripped():
    assert strip_markdown("`代码`") == "代码"


def test_link_keeps_label():
    assert strip_markdown("[标签](http://x.com)") == "标签"


def test_unordered_list_bullet_stripped():
    assert strip_markdown("- 项目") == "项目"


def test_unordered_star_bullet_stripped():
    assert strip_markdown("* 列表项") == "列表项"


def test_block_quote_stripped():
    assert strip_markdown("> 引用") == "引用"


def test_ordered_dot_list_stripped():
    assert strip_markdown("1. 第一") == "第一"


def test_ordered_paren_list_stripped():
    assert strip_markdown("1) 项") == "项"


def test_horizontal_rule_removed():
    assert strip_markdown("---") == ""


def test_horizontal_rule_asterisks_removed():
    assert strip_markdown("***") == ""


def test_fenced_code_block_keeps_inner_text():
    assert strip_markdown("```\n代码内容\n```") == "代码内容"


def test_combined_markdown_stripped():
    text = "# 标题\n- **粗** 和 *斜*"
    assert strip_markdown(text) == "标题 粗 和 斜"


def test_mixed_inline_stripped():
    text = "[标签](http://x.com) 和 **粗** 与 `代码`"
    assert strip_markdown(text) == "标签 和 粗 与 代码"


def test_italic_embedded_in_cjk():
    # Regression: Python's \w matches CJK, so the ASCII-only boundary fix
    # must keep embedded emphasis in Chinese sentences strippable.
    assert strip_markdown("说*强调*吧") == "说强调吧"


def test_underscore_italic_embedded_in_cjk():
    assert strip_markdown("这_强调_词") == "这强调词"


def test_ascii_identifier_not_stripped():
    # Underscores inside ASCII identifiers must survive italic stripping.
    assert strip_markdown("my_var") == "my_var"


def test_indented_heading_stripped():
    assert strip_markdown("  # 标题") == "标题"


def test_indented_bullet_stripped():
    assert strip_markdown("  - 项") == "项"
