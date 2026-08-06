"""Tests for the Smart Turn semantic end-of-turn adapter.

Mirrors the memory-store bge-m3 local-weight convention: the ONNX asset is
optional. Without it the adapter is fail-open (never crashes, never fakes), and
the golden end-to-turn cases auto-skip until the asset is fetched from
HuggingFace (pipecat-ai/smart-turn-v3.2).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from joy_interaction_webui.smart_turn_adapter import (  # noqa: E402
    GOLDEN_CASES,
    MODEL_DIR,
    MODEL_FILENAME,
    SmartTurnAdapter,
)

MODEL_PATH = MODEL_DIR / MODEL_FILENAME
HAS_MODEL = MODEL_PATH.exists()


def test_adapter_fail_open_when_model_absent():
    adapter = SmartTurnAdapter()
    assert adapter.available is False
    # Must not raise; returns neutral (False, 0.0) so acoustic endpoint rules.
    complete, prob = adapter.is_end_of_turn(b"\x00\x00" * 100, "嗯……那个")
    assert complete is False
    assert prob == 0.0


def test_golden_cases_defined():
    assert len(GOLDEN_CASES) == 3
    labels = {c[0] for c in GOLDEN_CASES}
    assert {"trailing_thought", "explicit_end", "normal_sentence"} <= labels


@pytest.mark.skipif(not HAS_MODEL, reason="smart-turn ONNX asset not fetched")
def test_golden_cases_with_model():
    adapter = SmartTurnAdapter()
    assert adapter.available is True
    for label, transcript, expected in GOLDEN_CASES:
        complete, _prob = adapter.is_end_of_turn(b"\x00\x00" * 100, transcript)
        assert complete == expected, f"golden {label}: expected {expected}, got {complete}"
