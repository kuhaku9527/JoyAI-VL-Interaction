"""Regression tests for browser ASR in-process fallback state."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class FakeEngine:
    def __init__(self):
        self.last_text = "上一轮识别"
        self.start_count = 0

    def start(self):
        self.start_count += 1
        self.last_text = ""


def test_connect_asr_inproc_resets_shared_engine(monkeypatch):
    from joy_interaction_webui import asr

    engine = FakeEngine()
    monkeypatch.setattr(asr, "_get_inproc_asr", lambda: engine)

    session, returned = asyncio.run(asr.connect_asr_inproc("test-session"))

    assert session is None
    assert returned is engine
    assert engine.start_count == 1
    assert engine.last_text == ""


def test_asr_url_defaults_to_inproc():
    from joy_interaction_webui import asr

    assert asr.ASR_URL == ""
    assert asr.ASR_CONNECT_RETRIES == 0
