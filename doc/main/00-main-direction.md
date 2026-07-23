# 主方向与项目定位

> **当前生产链路（2026-07-13 v3.33）**：WebUI `8099` → webinfer `8070`（视频/VLM）→ 本地社区量化 JoyAI llama-server `7060`；v3.33 在 webui 上加了 Screen Capture 本地预览（操作员能在 `<video id="videoElement">` 上看到被捕获的窗口/标签，同时 BT 仍走 1fps WS frame）；Jarvis 文字/语音对话在 WebUI 内直连同一个 `7060`。KWS + Paraformer ASR 固定本地，TTS/声音克隆固定 MiniMax `8985`。
> **MiniMax-only**：不启动 CosyVoice、TTS stub、whisper/asr-adapter 或 tts-adapter；历史端口只在停止脚本中保留，用于清理旧进程。
> **LLM 选型**：主对话/VLM 使用本地社区量化版；云端 LLM 只作为未来 fallback 或 Hermes 委派，不是当前主链路。
> 详见下方阅读优先级和 v3.2 路线图。

---

## §1 核心立场（防止误读）

- **混合架构是主路径**：本地社区量化 LLM/VLM + 本地 sherpa KWS/ASR + MiniMax TTS/声音克隆
- **ASR 走本地**：sherpa-onnx KWS + Paraformer 流式（首字丢失 / 隐私 / 0 网络）；云端 ASR 仅作视频回看 / 字幕转写备选
- **TTS/声音克隆云端唯一**：MiniMax Token Plan；无 stub、无 CosyVoice fallback
- **webinfer 必须保留**：承载视频流、决策 token 和三层进程内记忆；Jarvis 直连 7060 不代表废弃 webinfer
- 阅读本文档可以避免后续开发组误把 API 方向理解为可选项

> ⚠️ **面向后续开发组**：如果项目处于早期 v3.x 阶段，请先读 `00-main-direction.md` §4 v3.2 路线图，确认本阶段主方向。

---

## §2 阅读优先级

| 优先级 | 类别 | 文档 |
|---|---|---|
| 1 | 主方向 | `00-main-direction.md`（本文档） / `api-optimization.md` |
| 2 | 调研 | `token-plan-comparison.md` / `lightweight-replacement.md` |
| 3 | 本地化部署（**降级方案**） | `pm-local.md` / `tech-local.md` / `architecture-local.md` |
| 4 | 子系统 | `doc/subsystems/jarvis-mode.md` / `asr-streaming.md` / `screen-capture.md` / `hermes-integration.md` / `voice-clone.md` / `memory-architecture.md` |
| 5 | 交付与历史 | `../DELIVERY.md` / `deprecated/`（上游残留） |
| 6 | 用户向使用指南 | `gaming-mode.md` |

**为什么这样排**：先理解主方向（API 化）和已落地的设计原则，再看本地化降级方案的细节，最后看子系统实现。直接跳到本地化文档会误以为"本地化是主方向"。

---

## §3 已落地的设计原则（防误读，区别于"未落地路线图"）

| 原则 | 详情 | 文档 |
|---|---|---|
| **混合架构是主路径** | 社区量化 LLM/VLM 本地；TTS/声音克隆 MiniMax；KWS/ASR sherpa 本地 | `api-optimization.md` |
| **声音克隆走 MiniMax 唯一** | MiniMax Rapid Clone（10s 样本 + 99% 相似 + 0 显存）；本地 CosyVoice3 双轨/hybrid 已弃用 | `voice-clone.md` + `api-optimization.md §14` |
| **ASR 走本地** | sherpa-onnx KWS + Paraformer 流式（首字丢失 / 隐私 / 0 网络）；云端 ASR 仅作视频回看/字幕转写备选 | `api-optimization.md §2` + `asr-streaming.md` |
| **Hermes 严格隔离** | shim 只做协议转换；不传 system / 不传 BT-7274 上下文 / 不读 hermes 内部配置 / shim 不维护 provider（用户用 `hermes model` 切换） | `hermes-integration.md` |
| **记忆可插拔** | 后端可换 psql / sqlite-vec；命名空间 `lore:*` `wiki:*` 区分游戏预置 vs 实时写入 | `memory-architecture.md` |
| **屏幕捕获** | `getDisplayMedia` 替代 RTSP（`displaySurface:"window"`、1fps、无音频） | `screen-capture.md` |
| **Jarvis 模式** | 唤醒词 **"bt"**（自训 KWS v4 已上线）+ EXIT_WORDS `{行, 明白, 了解, ok, 好的}` + 全双工 + 事件预录音频 | `doc/subsystems/jarvis-mode.md` |
| **错误日志规范** | 报错写日志，**不** TTS 读出；每条日志带服务名 + 时间戳 | `tech-local.md` |
| **服务时间戳日志** | 每次服务启动新建时间戳日志文件（PID + 时间戳文件名） | `tech-local.md` |
| **预录音频** | wake.wav / goodbye.wav / error.wav 集中在 `prompts/bt/events/` | `doc/subsystems/jarvis-mode.md` |
| **退出词 = 肯定词** | 不需要额外说"拜拜/再见"；用"行/明白/了解/ok/好的"作为对话结束信号 | `doc/subsystems/jarvis-mode.md` |
| **LLM 回复可见** | webui 不再另起右上角回复面板；中间 `VLM Output Info` / `id="resultTextContent"` 是单一对话面，`Pilot` / `BT-7274` 对话进入 `vlmHistory` 渲染，避免“DOM 有内容但外层 display:none” | `doc/subsystems/jarvis-mode.md` §14 |
| **webui 文本直达 LLM（无需视频）** | webui 加 `id="llmTestSendBtn"` 按钮 + `id="btTtsPlayer"` audio 元素；点击 → POST `/api/llm/message`（同当前 WebSocket `sessionId`）→ WS `llm_reply` → 写入 `vlmHistory/resultTextContent` → 前端 fetch `/api/tts/synthesize` 播放 WAV；文本测试跳过状态机内置 TTS，避免 MiniMax 双合成 | `doc/subsystems/jarvis-mode.md` §14 |
| **语音对话可观测** | Jarvis ASR 定稿后广播 `pilot_utterance` WS 事件，前端先显示 Pilot 文本，再显示 LLM 回复；后续 KWS→ASR→LLM→TTS 测试可直接从中间框观察链路 | `doc/subsystems/jarvis-mode.md` §14 |

---

## §4 v3.2 路线图（6 项未落地主方向）

> 这些都是**主方向**（不只是"待办"），已完成方案设计但代码未实施。

| # | 项 | 优先级 | 状态 | 工作量 | 关联文档 |
|---|---|---|---|---|---|
| 1 | **API 化**（TTS / 声音克隆 / LLM 云端化；ASR 已固定本地） | **P0** | 设计完整 | 大 | `api-optimization.md` |
| 2 | **MiniMax Token Plan 接入** | **P0** | 半落地（凭证 + 模型就绪） | 中 | `token-plan-comparison.md` + `voice-clone.md` §13 |
| 3 | **P2 记忆持久化** | P1 | **落地（v0.2 hooks，2026-07-13 v3.26）** → 见 §4.0 | 中 | `memory-architecture.md` + `specs/memory-store-skeleton-spec.md` |
| 4 | **Jarvis 状态机主循环** | P1 | 设计完整 | 大 | `doc/subsystems/jarvis-mode.md` |
| ~~5~~ | ~~**KWS 训练**（`"bt 在吗"`）~~ | ~~P2~~ | ~~预训练实测 0/7 命中，待自训~~ → **v4 已落地 2026-07-10** | ~~中~~ | `doc/subsystems/jarvis-mode.md §2.4`（自训 FAR 2% / recall 49%）|
| 6 | **Codex fallback**（hermes 不可用时） | P2 | 文档完整 | 小 | `hermes-integration.md` |

### §4.0 已落地的 v3.2 项（2026-07-10 更新）

- **#5 KWS 自训**（2026-07-10 完成）：唤醒词 `bt`（自训 v4 model），部署 `D:\AI\models\sherpa-onnx\models\kws\bt-zai-ma\`，FAR 2% / recall 49%（Jarvis 包装层）。详见 `doc/subsystems/jarvis-mode.md §2.4`。
- **#2 MiniMax Token Plan 接入**（2026-07-12 半落地）：声音克隆走云端 `speech-2.8-hd`，voice_id `minimax_man_33333` 已建（MiniMax Token Plan 凭证 + GroupId `<your_minimax_group_id>`），BT-7274 persona 链路测试通过（`vllm_inference=948ms`，prompt_tokens=511 含 character_profile）。**未消除**：`run-windows.env` 凭证沉淀 + 全链路 e2e 收尾待办。详见 `doc/voice-clone.md` §13。
- **#4 webui 文本直达链路（v3.7 已落地）+ jarvis 状态机主循环（部分）**（2026-07-12）：放弃 services/voice-ui 薄壳思路（错误方向）；webui 直接扩：清理重复 html/head/body + 重复状态徽章 + 右上角冗余 `llmReplySection`，统一使用中间 `VLM Output Info` / `resultTextContent` 作为对话面。v3.7 起 `Pilot` / `BT-7274` 对话进入 `vlmHistory` 渲染，语音 ASR 定稿通过 `pilot_utterance` 可见；文本测试模式避免 MiniMax 双 TTS 合成。DevTools 实测：点击 LLM → /api/llm/message 200 → 中间框显示 Pilot + BT-7274 → /api/tts/synthesize 200 → audio blob 播放完成。jarvis 完整 KWS→ASR→LLM→TTS→EXIT 全链路 e2e 仍待联调（doc/subsystems/jarvis-mode.md §13 自标 ⚠️）。详见 doc/subsystems/jarvis-mode.md §14。
- #1 API 化（主路径云端化）/ #3 记忆持久化 / #4 jarvis 全链路 e2e 仍待落地。

- **v3.24**（2026-07-13）：Jarvis短期上下文、MiniMax-only与7060/8070/8099/8985统一启动链路（详见 DELIVERY.md §7 v3.24）。
- **#3 memory-store v0.1 skeleton（2026-07-13 v3.25）**：`services/memory-store/` 落地 SqliteBackend + FTS5 BM25（Psql/Obsidian `NotImplementedError` 占位），端口 8996，端点 `/v1/blocks/push|recall` + `/health` + `/v1/backends`；16/16 测试通过；不影响 `live_adapter.py`。详见 `doc/specs/memory-store-skeleton-spec.md` + `doc/adr/0005-memory-store-start.md`。后续 v0.2 才把钩子接到 webinfer `live_adapter.py`。
- **#3 memory-store v0.2 hooks（2026-07-13 v3.26）**：services/webinfer/live_adapter.py 落地 5 处钩子——get_session fire-and-forget warmup、_session_cleanup_loop 与 handle_reset end-of-session push（pushed 字段回执）、_build_main_http_messages 经 _build_memory_prompt 注入 [Local Wiki] / [本地知识库] 上下文、handle_health 暴露 memory_store 健康字段、on_cleanup 调用 stop_background_tasks 关闭 httpx pool；新增 memory_store_client.py + system_prompts.compose_system_prompt_with_memory；27/27 webinfer 测试通过（含 _memory_warmup / _memory_recall / _memory_push / _build_memory_prompt）。--no-memory-store 可关闭，fail-soft 永不阻塞主请求路径。详见 memory-architecture.md §6 + specs/memory-store-skeleton-spec.md D-9。
- **#1 Screen Capture + #6 hermes-agent 接入（2026-07-13 v3.27）**：(a) `static/screen_capture.js` 去 ES module 改全局 (`window.startScreenCapture / stopScreenCapture / isScreenCapturing`)，新增 fallback 走 `<video>` + drawImage 应对 ImageCapture 不可用；`static/index.html` Video Source 加 Screen Capture tab + `screenControls` div，start()/stop() 加 `inputSource === 'screen'` 分支；`server.py` `websocket_handler` 加 `elif t == "frame"`（base64 → PIL → `vlm_service.process_frame` → `get_session_callback` 广播 vlm_response）；79/79 webui 测试通过，模拟帧端到端 5.5s 拿到 llama-server 回复。(b) hermes-gateway(8642) + background-agent shim(8079) 接入链路打通：补 `$env:LOCALAPPDATA\hermes\bin\hermes.cmd` wrapper（venv python → `python -m hermes_cli.main`），`Start-Hermes` 用 `API_SERVER_HOST/PORT/KEY` env，`background-agent.env` + `scripts/run-windows.env` 同步 `HERMES_API_KEY`；/health（gateway 200/shim 200） + /v1/solve smoke test 返回中文"烟测通过。"(prompt_tokens=24157/5.9s)；详见 `screen-capture.md` §11 + `hermes-integration.md` §11。
- **#1 delegation 触发闭环（2026-07-13 v3.28）**：`prompts/bt-7274.txt` 加 **Delegation Protocol (P-D)** 章节，明示 `</delegation>` 用法（外部查才触发、Tag 必须结尾、background 短句、问题要 self-contained）+ 3 个中英示例；`jarvis_session.py::_make_llm_callback` 在广播 `llm_reply` 之后顺手调 `BackgroundModelService.handle_foreground_response(text, metrics)`，将 `</delegation>` 拆出来 POST `/v1/solve` → shim → hermes → `background_result_ready` WS 广播。LLM 4-case 烟测：chitchat/已知识 → 不触发，`RTX 5060 Ti 显存基准` / `今天天气` / `Cyberpunk 螳螂帮 boss` → 触发并将英文问题自动改写为中文 self-contained 任务。端到端 e2e：`Scanning external sources.</delegation> 查 Cyberpunk 2077 螳螂帮 boss` → 11s 后 `background_result_ready` 拿到 MiniMax M2 + web_extract 整理后的攻略（含 Royce boss、掉落、支线）。79/79 webui 测试通过。详见 `doc/subsystems/jarvis-mode.md` §13.2 + `hermes-integration.md` §10。
### §4.1 优先级说明

- **P0（必须）**：v3.2 的核心交付物，决定项目是否进入"产品形态"
- **P1（重要）**：体验性提升，没有也能用，有了显著加分
- **P2（按需）**：特殊场景才需要，先做也不亏

### §4.2 状态定义

- **设计完整**：文档已写完整，可作为实施依据
- **调研完成**：已比较多家厂商 / 方案，给出推荐
- **文档完整**：操作流程已写好，但还需训练 / 实施

---

## §5 关联文档

- 完整文档索引：见 `README.md`
- 交付与变更记录：`../DELIVERY.md`
- 上游残留（已弃用）：`deprecated/`

---

- **v3.32a verify-services.py/ps1 (2026-07-13)**: pure-Python end-to-end probe (no PowerShell parser issues), pings llama-server (7060) / webinfer (8070) / voice-clone (8985) / webui (8099). `stop-windows.ps1` / `verify-services.py` both green.
- **v3.32b 撤回 v3.32 image chat (2026-07-13)**: 删除 paperclip 按钮 + `/api/vlm/chat` 端点 + `pendingVlmImage` state machine + webinfer multimodal `image_url` 分支 + static contract test。视觉走 v3.27 `screen capture` 路径（`getDisplayMedia` 1fps 推 frame -> VLM）。`JARVIS_KWS_THRESHOLD` 保留 v3.32 的 0.20（NVIDIA Broadcast 干净环境，识别率优先）。
- **v3.33 / v3.33.1 Screen Capture 本地预览 (2026-07-13)**: `screen_capture.js` 暴露 `getScreenCaptureStream/getScreenCaptureVideo`,`index.html` 在 `start()` Screen 分支和 `screenStartBtn` click handler 都挂 `videoElement.srcObject` + 取消镜像。操作员能在 webui 上看到被捕获的窗口/标签,BT-7274 仍按 1fps WS 走原有视觉管线。详见 `doc/screen-capture.md` §3.5 + §11。
- **v3.34 llama-server 上下文 4096->16384 + webinfer prompt guard (2026-07-13)**: 治本 `exceed_context_size_error` 502。详见 `doc/screen-capture.md` §11 v3.34 + `doc/specs/webinfer-prompt-guard-spec.md`(待落地)。
- **v3.35 Paper-Plane 多模态 (2026-07-13)**: 让 BT-7274 通过"纸飞机"被问"你看到什么"时能看到当前屏幕。`index.html sendBtPrompt` 加 `captureBtFrameB64`(从 `getScreenCaptureVideo` / `<video id="videoElement">` 抓 JPEG,最大宽 800,q=0.7),`server.py llm_message` + `jarvis_mode._send_to_llm` 接受 `image_b64` 并把 user message 改成 OpenAI multimodal content 数组(需要 7060 llama-server 已启用 `--mmproj`,默认如此)。视觉管线 / 8070 webinfer / 4 进程编排 / 端口协议全部零改动。空源自动 fallback 到纯文本。详见 `doc/voice-ui.md` §3.6 + `doc/screen-capture.md` §11 v3.35。
- **v3.35a 隐藏 llama-server 控制台窗口 (2026-07-13)**: `install/windows/start-llama-server.ps1` 拉起 `llama-server.exe` 时 `Start-Process` 缺 `-WindowStyle Hidden`,会弹黑色控制台窗口,被误点 X 就 kill PID。补上参数后 7060 静默后台运行,只剩 PID 文件 + 时间戳日志可见。`run-windows.ps1` 本身用 `$psi.WindowStyle="Hidden"`,`start-all-services.ps1` 的 voice_clone_api 分支已带 `-WindowStyle Hidden`,均无需改动。零代码逻辑变化,纯启动参数。

> 文档版本：v3.35a 配套  |  最近更新：2026-07-13（隐藏 llama-server 控制台窗口）  |  作者：Codex
