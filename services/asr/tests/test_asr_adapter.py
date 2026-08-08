# SPDX-License-Identifier: Apache-2.0

"""Tests for the ASR websocket adapter's cloud-provider header support."""

from __future__ import annotations

import wave
from io import BytesIO

import pytest
from asr_adapter import Settings, transcribe_with_vllm


def _silent_wav_bytes(duration_ms: int = 500, sample_rate: int = 16000) -> bytes:
    """Return a minimal mono PCM16 WAV payload (silence)."""
    n_samples = int(sample_rate * duration_ms / 1000)
    pcm = b"\x00\x00" * n_samples
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


@pytest.mark.anyio
async def test_cloud_api_key_sent_in_authorization_header(httpx_mock):
    """When Settings.api_key is set, the adapter must forward it as Bearer token."""
    settings = Settings(
        upstream_url="https://api.siliconflow.cn/v1/audio/transcriptions",
        model="FunAudioLLM/SenseVoiceSmall",
        api_key="sk-test-key",
    )

    httpx_mock.add_response(
        url=settings.upstream_url,
        method="POST",
        json={"text": "你好"},
        status_code=200,
    )

    text = await transcribe_with_vllm(_silent_wav_bytes(), 16000, settings)

    assert text == "你好"
    request = httpx_mock.get_request()
    assert request.headers["Authorization"] == "Bearer sk-test-key"
    # model is still sent as form-data
    assert b'name="model"\r\n\r\nFunAudioLLM/SenseVoiceSmall' in request.content


@pytest.mark.anyio
async def test_local_upstream_no_api_key_header(httpx_mock):
    """When Settings.api_key is empty, no Authorization header is sent (local default)."""
    settings = Settings(
        upstream_url="http://127.0.0.1:8993/v1/audio/transcriptions",
        model="Qwen/Qwen3-ASR-1.7B",
        api_key="",
    )

    httpx_mock.add_response(
        url=settings.upstream_url,
        method="POST",
        json={"text": "hello"},
        status_code=200,
    )

    text = await transcribe_with_vllm(_silent_wav_bytes(), 16000, settings)

    assert text == "hello"
    request = httpx_mock.get_request()
    assert "Authorization" not in request.headers
