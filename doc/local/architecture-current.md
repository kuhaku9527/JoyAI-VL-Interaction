# 项目现状架构图（2026-07-14 代码事实层）

> 本文基于 HEAD = `616b6eb`（v3.37 + 事件循环修复）逐文件核对，
> 不引用 `specs/*.md`。所有图均为可执行的 mermaid。

---

## 1. 整体数据流（一张图）

```mermaid
flowchart LR
    subgraph Browser[浏览器 8099/index.html]
        UI[UI: video / chat / analysis 面板]
        ASR_WS[ASR WS ws://:8099/asr/<sid>]
        MAIN_WS[主 WS /ws<br/>type: update_* / frame / reset_session]
        REST[REST POST /api/llm/message<br/>text + 可选 image_b64]
        SCREEN_CAPTURE[screen_capture.js<br/>type:frame 推 JPEG]
    end

    subgraph WebUI[webui 服务 8099]
        SERVER[server.py:652]
        VP[VideoProcessorTrack :379]
        RTSP[rtsp_track.py:237]
        VLM_SVC[vlm_service.py:688<br/>AsyncOpenAI client]
        JARVIS[jarvis_mode.py:1126<br/>_send_to_llm]
        ASR[asr.py:455]
        TTS[tts.py:340]
        BG[background_model.py:1177]
    end

    subgraph WebInfer[webinfer 服务 8070]
        LA[live_adapter.py:3179]
        TEXT_CHAT[POST /v1/text/chat<br/>纯文本 + 编排]
        CHAT_COMP[POST /v1/chat/completions<br/>多模态]
        STATE[SessionState<br/>qa_history / mid_term / memory]
    end

    subgraph Llama[llama-server 7060]
        LLM[main model + mmproj]
    end

    subgraph Storage[memory-store 8088]
        MEM[SQLite + hooks]
    end

    UI --> ASR_WS --> ASR
    UI --> MAIN_WS --> SERVER
    UI --> REST --> SERVER
    SCREEN_CAPTURE --> MAIN_WS
    SERVER --> VP
    SERVER --> RTSP
    VP --> VLM_SVC
    RTSP --> VLM_SVC
    VLM_SVC -- chat.completions.create --> LA
    SERVER -- llm_message --> JARVIS
    JARVIS -- _send_to_llm image_b64?<br/>text-only? --> LA
    LA --> STATE
    LA --> LLM
    JARVIS --> BG
    BG --> LA
    BG <--> MEM
    ASR --> JARVIS
    JARVIS --> TTS
```

---

## 2. 三条 LLM 入口的真实路径（用户的疑问解答）

```mermaid
flowchart TB
    subgraph entry[webui LLM 入口]
        E1[REST POST /api/llm/message<br/>server.py:402]
        E2[WS type=frame<br/>server.py:171 分支]
    end

    E1 --> JSM[JarvisStateMachine._send_to_llm<br/>jarvis_mode.py:1078]
    JSM --> ROUTE{image_b64 ?}
    ROUTE -- 否 --> TC[POST :8070/v1/text/chat<br/>含 qa_history 累积]
    ROUTE -- 是 --> CC1[POST :8070/v1/chat/completions<br/>无 qa_history 累积]

    E2 --> VPROC[vlm_service.process_frame<br/>vlm_service.py:387]
    VPROC --> ANALYZE[analyze_image<br/>vlm_service.py:141]
    ANALYZE --> CC2[POST :8070/v1/chat/completions<br/>走同一多模态入口]

    TC --> LLM[llama-server :7060]
    CC1 --> LLM
    CC2 --> LLM
```

**事实层面**（不看 spec）：

| 路径 | 触发 | 端点 | 决策 token | qa_history |
| --- | --- | --- | --- | --- |
| 文本对话 | `/api/llm/message` (text-only) | `/v1/text/chat` | 解析 `</silence/response/delegation>` | 累积 |
| 文本+图 (paper-plane) | `/api/llm/message` (image_b64) | `/v1/chat/completions` | 解析 | 不累积 |
| 视频帧 (webcam/RTSP/screen) | WS `type:frame` | `/v1/chat/completions` | 不解析 | 不累积 |

**结论**：用户疑问成立 —— **视频帧路径没有经过 paper-plane 文字-图混合路径**。
两条路径都汇聚到 llama-server :7060（中间都过 webinfer :8070 网关），
但路径 1（jarvis）走 webinfer 的 text path，路径 2（vlm_service）走 webinfer 的 chat-completions path。
这是 v3.37 单入口设计的有意切分：text 才累积对话历史，video 是"观察"语义。

---

## 3. 视频输入三路子流

```mermaid
flowchart LR
    USER[用户点击 bigStartBtn] --> START[start() index.html:9412]
    START --> ACTIVE_TAB{active tab}
    ACTIVE_TAB -- data-source=webcam --> WEBCAM[startWebcam :9491<br/>WebRTC offer → /offer]
    ACTIVE_TAB -- data-source=rtsp --> RTSP[startRTSP :9573<br/>/api/rtsp/start]
    ACTIVE_TAB -- data-source=screen --> SCREEN[startScreenCapture :9467<br/>screen_capture.js]

    WEBCAM --> PC[PeerConnection<br/>视频轨道]
    RTSP --> RTSPTRK[rtsp_track.py VideoProcessorTrack]
    SCREEN --> WS_FRAME[WS type=frame JPEG]

    PC --> VPT[VideoProcessorTrack.recv<br/>video_processor.py]
    RTSPTRK --> VPT
    WS_FRAME -.服务端.-> SVR[server.py:171 frame 分支]
    SVR --> VLM[vlm_service.process_frame]
    VPT --> VLM
    VLM --> LA[/v1/chat/completions/]
```

`VideoProcessorTrack` 接收所有三路视频帧，统一进 `vlm_service.process_frame` →
`analyze_image` → `self.client.chat.completions.create(...)` → webinfer。

---

## 4. 决策 / 委派链路

```mermaid
sequenceDiagram
    participant U as User
    participant JSM as JarvisStateMachine
    participant LA as live_adapter
    participant LLM as llama-server
    participant BG as BackgroundModelService

    U->>JSM: text "帮我查 RTX 5060 Ti 显存占用"
    JSM->>LA: POST /v1/text/chat {messages}
    LA->>LLM: chat.completions
    LLM-->>LA: </delegation> 显卡跑 Qwen3-7B 显存?
    LA-->>JSM: {streamingharness.decision=delegation}
    JSM->>BG: handle_foreground_response(text, delegation_question)
    BG->>LA: POST /v1/chat/completions (multimodal agent)
    LA-->>BG: chunk summary
    BG-->>JSM: background_result_ready
    JSM-->>U: notify_session_llm_reply
```

---

## 5. 模块行数清单（代码层）

| 模块 | 行数 | 角色 |
| --- | --- | --- |
| `live_adapter.py` | 3179 | webinfer 网关 + 编排 |
| `jarvis_mode.py` | 1126 | BT-7274 状态机 |
| `background_model.py` | 1177 | 后台 agent |
| `server.py` | 652 | webui HTTP/WS 入口 |
| `vlm_service.py` | 688 | 视频帧 → LLM 客户端封装 |
| `asr.py` | 455 | 语音识别 |
| `video_processor.py` | 379 | WebRTC/RTSP 视频轨道 |
| `tts.py` | 340 | 语音合成 |
| `jarvis_session.py` | 242 | 会话管理 |
| `rtsp_track.py` | 237 | RTSP → VLM |
| `audio_processor.py` | 180 | 音频处理 |
| `local_file_server.py` | 56 | 静态图片 |

合计 ~24.9k 行 Python + ~9k 行 JS（index.html）。

---

## 6. 与用户预期相比的风险点

| 风险 | 严重度 | 现状 |
| --- | --- | --- |
| 视频帧路径未接 paper-plane 文本合并 | 低（设计有意） | spec §2.2 明确 `/v1/chat/completions` 接受 image，文本+图走 `/api/llm/message` |
| vlm_service 默认 api_base=:8000 与实际 :8070 不一致 | 低 | server.py:446 覆盖 |
| 红色 Start 按钮 = 设计色 `--joy-red` | 无 | CSS 1082-1166 设计意图 |
| `bigStartBtn` 重复实现 | 无 | 仅 9412 一处定义；7594/9434 是 reset / animating 切换 |
| doc/specs 偏多（21 个 .md） | 中 | 7 specs + 6 adr + 3 main + 2 local + 5 deprecated + 2 research |

---

## 7. 当前 HEAD

- `616b6eb` fix(webui): unblock event loop on sync `_probe_tts/_probe_kws`
- `ff79b3b` feat(llm-gateway): v3.37 single-entry point (Option B)
- 工作树 clean，1 ahead of origin/main