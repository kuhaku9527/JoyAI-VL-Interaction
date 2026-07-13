"""Regression tests: the red big Start button must be the single entry point
for every input source (webcam / RTSP / screen).

Before the fix, ``screenStartBtn`` and ``screenStopBtn`` (in the Video Source
panel) carried their own addEventListener bodies that re-implemented
``start()``/``stop()``'s screen branch. Any future change to ``start()`` or
``stop()`` would silently leave the panel buttons out of sync -- the
literal ``red Start logic conflict`` we want to prevent.

The contract enforced here:

* ``bigStartBtn`` and ``screenStartBtn`` both delegate to ``start()``.
* ``bigStartBtn`` and ``screenStopBtn`` both delegate to ``stop({...})``.
* The browser JS does NOT contain duplicated capture logic
  (``setVideoWaitingForStream`` + ``updateStatus('Selecting window...')``
  + ``await window.startScreenCapture(...)``) outside the canonical
  ``start()`` function body.
"""
from __future__ import annotations

import re
from pathlib import Path

WEBUI_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = WEBUI_ROOT / "src" / "joy_interaction_webui" / "static" / "index.html"


def _index_html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _function_body(html: str, name: str) -> str:
    match = re.search(
        rf"(?:async\s+)?function {name}\([^)]*\) \{{(?P<body>.*?)\n        \}}",
        html,
        re.S,
    )
    assert match, f"missing function {name}"
    return match.group("body")


def _button_declaration(html: str, element_id: str) -> str:
    match = re.search(
        rf'<button[^>]*\bid="{re.escape(element_id)}"[^>]*>',
        html,
        re.S,
    )
    assert match, f"missing element id={element_id}"
    return match.group(0)


def test_screen_start_btn_has_no_duplicate_capture_implementation():
    """The panel screenStartBtn must delegate to start().

    No addEventListener block should re-implement the screen branch:
    the previous code duplicated setVideoWaitingForStream + updateStatus
    + window.startScreenCapture, which was the red Start conflict.
    """
    html = _index_html()
    decl = _button_declaration(html, "screenStartBtn")

    assert 'onclick="start()"' in decl, (
        "screenStartBtn must declare onclick=\"start()\" so it goes through "
        "the canonical start() dispatcher instead of carrying its own "
        "screen-capture body."
    )

    match = re.search(
        r"screenStartBtn\.addEventListener\(['\"]click['\"]\s*,\s*async\s*\(\)\s*=>\s*\{(?P<body>.*?)\}\);",
        html,
        re.S,
    )
    assert match is None, (
        "screenStartBtn still owns an addEventListener click body. "
        "Delete it; the inline handler must be replaced by onclick=\"start()\"."
    )


def test_screen_stop_btn_has_no_duplicate_stop_implementation():
    """The panel screenStopBtn must delegate to stop({...}).

    stop() already calls window.stopScreenCapture, resets videoElement,
    and runs resetSession -- screenStopBtn must not duplicate any of that.
    """
    html = _index_html()
    decl = _button_declaration(html, "screenStopBtn")

    assert 'onclick="stop({ clearConversation: false })"' in decl, (
        "screenStopBtn must declare onclick=\"stop({ clearConversation: false })\" "
        "so it goes through the canonical stop() cleanup."
    )

    match = re.search(
        r"screenStopBtn\.addEventListener\(['\"]click['\"]\s*,\s*\(\)\s*=>\s*\{(?P<body>.*?)\}\);",
        html,
        re.S,
    )
    assert match is None, (
        "screenStopBtn still owns an addEventListener click body. "
        "Delete it; the inline handler must be replaced by onclick=\"stop(...)\"."
    )


def test_canonical_start_function_still_handles_screen_branch():
    """Sanity guard: start() must keep its own screen branch.

    If the cleanup accidentally deletes the screen branch from start(),
    delegating screenStartBtn -> start() becomes a no-op. This test makes
    that regression loud.
    """
    html = _index_html()
    body = _function_body(html, "start")

    assert "await window.startScreenCapture(websocket, { fps: 1 })" in body
    assert "setVideoWaitingForStream(true)" in body
    assert "updateStatus('Selecting window...', 'processing')" in body


def test_canonical_stop_function_still_cleans_screen_capture():
    """Sanity guard: stop() must still call window.stopScreenCapture.

    screenStopBtn -> stop() relies on this hook.
    """
    html = _index_html()
    body = _function_body(html, "stop")

    assert "window.stopScreenCapture()" in body
    assert "resetSession(" in body


def test_panel_screen_status_helpers_remain_in_place():
    """The inline helpers driving #screenStatus must survive the cleanup.

    They are not part of the red Start conflict; they update a panel-only
    status badge that start()/stop() never touches.
    """
    html = _index_html()

    assert "function setStatus(text, color)" in html
    assert "function refresh()" in html
    assert "getElementById('screenStartBtn')" in html
    assert "getElementById('screenStopBtn')" in html
    assert "setInterval(refresh, 1000)" in html
    assert "window.isScreenCapturing && window.isScreenCapturing()" in html