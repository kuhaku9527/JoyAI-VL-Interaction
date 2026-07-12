"""End-to-end smoke test for the local voice-clone service.

Run from the repository root after starting voice-clone:
    python services\\scripts\\smoke_voice_clone.py
"""

from __future__ import annotations

import base64
import os
import sys
import time
import wave
from pathlib import Path

import httpx


PROBE_URL = os.environ.get("SMOKE_TTS_URL", "http://127.0.0.1:8985/v1/synthesize")
VOICE_ID = os.environ.get("TTS_DEFAULT_VOICE_ID", "minimax_man_33333")
TEXT = os.environ.get("SMOKE_TTS_TEXT", "铁御，BT-7274 就绪，准备展开作业二一七。")


def _short_body(resp: httpx.Response) -> str:
    try:
        return resp.text[:1000]
    except Exception:  # pragma: no cover - defensive against broken response objects
        return "<unreadable response body>"


def main() -> int:
    print(f"smoke test -> {PROBE_URL}")
    print(f"voice_id    = {VOICE_ID}")
    print(f"text        = {TEXT!r}")
    try:
        resp = httpx.post(
            PROBE_URL,
            json={"text": TEXT, "voice_id": VOICE_ID, "streaming": False},
            timeout=60.0,
        )
    except httpx.HTTPError as err:
        print(f"FATAL: cannot reach {PROBE_URL}: {err}")
        print("Hint: start voice-clone first: powershell -File start-joyai.ps1 -Mode voice")
        return 2

    print(f"HTTP {resp.status_code}  ({len(resp.content)} bytes)")
    if resp.status_code != 200:
        body = _short_body(resp)
        print("Response body:")
        print(body)
        if "1004" in body:
            print()
            print("DIAGNOSIS: MiniMax rejected the Bearer token (login fail / 1004).")
            print("Check MINIMAX_API_KEY and make sure the running process loaded the new env.")
        if "not found" in body.lower() or "404" in body:
            print()
            print("DIAGNOSIS: local voice_id was not found. In MiniMax mode direct cloud voice_id is supported; restart voice-clone after updating code/env.")
        return 1

    payload = resp.json()
    audio_b64 = payload.get("pcm16_base64") or payload.get("audio_base64")
    if not audio_b64:
        print("FATAL: 200 but no audio payload")
        print(_short_body(resp))
        return 1

    try:
        pcm = base64.b64decode(audio_b64, validate=True)
    except ValueError as err:
        print(f"FATAL: invalid base64 audio payload: {err}")
        return 1

    sample_rate = int(payload.get("sample_rate") or 24000)
    print(f"audio bytes = {len(pcm)}")
    out_path = Path("services") / "scripts" / f"smoke_{int(time.time())}.wav"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    print(f"saved -> {out_path}")
    print("OK  smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
