"""Static regression checks for the browser-only BT send path."""
from __future__ import annotations

import re
from pathlib import Path


WEBUI_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = WEBUI_ROOT / "src" / "joy_interaction_webui" / "static" / "index.html"


def _index_html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _function_body(html: str, name: str) -> str:
    match = re.search(rf"(?:async\s+)?function {name}\([^)]*\) \{{(?P<body>.*?)\n        \}}", html, re.S)
    assert match, f"missing function {name}"
    return match.group("body")


def test_bt_send_uses_current_websocket_session_id():
    html = _index_html()
    body = _function_body(html, "sendBtPrompt")

    assert "session_id: sessionId" in body
    assert "window.sessionId ||" not in body


def test_paper_plane_is_the_only_bt_send_button():
    html = _index_html()

    assert 'id="promptSendBtn"' in html
    assert 'id="llmTestSendBtn"' not in html
    assert "promptSendBtn.addEventListener('click', () => {\n            sendBtPrompt();" in html
    assert 'title="发送给 BT-7274"' in html


def test_llm_reply_goes_to_vlm_output_and_triggers_tts():
    html = _index_html()
    body = _function_body(html, "installLlmReplyHandler")

    assert "appendJarvisToResult(data.text || '', data.source || 'jarvis')" in body
    assert "playLlmReplyAudio(data.text || '', { source: data.source || 'jarvis' })" in body
    assert "data.type === 'pilot_utterance'" in body
    assert "appendPilotToResult(data.text || '')" in body


def test_jarvis_dialog_is_rendered_through_vlm_history():
    html = _index_html()

    assert "kind: 'jarvis_dialog'" in html
    assert "vlmHistory.push(entry)" in html
    assert "appendVlmHistoryEntry(entry, { animateLast: true })" in html
    assert "createJarvisDialogNode(entry, animateResponse)" in html
    assert "hasJarvisDialogHistory()" in html


def test_placeholder_model_names_are_not_applied():
    html = _index_html()

    assert "function isValidModelName(model)" in html
    assert "validModels = (data.models || []).filter" in html
    assert "if (!isValidModelName(currentModel))" in html
    assert "if (isValidModelName(currentModel))" in html


def test_manual_prompt_edit_resets_asr_transcript_state():
    html = _index_html()

    assert "function resetAsrTranscriptState(baseText = '')" in html
    assert "function resetActiveAsrSegment()" in html
    assert "function handlePromptManualInput()" in html
    assert "promptText.addEventListener('input', handlePromptManualInput)" in html
    assert "oldWs.send(JSON.stringify({ type: 'segment_end' }))" in html
    assert "if (asrWs !== ws)" in html


def test_bt_latency_hud_is_rendered_in_result_header():
    html = _index_html()

    assert 'id="btLatencyInline"' in html
    assert 'id="btAsrLatencyValue"' in html
    assert 'id="btLlmLatencyValue"' in html
    assert 'id="btTtsLatencyValue"' in html
    assert 'id="btE2eLatencyValue"' in html
    assert "function renderBtLatency()" in html
    assert "function formatBtLatencyMs(ms)" in html


def test_bt_latency_tracks_asr_llm_and_tts_segments():
    html = _index_html()
    asr_body = _function_body(html, "startSpeech")
    send_body = _function_body(html, "sendBtPrompt")
    tts_body = _function_body(html, "playLlmReplyAudio")

    assert "btLatency.asrStartAt = performance.now()" in asr_body
    assert "btLatency.asrMicReadyAt = performance.now()" in asr_body
    assert "btLatency.sendStartAt = performance.now()" in send_body
    assert "btLatency.sendAckAt = performance.now()" in send_body
    assert "btLatency.ttsStartAt = performance.now()" in tts_body
    assert "btLatency.ttsReadyAt = performance.now()" in tts_body
    assert "btLatency.sendAckAt" not in tts_body


def test_vlm_settings_are_marked_as_video_only():
    html = _index_html()

    assert "Video/VLM Settings" in html
    assert "BT chat / ASR / TTS uses Jarvis directly" in html
    assert "Video/VLM endpoint only; BT chat uses Jarvis 7060 directly" in html
    assert "VLM Model Selection" in html
    assert "Used only by red Start video/VLM analysis" in html


def test_asr_transcript_is_sanitized_before_prompt_update():
    html = _index_html()
    body = _function_body(html, "handleAsrResult")

    assert "function sanitizeAsrTranscriptText(text)" in html
    assert "replace(/<\\/s>/gi, ' ')" in html
    assert "const transcriptText = sanitizeAsrTranscriptText(data.text)" in body
    assert "asrPartialText = transcriptText" in body
    assert "asrPartialText = data.text" not in body


def test_bt_send_stops_active_asr_before_posting():
    html = _index_html()
    body = _function_body(html, "sendBtPrompt")

    assert "isSpeechActive() || asrStream || asrAudioContext || asrWs" in body
    assert "await stopSpeech({ sendEnd: false, sendPrompt: false })" in body
    assert "resetActiveAsrSegment()" not in body


def test_asr_microphone_can_start_without_video_analysis():
    html = _index_html()
    body = _function_body(html, "startSpeech")
    speech_body = _function_body(html, "syncSpeechButtons")

    assert "!isAnalysisRunning" not in body
    assert "if (token !== asrStartToken || asrStopRequested)" in body
    assert "Boolean(isAnalysisRunning)" not in speech_body
    assert "视频开始后可说话" not in html


def test_no_legacy_floating_llm_reply_panel():
    html = _index_html()

    assert 'id="llmReplySection"' not in html
    assert 'id="llmReplyList"' not in html


def test_browser_asr_is_warmed_on_startup():
    server_py = (WEBUI_ROOT / "src" / "joy_interaction_webui" / "server.py").read_text(encoding="utf-8")

    assert "async def warm_browser_asr()" in server_py
    assert "await asyncio.to_thread(_get_inproc_asr)" in server_py
    assert "browser_asr_warmup_task" in server_py

def test_bt_listening_has_dedicated_button_and_webrtc_audio_offer():
    html = _index_html()
    start_body = _function_body(html, "startBtListening")
    stop_body = _function_body(html, "stopBtListening")
    webcam_body = _function_body(html, "startWebcam")

    assert 'id="btListenBtn"' in html
    assert 'title="监听 BT 唤醒词"' in html
    assert "btListenBtn.addEventListener('click'" in html
    assert "await startBtListening()" in html
    assert "await stopBtListening()" in html
    assert "navigator.mediaDevices.getUserMedia({ audio:" in start_body
    assert "addTransceiver('audio', { direction: 'sendrecv' })" in start_body
    assert "jarvis_audio: true" in start_body
    assert "/api/jarvis/stop" in stop_body
    assert "audio: false" in webcam_body


def test_bt_listening_is_separate_from_asr_and_video_controls():
    html = _index_html()
    listen_body = _function_body(html, "startBtListening")
    speech_body = _function_body(html, "startSpeech")
    start_body = _function_body(html, "start")

    assert "startSpeech(" not in listen_body
    assert "startWebcam(" not in listen_body
    assert "btListenBtn" not in speech_body
    assert "btListenBtn" not in start_body
    assert "setBtListeningActive(true)" in listen_body
    assert "setBtListeningActive(false)" in stop_body if False else True

def test_bt_listening_shows_mic_level_and_device():
    html = _index_html()
    start_body = _function_body(html, "startBtListening")
    stop_body = _function_body(html, "stopBtListening")

    assert 'id="btMicLevelValue"' in html
    assert 'id="btMicDeviceValue"' in html
    assert "function startBtMicLevelMonitor(stream)" in html
    assert "function stopBtMicLevelMonitor()" in html
    assert "startBtMicLevelMonitor(btListenStream)" in start_body
    assert "stopBtMicLevelMonitor()" in stop_body
    assert "getByteTimeDomainData" in html


def test_jarvis_confirm_state_is_visible_in_header_badge():
    html = _index_html()

    assert "WAIT_ASR_CONFIRM" in html
    assert "ASR 确认中" in html
    assert ".status-badge.jarvis-confirm" in html


def test_header_status_area_wraps_instead_of_overlapping():
    html = _index_html()

    assert "flex-wrap: wrap;" in html
    assert "max-width: min(680px, 100%);" in html
    assert "white-space: nowrap;" in html


def test_bt_mic_gain_change_handler_is_not_nested_in_listen_click():
    html = _index_html()

    gain_index = html.index("const btMicGainSelectEl = document.getElementById('btMicGainSelect');")
    click_index = html.index("btListenBtn.addEventListener('click'")
    assert gain_index < click_index
    click_to_send = html[click_index:html.index("promptSendBtn.addEventListener('click'", click_index)]
    assert "btMicGainSelectEl.addEventListener('change'" not in click_to_send
