---
title: WebUI 视觉与交互规约
status: active
last_updated: 2026-07-13
related:
  - architecture-local.md
  - api-optimization.md
  - specs/webui-kws-listening-chain.md
  - specs/webui-asr-input-state.md
---

# Voice UI 规约

本文档记录 JoyAI-VL-Interaction WebUI 中与 BT-7274 语音链路相关的视觉与交互约定。
所有 WebUI 调整改完 CSS / HTML / JS 后，必须同步本文档对应小节，否则视为不一致。

## 1. HUD 右上角状态条（header-right）

### 1.1 元素清单
从左到右依次为：

| 序号 | 元素 | 类型 | 说明 |
| --- | --- | --- | --- |
| 1 | jarvisStatus | `.status-badge.disconnected` / `.connected` | WebSocket 连接状态，文本 `Disconnected` / `Connected` |
| 2 | llmBadge | `.status-badge.llm-unknown` / `.llm-ok` / `.llm-err` | LLM 健康状态，文本 `LLM ?` / `LLM OK` / `LLM ERR` |
| 3 | ttsBadge | `.status-badge.llm-unknown` / `.llm-ok` / `.llm-err` | TTS 健康状态，文本 `TTS ?` / `TTS OK` / `TTS ERR` |
| 4 | kwsBadge | `.status-badge.llm-unknown` / `.llm-ok` / `.llm-err` | KWS 健康状态，文本 `KWS ?` / `KWS OK` / `KWS ERR` |
| 5 | jarvisExtra | `.status-badge.jarvis-disconnected` / `.jarvis-connected` | Jarvis 后端额外状态，文本 `Jarvis ?` / `Jarvis OK` |
| 6 | settingsBtn | `button.settings-btn` | 打开 Settings Modal，仅图标 |
| 7 | themeToggle | `button.theme-toggle` | 浅色 / 深色主题切换，文本 `Dark` / `Light` |

### 1.2 视觉分组约束
1. 元素 1-5 是「状态徽章区」，视觉上必须连续。
2. 元素 6-7 是「控制区」，与状态徽章区之间必须有视觉分隔。
3. 实现方式：`.header-right` 设置 `gap: 10px`，并在 `.settings-btn` 上：
   - `margin-left: 4px`
   - `padding-left: 14px`（在 `.theme-toggle` 同款 padding 基础上多加 4px 形成左侧呼吸空间）
   - `box-shadow: inset 1px 0 0 rgba(255, 255, 255, 0.28)`（画一根 1px 半透明白色分割线）
4. 调整任何徽章或按钮的 padding / margin 后，必须重新走 `getBoundingClientRect()` 验证：
   - 状态徽章彼此 `gap_left` 应稳定在 10px
   - 第 5 个徽章 -> settingsBtn 的 `gap_left` 应 >= 14px
   - settingsBtn -> themeToggle 的 `gap_left` 应稳定在 10px
   - `.header-right` 总宽控制在 `min(680px, 100%)` 以内，避免溢出

### 1.3 已知修复记录

#### 1.3.1 2026-07-12 HUD 重叠（518px 拥挤）

**症状**：5 个状态徽章 + 2 个控制按钮挤在 499px 内，无视觉分组，从左至右密集排列，眼睛难以区分。

**修复方案**：
- `.header-right` `gap: 8px -> 10px`
- `.settings-btn` 改为 `padding: 8px 12px 8px 14px`，新增 `box-shadow: inset 1px 0 0 rgba(255, 255, 255, 0.28)` 与 `margin-left: 4px`

**修复前后实测布局**：

| 区域 | 修复前 gap_left | 修复后 gap_left |
| --- | --- | --- |
| jarvisStatus -> llmBadge | 8px | 10px |
| llmBadge -> ttsBadge | 8px | 10px |
| ttsBadge -> kwsBadge | 8px | 10px |
| kwsBadge -> jarvisExtra | 8px | 10px |
| jarvisExtra -> settingsBtn | 8px（无分隔） | 14px（含 4px margin + 视觉分隔） |
| settingsBtn -> themeToggle | 8px | 10px |
| `.header-right` 总宽 | 499px | 518px |

**改动文件**：`services/webui/src/joy_interaction_webui/static/index.html`
- `.header-right` 块（约 line 154）
- `.settings-btn` 块（约 line 187-197）

**截图**：
- `.pids/after_overlap_fix_step2.png`
- `.pids/after_overlap_fix_step2.jpeg`
- `.pids/after_overlap_fix_step3.jpeg`

## 2. 主题与色板

- 深色主题为默认（`.theme-toggle` 文本 `Dark`，点击切换到浅色并显示 `Light`）。
- 状态徽章色板由 `.status-badge` 系列定义：
  - `.connected` / `.llm-ok` / `.jarvis-connected` -> 健康色
  - `.disconnected` / `.jarvis-disconnected` -> 未连接色
  - `.llm-unknown` -> 未知 / 轮询中
  - `.llm-err` -> 错误
- 不允许使用单一色调家族作为整个 HUD 主色（如全紫 / 全蓝）。

## 3. Video 元素在 Screen Capture tab 的行为（v3.33）

### 3.1 元素定位

`<video id="videoElement" autoplay playsinline muted>` 位于 `services/webui/.../static/index.html` 顶部 Video Source 卡片内，是 webui 唯一可见的视频预览元素。

### 3.2 三个 tab 的视频源与本地预览关系（v3.33 后）

| Tab | 视频源 | 本地预览（v3.33 前） | 本地预览（v3.33 后） |
| - | - | - | - |
| Webcam | `getUserMedia` 物理摄像头 | 由 WebRTC 远端流显示（不归本任务） | 同上（不变） |
| RTSP | 服务端 RTSP 推流 | 由 WebRTC 远端流显示（不归本任务） | 同上（不变） |
| **Screen Capture** | `getDisplayMedia` 选窗口/标签 | ❌ **不显示**（hidden video） | ✅ **实时显示**（挂到 `videoElement`） |

### 3.3 切换行为

- 切到 Screen Capture tab → `startScreenCapture()` 后 `videoElement.srcObject = previewStream`，同时 `classList.remove('mirrored')`（避免游戏 UI 文字被 `transform: scaleX(-1)` 颠倒）
- 切回 Webcam / RTSP → `start()` 开头自动 `videoElement.srcObject = null` + `setVideoWaitingForStream(true)`，新 tab 接管视频源
- 点 Stop → `stopScreenCapture()` 清空内部 stream，外层 `stop()` 再清 `videoElement.srcObject = null`

### 3.4 取消授权处理

- 用户在 `getDisplayMedia` 弹窗里点取消 → `getScreenCaptureStream()` 返回 `null` → 走 `updateStatus('Screen capture cancelled', 'disconnected')` + `setVideoWaitingForStream(false)`，**不会卡在 'Selecting window...'**

### 3.5 样式注意

- `<video id="videoElement">` 现有的 `autoplay playsinline muted` 属性已就位，**不需要改**
- `setVideoWaitingForStream(waiting)` 切换 `videoCard` 的 `.waiting-for-stream` class（用于显示占位文本）
- `.mirrored` class 仅在 Webcam 模式下手动开启（前置摄像头镜像），Screen Capture 模式启动时主动移除

### 3.6 Paper-Plane 多模态发送 (v3.35)

Paper-Plane 按钮（`promptSendBtn` / Cmd+Enter）原本只发纯文本 `text` 到 `/api/llm/message`，
BT-7274 因为看不到画面只能说"全黑"/"无可见目标"。v3.35 升级为多模态：

| 路径 | 行为 |
| - | - |
| 抓帧源 | `window.getScreenCaptureVideo()` -> `<video id="videoElement">` -> `null`。Screen Capture 模式优先,Webcam 其次,无源则 `null`。 |
| 抓帧 | `canvas.drawImage(video, 0, 0, w, h)`,最大宽 `800px`,JPEG 质量 `0.7`,输出纯 base64 不带前缀。 |
| POST body | `{ text, session_id, image_b64? }`,只在抓到帧时附加 `image_b64`。 |
| 服务端 | `/api/llm/message` (server.py) 校验后调 `sm._send_to_llm(text, stream_tts=False, image_b64=...)`;baseline 3MB 拒绝以避免一次请求过大。 |
| LLM 入参 | `_send_to_llm` (jarvis_mode.py) 在 `image_b64` 非空时把 user message content 改为 `[{text}, {image_url: data:image/jpeg;base64,...}]` 数组(OpenAI 多模态协议)。7060 llama-server 启用 `--mmproj` 才能接,详见 `install/windows/start-llama-server.ps1`。 |
| TTS / WS 广播 | 不变。仍走 jarvis_voice / jarvis_text broadcast + `/api/tts/synthesize` 前端播放。 |

**触发条件自动 fall-back**：当抓帧失败 (`videoWidth === 0` / 视频未授权 / 非媒体元素) 时,自动回到纯文本发送,前端不报错,BT-7274 仅缺画面上下文。

---

## 4. 待补章节（原 §3，章节号顺延）



- 聊天面板布局（消息气泡、用户/助手区分、延迟时间戳）
- KWS 监听模式下的音频波形 / RMS 指示器（v3.29 已加 RMS 条，详见 §3.6 后续）
- ASR 输入框状态机（idle / recording / final / error）
- 设置 Modal 内字段

### 4.1 引用 v3.33 改动的其他文档

- `doc/screen-capture.md` §3.5（本任务的完整设计与决策记录）
- `doc/00-main-direction.md` §4 v3.33 变更条目

---

## 9. Design Tokens

> 新增 WebUI 状态徽章 / 指示元素时，**必须**从本节取 token，禁止在 PR 里临时拍脑袋定色板 / 间距（曾发生 GAP 8px→10px 漂移事故）。规则本地化自 s2s `demo/DESIGN.md`，仅保留本仓库需要的子集。

### 9.1 色板（orb / 徽章状态色）

状态色由 `.status-badge` 系列 class 驱动，新增状态须复用以下语义色，不得新造色值：

| 语义 | class | 用途 |
| --- | --- | --- |
| 健康 / 已连接 | `.connected` / `.llm-ok` / `.jarvis-connected` | 正常在线 |
| 未连接 | `.disconnected` / `.jarvis-disconnected` | 离线 / 未建立 |
| 未知 / 轮询中 | `.llm-unknown` | 启动后尚未拿到健康结果 |
| 错误 | `.llm-err` | 健康检查失败 |

- orb（语音球）颜色随状态切换，须映射到上表四语义之一；**不允许**使用单一色调家族作为整个 HUD 主色（如全紫 / 全蓝）。
- 新增色值只能在 §9.1 追加，禁止散落在 CSS 叙述里。

### 9.2 字体

- **机器文本**（状态徽章文本、日志行、时间戳）：等宽字体（mono），保证对齐与「机器感」。
- **正文 / 对话气泡**：`Inter`（无衬线），提升长文可读性。
- 新增文本元素须二选一归属，不得混用导致视觉层级混乱。

### 9.3 间距与网格

- 所有 HUD 内元素间距走 **8px 基准网格**（8 / 16 / 24px），禁止出现非 8 倍数的 gap（历史事故：状态徽章 `gap` 8px→10px 未同步文档）。
- `.header-right` 总宽约束 `min(680px, 100%)`，徽章间 `gap: 10px`、控制区分隔 `margin-left: 4px` + 1px 半透明白分割线（见 §1.2）。
- 任何 padding / margin 调整后，必须重新走 `getBoundingClientRect()` 验证 §1.2 列出的 gap 实测值。
