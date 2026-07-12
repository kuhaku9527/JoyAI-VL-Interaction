"""Tests for the webui ``POST /api/tts/synthesize`` proxy.

The browser calls this once an ``llm_reply`` WS event arrives so the LLM
text becomes audible even when WebRTC audio streaming is not active (e.g.
text-only test mode, no peer connection). The endpoint wraps the upstream
``voice_clone_api /v1/synthesize`` response (which is base64 PCM16) into a
playable WAV blob for the HTML5 ``<audio>`` element.

Contract:
  body : ``{"text": "..."}``
  200  : ``audio/wav`` bytes, RIFF header
  400  : missing/empty ``text``
  502  : upstream voice_clone_api 5xx / unreachable
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from joy_interaction_webui.server import build_tts_synthesize_payload  # noqa: E402


_SILENCE_PCM = (b"\x00\x00") * 16000


def _b64_silence() -> str:
    return base64.b64encode(_SILENCE_PCM).decode("ascii")


def test_build_payload_wraps_pcm16_in_wav_header():
    """build_tts_synthesize_payload produces a RIFF/WAVE blob from PCM16 base64."""
    upstream_json = {
        "voice_id": "minimax_man_33333",
        "sample_rate": 24000,
        "channels": 1,
        "pcm16_base64": _b64_silence(),
        "duration_sec": 1.0,
        "format": "pcm16",
    }
    wav = build_tts_synthesize_payload(upstream_json)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    # Data chunk size in header must match len(PCM) for a valid WAV
    assert int.from_bytes(wav[4:8], "little") == len(wav) - 8
    assert int.from_bytes(wav[40:44], "little") == len(_SILENCE_PCM)


def test_build_payload_rejects_missing_pcm16_base64():
    """If the upstream response has no pcm16_base64, raise a clear error."""
    import pytest
    with pytest.raises(ValueError, match="pcm16_base64"):
        build_tts_synthesize_payload({"sample_rate": 24000, "channels": 1})


def test_build_payload_uses_default_sample_rate_when_missing():
    """When upstream omits sample_rate, default to 24000 (MiniMax convention)."""
    upstream_json = {
        "voice_id": "minimax_man_33333",
        "channels": 1,
        "pcm16_base64": _b64_silence(),
    }
    wav = build_tts_synthesize_payload(upstream_json)
    # Sample rate field lives at bytes 24..28 (little endian)
    assert int.from_bytes(wav[24:28], "little") == 24000

