"""Regression test for bug #2: VLM Output Info panel too small.

Root cause: the base ``.vlm-history`` rule hard-coded
``height: 420px; max-height: 420px;``. Inside the flex-column
``#vlmOutputCard`` the surrounding ``.vlm-history-shell`` would stretch
to fill the parent, but the inner ``.vlm-history`` stayed 420px — leaving
a large empty area at the bottom of the panel.

Fix contract:
  * The base ``.vlm-history`` rule must use ``flex: 1 1 auto;
    min-height: 0`` so it fills its parent in a flex column.
  * Pixel-based ``height`` / ``max-height`` must not be set on the base
    rule (those belong in the narrow-screen media query only).
"""
from __future__ import annotations

import re
from pathlib import Path

WEBUI_ROOT = Path(__file__).resolve().parents[1]



INDEX_HTML = WEBUI_ROOT / "src" / "joy_interaction_webui" / "static" / "index.html"


def _extract_css_block(html: str, selector: str) -> str:
    """Return the body of the FIRST CSS rule matching ``selector``."""
    pattern = re.compile(
        rf"(?<![\w-]){re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}",
        re.S,
    )
    match = pattern.search(html)
    assert match, f"selector {selector!r} not found in index.html"
    return match.group("body")


def test_vlm_history_base_rule_uses_flex_height():
    """The base .vlm-history rule must flex to fill its parent."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    body = _extract_css_block(html, ".vlm-history")

    # Must declare flex growth so it fills the .vlm-history-shell parent
    assert re.search(r"flex\s*:\s*1\s+1\s+auto", body), (
        f".vlm-history base rule missing `flex: 1 1 auto` (got body: {body!r})"
    )
    assert "min-height: 0" in body, (
        f".vlm-history base rule missing `min-height: 0` (got body: {body!r})"
    )


def test_vlm_history_base_rule_has_no_fixed_pixel_height():
    """Pixel-based height on the base rule traps the panel at 420px."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    body = _extract_css_block(html, ".vlm-history")

    # No fixed pixel height in the base rule. Small-screen media query may
    # still set clamp() values.
    assert not re.search(r"^\s*height\s*:\s*\d+\s*px", body, re.M), (
        f".vlm-history base rule must not pin height in pixels (got body: {body!r})"
    )
    assert not re.search(r"^\s*max-height\s*:\s*\d+\s*px", body, re.M), (
        f".vlm-history base rule must not pin max-height in pixels "
        f"(got body: {body!r})"
    )


def test_vlm_output_card_remains_flex_column_with_min_height_zero():
    """Parent chain must allow the inner .vlm-history to actually fill."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    card_body = _extract_css_block(html, "#vlmOutputCard")
    assert "flex-direction: column" in card_body, "#vlmOutputCard must be a flex column"
    assert "min-height: 0" in card_body, "#vlmOutputCard must allow shrinking"

    shell_body = _extract_css_block(html, ".vlm-history-shell")
    assert "min-height: 0" in shell_body, ".vlm-history-shell must allow shrinking"
    assert re.search(r"flex\s*:\s*1", shell_body), (
        ".vlm-history-shell must grow inside the parent flex column"
    )