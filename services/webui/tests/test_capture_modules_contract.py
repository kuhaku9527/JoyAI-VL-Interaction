"""Contract test: each video source exposes a uniform capture API.

The red Start button (Phase 1) and the 3-tab dispatcher were replaced
by 3 self-contained capture modules. They must each export the same
shape so the sidebar code can call them interchangeably.

    startXxxCapture(ws, opts?) -> Promise<void>
    stopXxxCapture()            -> void
    isXxxCapturing()            -> boolean
    getXxxStream()              -> MediaStream | null  (where applicable)
    getXxxVideo()               -> HTMLVideoElement | null  (where applicable)

This test pins the public API surface. If a future refactor drops
one of these functions, the test fails and the sidebar handler for
that source breaks visibly.
"""
from __future__ import annotations

import re
from pathlib import Path


WEBUI_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = WEBUI_ROOT / "src" / "joy_interaction_webui" / "static"


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def test_capture_webcam_exposes_public_api():
    src = _read("capture_webcam.js")
    for fn in (
        "window.startWebcamCapture",
        "window.stopWebcamCapture",
        "window.isWebcamCapturing",
        "window.getWebcamStream",
        "window.getWebcamVideo",
    ):
        assert fn in src, "missing " + fn + " in capture_webcam.js"
    assert "window.localStream" not in src, "capture_webcam.js must not export localStream"
    assert "function startWebcam(" not in src, "capture_webcam.js must not define legacy startWebcam"


def test_capture_rtsp_exposes_public_api():
    src = _read("capture_rtsp.js")
    for fn in (
        "window.startRtspCapture",
        "window.stopRtspCapture",
        "window.isRtspCapturing",
        "window.getRtspStream",
    ):
        assert fn in src, "missing " + fn + " in capture_rtsp.js"
    assert "function startRTSP(" not in src, "capture_rtsp.js must not define legacy startRTSP"


def test_screen_capture_exposes_public_api():
    src = _read("screen_capture.js")
    for fn in (
        "window.startScreenCapture",
        "window.stopScreenCapture",
        "window.isScreenCapturing",
        "window.getScreenCaptureStream",
        "window.getScreenCaptureVideo",
    ):
        assert fn in src, "missing " + fn + " in screen_capture.js"


def test_modules_do_not_share_globals():
    """Phase 1 shared localStream/peerConnection across sources.
    New design keeps each module state in an IIFE closure.
    """
    for name in ("capture_webcam.js", "capture_rtsp.js", "screen_capture.js"):
        src = _read(name)
        assert "(function () {" in src, name + " missing IIFE wrapper"
        assert re.search(r"^\s*function start\s*\(", src, re.M) is None, (
            name + " must not define a global start() function"
        )
        assert re.search(r"^\s*function stop\s*\(", src, re.M) is None, (
            name + " must not define a global stop() function"
        )


def test_index_html_loads_all_three_capture_modules():
    html = _read("index.html")
    for name in ("capture_webcam.js", "capture_rtsp.js", "screen_capture.js"):
        needle = chr(34)  # double quote
        if chr(34) + name + chr(34) not in html and ("./" + name) not in html:
            raise AssertionError("index.html must <script src=...> load " + name)


def test_index_html_has_no_global_red_start_dispatcher():
    """Phase 1: index.html had function start() and function stop() that
    dispatched on the active tab. The new design removes both; the
    sidebar handler is per-source and lives inline.
    """
    html = _read("index.html")
    assert re.search(r"^\s*async function start\s*\(", html, re.M) is None, (
        "index.html must not define a global async function start()"
    )
    assert re.search(r"^\s*function stop\s*\(", html, re.M) is None, (
        "index.html must not define a global function stop()"
    )
    assert chr(34) + "bigStartBtn" + chr(34) not in html, "red bigStartBtn must be removed"
    assert chr(34) + "smallStopBtn" + chr(34) not in html, "smallStopBtn must be removed"
    assert "Video/VLM Settings" not in html, "Video/VLM Settings panel must be removed"
