"""Tests for the Smart Turn semantic end-of-turn adapter.

Mirrors the memory-store bge-m3 local-weight convention: the ONNX asset is
optional. Without it the adapter is fail-open (never crashes, never fakes), and
the golden end-to-turn cases auto-skip until the asset is fetched from
HuggingFace (pipecat-ai/smart-turn-v3).

Semantic calibration note:
  The model is *audio-native* — it consumes a Whisper log-mel spectrogram and
  IGNORES the transcript. Asserting ``complete == expected`` against
  transcript-only golden cases is therefore invalid (the old ``== expected``
  test was removed). Calibrating end-of-turn semantics requires a real
  recording corpus (recorded utterances paired with ground-truth end-of-turn
  judgments), which we do not ship. The tests here are contract smoke tests:
  they verify the adapter never raises, stays fail-open, and returns a valid
  ``(bool, float)`` probability in [0, 1] — whether or not the asset is
  present.
"""

from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

import pytest

WEBUI_SRC = Path(__file__).resolve().parents[1] / "src"
if str(WEBUI_SRC) not in sys.path:
    sys.path.insert(0, str(WEBUI_SRC))

from joy_interaction_webui.smart_turn_adapter import (  # noqa: E402
    GOLDEN_CASES,
    MODEL_DIR,
    MODEL_FILENAME,
    SmartTurnAdapter,
)

MODEL_PATH = MODEL_DIR / MODEL_FILENAME
HAS_MODEL = MODEL_PATH.exists()

# 16kHz mono int16 PCM helper for the contract smoke test.
SR = 16000


def _make_int16_pcm(seconds: float = 0.5, freq_hz: float = 440.0) -> bytes:
    """Synthesize a short 16kHz mono int16 sine tone as raw PCM bytes."""
    n = int(seconds * SR)
    samples = [int(0.3 * 32767 * math.sin(2.0 * math.pi * freq_hz * i / SR)) for i in range(n)]
    return b"".join(struct.pack("<h", s) for s in samples)


@pytest.mark.skipif(
    HAS_MODEL,
    reason="model asset present -> adapter is available, not fail-open; the fail-open path is only exercised when the asset is absent (mirrors the repo's 'auto-skip until asset fetched' convention)",
)
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


def test_smoke_contract_returns_probability_in_range():
    """Contract smoke test: a short synthetic 16kHz mono int16 sine must run
    through the adapter end-to-end (exercising the Whisper log-mel path when
    the ONNX asset is present, or staying fail-open when it is not) and always
    return ``(bool, float)`` with ``prob`` in [0, 1]. Never raises.
    """
    pcm = _make_int16_pcm(0.5)
    adapter = SmartTurnAdapter()
    complete, prob = adapter.is_end_of_turn(pcm, "")
    assert isinstance(complete, bool)
    assert isinstance(prob, float)
    assert 0.0 <= prob <= 1.0
