# Loose-Coupling 4 Services + Per-Source Capture Modules

## Architecture Principle - single webinfer main path

All capability changes - model switch, summarizer repoint, TTS swap - must flow
through one path: **webui -> webinfer -> branch -> back to webinfer -> back to webui**.
No alternative paths. Features branch off webinfer, do their work, return to
webinfer, and webinfer ships the result to webui. Composition, not duplication.

```
                  +----------------------------------------------+
                  |  webui  (presentational - UI + WS frame)     |
                  +-----------------------+----------------------+
                                          | HTTP/WS
                                          v
                  +----------------------------------------------+
                  |  webinfer  (orchestrator - single main path) |
                  +--+--------+-----------+-----------+----------+
                     |        |           |           |
              +------+   +----+      +----+      +----+
              v          v           v           v
         llama-server  minimax-vl  voice-clone  sherpa-asr
         (LLM)         (Summary)   (TTS)        (ASR)
         7060          cloud       8985         in-process
```

Rationale: when the same capability has two delivery paths, divergence is
inevitable (e.g. one path accumulates qa_history, the other doesn't - see
v3.37 single-entry LLM decision). One path means one place to wire, probe,
audit, swap, and reason about.

## Scope

1. **Per-source capture** (browser side) - each video source owns its lifecycle.
2. **Services config UI** (webui) - 4 API slots (LLM / Summary / TTS / ASR).
3. **Services config propagation** - UI save -> webui storage -> webinfer in-process state.
4. **Phase 2B** - webui `/api/webinfer/summarizer/route` proxies to webinfer
   `/v1/summarizer/route`, which calls `SummarizerModel.update_routing`.
   This is the piece that makes "Summary = cloud" actually hot-swappable.

## Problem Statement

当前 webui UI 把 4 个外部服务（LLM / TTS / Summary / ASR）和 3 个视频源（Webcam / RTSP / Screen Capture）的配置逻辑混在一起：

1. **红 Start 按钮** (`bigStartBtn` + global `start()`) 是单一入口，根据当前 tab 分发到不同 capture 路径。任何人改 webui 都要碰这个全局函数。
2. **Video/VLM Settings 面板** 是「红 Start 触发 VLM 路径」的配置区。但 VLM 在这里是单数概念 - 只有 1 个本地 GGUF 模型（`joyai-vl-interaction-preview`）。
3. **TTS / Summary / ASR** 完全靠环境变量注入（`JARVIS_TTS_API_URL`、`ASR_MODEL`、webinfer 的 `--summarizer-api-base`），UI 上改不了，重启才生效。
4. **Webcam / RTSP / Screen Capture** 用 tab 切换控件，3 个源共享 `start()` / `stop()` 的全局状态机，状态在 `isAnalysisRunning` 这一个变量上纠缠。
5. **Summary 与 LLM 是同一台机器** - 实际生产中 Summary 应走云端 VL（更强的视觉理解 + 不占用本地显存），但目前绑死在本地 llama-server。

## Solution

**用户视角**：UI 上看到的是 4 个独立的 API 配置 + 3 个独立的 Capture 块，每个 Capture 块自带 Start/Stop/状态指示，按下立即生效、互不干扰。红 Start 按钮消失。Summary 默认指向云端 MiniMax-VL。

**架构视角**：把 capture 路径拆成 3 个自治 JS 模块（与现有的 `screen_capture.js` 同形），把 4 个外部服务的 URL/Model 抽到统一的 `services_config` 后端，webui 通过代理调用 webinfer 的内部端点（`/v1/summarizer/route` 等）让配置真正生效。webinfer 仍是单主路。

## User Stories

1. As a **local operator**, I want each video source (Webcam / RTSP / Screen) to be its own self-contained panel with its own Start/Stop, so that I can start Webcam without affecting Screen Capture state.
2. As a **local operator**, I want the red Start button removed from the main view, so that there is no longer an ambiguous "global" start that switches behavior based on a hidden tab state.
3. As a **local operator**, I want to set the LLM API URL and model from the UI, so that I can repoint webui to a different webinfer instance without editing env vars and restarting.
4. As a **local operator**, I want to set the TTS service URL from the UI, so that I can switch between voice-clone / sherpa TTS without restarting webui.
5. As a **local operator**, I want Summary to point at the cloud MiniMax-VL endpoint by default, so that long-term memory summarization uses stronger VL reasoning without consuming local GPU memory.
6. As a **local operator**, I want the Summary URL/Model change in the UI to take effect on the running webinfer process (no restart), so that I can A/B cloud vs. local summarizer.
7. As a **local operator**, I want to set the ASR service from the UI, so that I can switch between sherpa-whisper and other ASR backends without code changes.
8. As a **local operator**, I want to see live OK/ERR status for each of the 4 services after I save a config, so that I can immediately see whether the new endpoint is reachable.
9. As a **local operator**, I want each capture source to write frames to the same WebSocket session, so that all sources are observable in the VLM output area without re-architecting the backend.
10. As a **maintainer**, I want the global `start()` / `stop()` functions removed, so that there is no longer a single point of truth for "what is currently running".
11. As a **maintainer**, I want each capture module to expose `startXxxCapture(ws)`, `stopXxxCapture()`, `isXxxCapturing()`, so that they mirror `screen_capture.js` API and are interchangeable.

## Implementation Decisions

### Phase 2A - capture modules + services config UI + storage (this slice)

**Capture modules (3 files, JS)** - mirror the existing `screen_capture.js` shape.

- `static/capture_webcam.js` - owns `webcamStream` + WebRTC peer connection lifecycle. Exposes `startWebcamCapture(ws, opts)`, `stopWebcamCapture()`, `isWebcamCapturing()`, `getWebcamStream()`, `getWebcamVideo()`. Independent state - no `isAnalysisRunning` global.
- `static/capture_rtsp.js` - owns RTSP playback + WebRTC peer connection. Same shape.
- `static/screen_capture.js` - keep as is. Public API unchanged.

**Index.html** - delete the red Start, the input-source-tabs dispatcher, the Video/VLM Settings panel; replace with 3 self-contained capture panels in the `Video Source` block.

**Services config backend (webui)** -

- `_services_config` module-level dict, default-seeded from env.
- `GET/PUT /api/services/config` - read / write the dict.
- `GET /api/services/status` - runs 4 probes, returns normalized `{ok, reason, endpoint}` for each.
- Default `summary` slot points at cloud MiniMax-VL: `https://api.minimaxi.com/v1` with model `MiniMax-VL-01`. Operators can override to a local llama-server if desired.
- `_propagate_services_to_runtime()` is invoked on PUT. For now it updates in-process state the webui owns (LLM -> VLMService). Summary/TTS/ASR propagation is Phase 2B.

**Services config UI (browser)** - 4 collapsible rows in the `Services` panel, each with URL/Model/API Key inputs + live OK/ERR badge. Save triggers probe.

### Phase 2B - webinfer summarizer routing (next slice)

This is the piece that makes the "single webinfer main path" real for Summary.

**webinfer side** (services/webinfer/live_adapter.py + memory_summarizer.py):

- `SummarizerModel.update_routing(api_base, model_name, api_key)` - mutates `self._client.base_url`, `self.model_name`, and (when api_key is not None) `self._client.api_key`. Preserves `api_key=None` as "leave alone" sentinel.
- `SummarizerModel.snapshot_routing()` - returns `{api_base, model_name, api_key_set: bool}`. Never returns the raw key.
- `POST /v1/summarizer/route` - accepts `{api_base, model_name, api_key}`; calls `update_routing`; returns the new snapshot. 400 on bad JSON. 503 if summarizer is disabled.
- `GET /v1/summarizer/route` - returns the current snapshot. 503 if summarizer disabled.

**webui side** (services/webui/src/joy_interaction_webui/server.py):

- `POST /api/webinfer/summarizer/route` - proxy to webinfer. Reads `_services_config["summary"]` and forwards to webinfer.
- `_propagate_services_to_runtime()` calls this proxy on PUT `summary`.
- `/api/services/status` for `summary` probes the configured `api_base` directly (cheap reachability check). The "is webinfer actually using it?" check is a separate `GET /v1/summarizer/route` round-trip we can add if needed.

This keeps the architecture honest: UI edits the webui-side config, webui proxies to webinfer, webinfer mutates its own state, webinfer stays the single main path.

## State changes

- Drop `isAnalysisRunning`, `peerConnection`, `localStream`, `rtspSessionId` globals. Each capture module owns its state.
- Drop `streamStartToken` - sources don't race any more.
- Drop `processEvery`, `framesPerBatch` - these were global knobs. Per-source if needed later.

## Testing Decisions

- **Services config storage**: `tests/test_services_config_handler.py` (GET / PUT round-trip, schema validation).
- **Services status handler non-blocking**: `tests/test_services_status_handler_nonblocking.py` - assert that 4 slow probes (0.3s each) complete in < 0.6s (parallel via `run_in_executor` + `asyncio.gather`).
- **Capture module contract**: each module exports the canonical start/stop/isCapturing API. Verified by `tests/test_capture_modules_contract.py`.
- **Summarizer routing** (Phase 2B): `tests/test_summarizer_routing.py` pins 6 invariants - `update_routing` mutates clients + model, `snapshot_routing` masks the key, `POST /v1/summarizer/route` returns the new snapshot, `api_key=None` leaves the previous key alone, bad JSON -> 400, summarizer disabled -> 503.

## Out of Scope

- Removing WebRTC entirely. The Webcam module still uses WebRTC for low-latency local preview; the only thing that changes is its lifecycle is now owned by `capture_webcam.js`.
- Changing the BT-7274 pipeline or jarvis_mode.
- Removing the `Video Source` panel name from JS state - purely cosmetic rename.
- Changing LLM endpoint routing - that's v3.37's `/v1/text/chat` vs. `/v1/chat/completions` split, owned by webinfer.
- A "force everything local" mode - Summary is cloud-by-default because that's the product direction; switching to local is a UI config change, not a code change.

## Further Notes

- Naming: this spec aligns with the v3.37 llm-gateway decision (single-entry to LLM). The 4 services here are at a higher level: 4 *external* services that webui orchestrates. Don't conflate with the v3.37 "single-entry LLM" which is about webinfer's internal routing.
- Risk: deleting `#bigStartBtn` + `start()` removes ~160 lines of orchestration. If a user has muscle memory clicking the big Start, this is a UX regression. Mitigation: the 3 new capture panels are visible by default (not collapsed), each with a clear Start button.
- ADR-worthy: yes - three decisions meet all three criteria:
  1. **Delete global start/stop**: hard to reverse if reintroduced; surprising without context (why was the single Start button controversial?); real trade-off (single entry vs N independent state machines).
  2. **Summary default = cloud minimax-vl**: hard to reverse (changes the load profile of local GPU); surprising (today the summarizer is the same llama-server as LLM); real trade-off (cloud cost vs. local GPU contention).
  3. **Single webinfer main path with proxy `/api/webinfer/summarizer/route`**: hard to reverse (it cements webinfer as the orchestrator); surprising (operators might expect webui to write directly to webinfer); real trade-off (composition vs. direct poke).
