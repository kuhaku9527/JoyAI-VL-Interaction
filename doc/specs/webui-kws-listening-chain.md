# WebUI KWS Listening Chain Spec

## Problem Statement

当前 webui 已经可以用纸飞机测试文本到 LLM/TTS，也可以用红色麦克风按钮做一次性 ASR 输入，但这两条都不是 Jarvis 常驻监听链路。页面上的 `KWS OK` 只证明 KWS 模型文件存在，不证明浏览器麦克风音频已经持续送进 Jarvis KWS。用户无法验证“喊 BT -> 唤醒 -> 识别 -> LLM -> TTS”的真实路径。

## Solution

新增一个独立的 BT 监听入口。监听按钮只负责启动/停止常驻 KWS 链路：浏览器采集麦克风，通过 WebRTC audio-only offer 发给 webui，server 在 `/offer` 里创建 Jarvis session，把远端 audio track 接到 `MicAudioTrack`，并把 `SpeakerAudioTrack` 加回 peer connection 用于 wake/TTS 播放。状态徽章继续显示 `KWS_LISTENING / WAKE_DETECTED / DIALOG_ACTIVE`，用于判断监听是否真的进入状态机。

## User Stories

1. As a Pilot, I want a dedicated listening button, so that I can test wake-word listening without starting video/VLM analysis.
2. As a Pilot, I want the ASR microphone button to remain a one-shot dictation input, so that it does not masquerade as the always-on KWS listener.
3. As a Pilot, I want `KWS_LISTENING`, `WAKE_DETECTED`, and `DIALOG_ACTIVE` visible in the header, so that I can see whether BT actually woke up.
4. As a Pilot, I want stopping listening to tear down the Jarvis session cleanly, so that stale `DIALOG_ACTIVE` state does not pollute the next wake test.
5. As a developer, I want `/offer` to bind incoming audio tracks to Jarvis and outgoing speaker tracks to WebRTC, so that browser audio is the public seam for KWS e2e testing.
6. As a developer, I want KWS sweep results to reset stream state per wav, so that recall/FAR numbers are trustworthy before changing thresholds.

## Implementation Decisions

- WebUI remains the chain-test surface; no `services/voice-ui` thin shell.
- Red Start remains scoped to video/VLM analysis.
- The red microphone remains scoped to ASR dictation into the prompt box.
- The new listening button owns the always-on KWS path and creates a WebRTC audio-only session.
- `/offer` must support audio tracks by creating or reusing a Jarvis session, wrapping browser audio in `MicAudioTrack`, and adding `SpeakerAudioTrack` back to the peer connection.
- Stopping listening calls `/api/jarvis/stop` for the current session after closing the peer connection and local microphone tracks.
- KWS parameter decisions must be based on a sweep that resets KWS state per wav file.

## Testing Decisions

- Test the backend at the `/offer` binding seam by factoring the track binding into a helper that can be exercised with fake peer connections and fake tracks.
- Keep frontend coverage as static contract tests because the webui is a single inline HTML/JS file.
- Test that the frontend has one dedicated listening entry and that webcam video still uses `audio:false`.
- Test that KWS sweep calls `kws.start()` before every wav in both positive and negative sets.

## Out of Scope

- Replacing the existing red microphone ASR implementation.
- Reworking VLM/video inference.
- Retraining KWS v5.
- Optimizing LLM/TTS latency before the wake chain is physically connected.

## Further Notes

Manual completion requires a real microphone test: start listening, say "BT", observe `WAKE_DETECTED` then `DIALOG_ACTIVE`, and confirm either wake/TTS audio or visible Pilot/BT messages. Automated tests can prove the code path is wired, but not that the user's physical microphone and NVIDIA Broadcast path produce a wake hit.

> **标注（审查组 2026-07-29）**：本 spec 无独立 ADR 链接，但前提仍有效——KWS = sherpa-onnx 进程内、本地部署（见 `决策/服务-语音栈.md` D-047 上下文）。按审计结论留档不改正文；如需追溯，配套决策为 `决策/服务-语音栈.md`。