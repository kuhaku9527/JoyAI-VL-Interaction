# WebUI ASR Input State Spec

## Problem Statement

用户在 webui 测试语音链路时，红色麦克风 ASR 会把旧识别内容或持续 partial 写回输入框。页面表现为：输入框被长文本撑满，`VLM Output Info` 里出现大段难以观察的 Pilot 文本，发送后输入框仍继续被录音内容填充。用户无法判断当前是空闲、识别中、已发送，还是旧缓存复活。

## Solution

webui 的红色麦克风作为独立 ASR 测试入口，不依赖红色 Start 视频/VLM 状态。文本/ASR 发送统一走纸飞机 `sendBtPrompt()`；发送时停止正在进行的 ASR 录音，清空前端 ASR 状态，并把当前文本发给 `/api/llm/message`。ASR partial/final 写入输入框前清理模型控制 token（例如 `</s>`）。后端 in-process sherpa fallback 每次 websocket 连接重置 stream，避免上一轮 `last_text` 复活。

## User Stories

1. As a Pilot, I want the microphone button to start ASR without pressing the red Start button, so that I can test voice input without starting video analysis.
2. As a Pilot, I want the paper-plane send button to stop active ASR before posting text, so that the input box does not refill immediately after I send.
3. As a Pilot, I want ASR control tokens to be hidden from the input box, so that prompts sent to BT-7274 are readable.
4. As a Pilot, I want stale ASR fallback text cleared on each new ASR session, so that old dictation cannot reappear as new speech.
5. As a developer, I want static contract tests around the webui send path, so that duplicate buttons and old video gates do not regress.

## Implementation Decisions

- Keep webui as the chain-test surface; do not revive the thin voice-ui shell.
- Keep paper plane as the only text/ASR send entry point.
- `sendBtPrompt()` owns the transition from dictation to request: stop ASR, clear ASR state, append Pilot text, POST to LLM.
- ASR frontend text goes through a sanitizer before reaching `promptText`.
- The in-process ASR fallback may reuse the loaded recognizer, but every browser websocket must begin with a fresh stream.
- Red Start remains scoped to video/VLM analysis and is not required for browser microphone ASR.

## Testing Decisions

- Use static webui contract tests for browser-only behavior because the fragile surface is inline `index.html` JavaScript.
- Use an in-process fallback unit test to verify `connect_asr_inproc()` resets a reused engine.
- Keep the highest practical seam at the browser send path: paper plane, ASR state, and `/api/llm/message` must remain aligned.

## Out of Scope

- Replacing sherpa-onnx ASR with cloud ASR.
- Redesigning the entire JoyAI source settings panel.
- Changing KWS wake-word model parameters.
- Reintroducing `webinfer` as a required LLM path for this webui test flow.

## Further Notes

Current runtime must be restarted after backend ASR changes. If port `8099` is still running a process that started before the `asr.py` modification time, browser refresh alone is insufficient.
## Latency HUD Extension

The webui should expose BT chain timings directly in the result header so ASR, LLM, and TTS slowness can be separated during manual testing. The HUD reports browser-observed ASR startup/first partial, LLM send-to-reply, TTS request-to-audio, and end-to-end turn timing. VLM settings remain visible but are labelled as video-only so they are not confused with the Jarvis BT path.

> **标注（审查组 2026-07-29）**：本 spec 假设 ASR 后端为 sherpa-onnx，现 ASR 已改为 **Qwen3-ASR vLLM（本地，`:8993`，见 `决策/服务-语音栈.md` D-045）**，前提已被 D-045 覆盖。webui 交互逻辑（麦克风按钮 / 纸飞机 / 清空 ASR 状态）仍适用，但 ASR 引擎细节以 D-045 为准。按审计结论留档不改正文。