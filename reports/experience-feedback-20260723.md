# JoyAI-VL-Interaction 体验反馈报告

> **日期**：2026-07-23（晚间实跑）
> **环境**：default 模式，main 分支 `3fed7f8`（含 #21/#22/#23 合并）
> **体验人**：用户（测试对话记录）
> **状态**：📝 现象记录阶段（不含方案）

---

## 反馈总览

| # | 模块 | 现象简述 | 严重度 | 类型 |
|---|------|----------|--------|------|
| E1 | 视频输入 | 浏览器 Screen Capture 延迟大，想用 OBS Virtual Camera 但不会配 | 🔴 高 | 调研+配置 |
| E2 | 输出渲染 | `</response>` 和 `</silence>` 内部标签泄露到聊天 UI 可见区域 | 🔴 高 | Bug |
| E3 | 对话逻辑 | `</silence>` 在 default 模式出现——该机制疑似属于直播模式，不应在普通对话触发 | 🟡 中 | 逻辑分析 |
| E4 | 状态栏 | 缺少 Memory OK / Wiki OK 徽章，无法直观判断记忆和外接库是否在线 | 🟢 低 | 功能增强 |
| E5 | 国际化 | WebUI 全英文：Video Source 面板 + Settings 页面看不懂描述、不知如何设置 | 🟡 中 | i18n/汉化 |

---

## E1：Screen Capture 延迟体感大 → OBS Virtual Camera 调研

### 现象
- 使用浏览器原生 `getDisplayMedia()` 做 Screen Capture（1 fps JPEG 帧序列），**延迟体感明显偏高**。
- 用户已有 OBS 安装，但：
  - 不知道如何开启 OBS Virtual Camera
  - 不清楚 OBS Virtual Camera 的接口/协议（是虚拟摄像头设备？还是推流 URL？）
  - 不确定 WebUI 的 "OBS Virtual Camera" 下拉选项是否已可用、如何对接

### 截图证据
Video Source 面板中可见：
- `OBS Virtual Camera` 已出现在 Camera Selection 下拉列表中 ✅
- 当前选中的是 `OBS Virtual Camera`
- 下方提示文字："Local preview + WebRTC to backend. VLM runs automatically while streaming."
- `RTSP Stream` 选项旁有 `Beta: Tested with Reolink RLC-811A.` 标注
- Screen Capture 显示 "Capturing (1 fps)"

### 待调研项
1. [ ] OBS Virtual Camera 开启步骤（Windows 版本要求、Settings → Virtual Camera 启动）
2. [ ] WebUI 的 `OBS Virtual Camera` 选项实际调用的是 `getUserMedia({ video: { deviceId: 'obs virtual camera' } })` 还是其他接口？
3. [ ] OBS Virtual Camera vs RTSP Stream vs Screen Capture 三种模式的延迟对比数据
4. [ ] 用户机器的 OBS 版本是否支持 Virtual Camera（OBS 26+ 内置，旧版需插件）

---

## E2：`</response>` 和 `</silence>` 标签泄露到聊天 UI

### 现象
VLM 模型输出的内部控制 token `</response>` 和 `</silence>` **作为可见文本显示在聊天气泡中**，未被前端剥离。

### 截图证据

**截图 A — `</response>` 泄露：**
```
用户: bt, 告诉我现在gpu占多少

BT-7274: </response> 显示器里能看到GPU占用9.6%，显存占用
        0.2%，温度39℃，当前是GeForce RTX 5060 Ti，一切正常。
```
→ `</response>` 标签以明文出现在回复正文开头。

**截图 B — `</silence>` 泄露：**
```
用户: 你看到的分辨率是多少，不是9.6%，是占了9.6GB显存。是否
      分辨率太小导致的

BT-7274: </silence>

用户: 回复

BT-7274: </response> 显示器里确实显示显存占用9.7/16GB，
        9.7GB，分辨率是1920x1080，当前没有异常。
```
→ `</silence>` 作为一条**独立消息气泡**出现（不是附加在某条回复上），且后续正常回复仍带 `</response>` 前缀。

### 影响范围
- **所有 VLM 回复**均可能携带 `</response>` 前缀（100% 复现）
- `</silence>` 概率性出现（非每轮都有）
- 严重影响阅读体验，且暴露内部实现细节给终端用户

### 初步判断（不深入代码）
- 这两个标签是系统 prompt 中定义的 **decision token**（决策令牌），用于控制 VLM 行为分支（`</delegate>` / `</response>` / `</silence>` 等）。
- 前端 `render_markdown` 或消息后处理逻辑**未剥离这些标签**就直接渲染到 DOM。
- 修复方向应在**前端消息管线**（收到 WebSocket 文本后、插入 DOM 前）做标签过滤，而非改 prompt。

---

## E3：`</silence>` 在 default 模式的逻辑合理性存疑

### 现象
如 E2 截图 B 所示，在 **default 模式**（非直播/非 Jarvis 语音模式）下，VLM 输出了 `</silence>` 决策 token。

### 用户记忆/背景
- 用户回忆：`</silence>` 机制源自**源项目的直播模式**设计——用户直播时 JoyAI 作为 AI 虚拟角色：
  - 听沉默（不说话，观察中）
  - 回答用户问题
  - 主动随机发言（概率性插话）
- 这是**直播陪伴场景**的行为逻辑，**不应该在 default 文本对话模式**触发。

### 待讨论/分析项
1. [ ] **当前 system prompt 是否统一？** default 模式和 Jarvis/live-stream 模式是否共用同一套 decision token 定义？
2. [ ] **`</silence>` 的概率权重**：当前 prompt 中 silence 分支的条件是什么？是否有模式判定（如 `if jarvis_mode or live_stream_mode`）？
3. [ ] **期望行为**：
   - default 模式 → **永远不输出 `</silence>`**（每轮必须有文本回复或 `</delegate>`）
   - Jarvis 语音模式 / 直播模式 → 保留 silence 作为合法决策
4. [ ] **修改层级**：这是 prompt 层的问题（改 system prompt 加条件）、还是后端 adapter 层的问题（拦截 silence 并转为空回复 / 自动重试）？

---

## E4：状态栏缺少 Memory OK / Wiki OK 徽章

### 现象
当前底部状态栏有 5 个徽章：

| 徽章 | 含义 | 当前状态 |
|------|------|----------|
| CONNECTED | WebSocket 已连接 webinfer | ✅ 绿色 |
| LLM OK | llama-main VLM 可用 | ✅ 绿色 |
| TTS OK | voice-clone MiniMax 可用 | ✅ 绿色 |
| KWS OK | 关键词唤醒 sherpa-onnx 可用 | ✅ 绿色 |
| 对话中 (唤醒) | Jarvis/KWS 状态 | 🟡 黄色 |

**缺失**：
- **Memory OK** — memory-store (:8996) 是否启动、sqlite 后端是否可达
- **Wiki OK** — Hermes gateway (:8642) / 外接知识库是否在线、`[Local Wiki]` 召回是否启用

### 用户诉求
- 新增两个徽章，分别展示**记忆服务**和**外接库**的健康状态。
- 当对应服务未启动时（如本次 default 模式 memory-store 未拉起），应显示灰色/离线态，而不是直接隐藏。

### 备注
- memory-store 是 opt-in 服务（需 `JOYAI_ENABLE_MEMORY_STORE=1`），所以该徽章需要区分"未启用"和"启用但离线"两种灰态。
- Hermes gateway 同理（`run-windows.ps1` default/voice 模式均不启动 hermes-gateway 和 background-agent）。

---

## E5：WebUI 汉化需求（英文界面看不懂）

### 现象
源项目 WebUI 全英文，用户在两个核心面板遇到理解障碍：

#### E5.1：Video Source 面板

| 英文原文 | 用户困惑点 |
|----------|-----------|
| **Video Source** | 标题本身可猜，但下属选项说明看不懂 |
| *Webcam Capture* → **Camera Selection** / **OBS Virtual Camera** / **idle** | 不知各选项区别、OBS 怎么配 |
| *"Local preview + WebRTC to backend. VLM runs automatically while streaming."* | 不懂技术含义 |
| **RTSP Stream** / *Beta: Tested with Reolink RLC-811A.* | 不知什么是 RTSP、Reolink 是什么 |
| **RTSP Stream URL** (`rtsp://192.168.1.100:554/stream`) | 不知填什么 |
| **Processing Interval** / *"Seconds between each VLM inference (default: 1s)"* | 不知该调大还是调小 |
| **Frames per Batch** / *"Number of frames batched per inference (default: 1)"* | 不懂 batch 概念 |
| **Screen Capture** / *"Browser-native getDisplayMedia, 1 fps JPEG frames."* / **Capturing (1 fps)** | 不知这是什么捕获方式 |

#### E5.2：Settings 面板

| 区块 | 英文原文 | 用户困惑点 |
|------|----------|-----------|
| **Layout** | Main Content Order / VLM Output Info → Cam / VLM Output on Camera View / None | 不知每个选项的效果 |
| **Visual Style** | Colorful UI Accents / *"Color-coded icons and input focus glows"* | 不知开关后的视觉变化 |
| **Visual Effects** | Pop-in Animation / Green Glow Effect / Fade Effect | 能猜大概但不确定 |
| **WebRTC** | Max Video Latency (seconds) / *"Drop old frames if delay exceeds this"* | 不知该设多少 |
| **Audio Output** | Speak VLM output / *"Play TTS audio for each visible response"* | 这个能猜到 |
| **Background Model** | Enable delegation solver / *"Run Qwen3.5-122B-A10B-FP8 for delegated questions..."* | 完全不懂 delegation 是什么 |
| Frame multiplier / Max background frames | 技术术语 | 不知影响 |
| **Debug** | Show request payload / Show response payload / Show memory state | 不知何时该开 |

### 汉化范围建议（待确认）
用户明确说"主要在几个地方"看不懂，优先级应为：
1. **Video Source 面板**（E5.1 全部）— 这是第一屏入口，用户首先碰到
2. **Settings 面板**（E5.2）— 配置页面，不懂就没法调优
3. 其他区域（聊天框 placeholder、按钮 tooltip、错误提示等）— 后续迭代

### 技术注意
- 当前项目**无 i18n 框架**（0 个 .json 语言包、0 个 `t()` 调用），纯硬编码英文字符串散布在 `index.html` ~9400 行和 7 个 JS 模块中。
- 汉化方案选择（**本报告不展开**）：直接替换硬编码 vs 引入轻量 i18n vs 双语切换 toggle。

---

## 附录：运行时环境快照

| 项目 | 值 |
|------|-----|
| 分支/commit | main / 3fed7f8 |
| 启动模式 | default（llama-main + voice-clone + webinfer + webui） |
| llama-server | port 7060, ctx 16384, -ngl 999, GGUF IQ4_NL |
| webinfer | port 8070, streaming-infer-adapter |
| webui | port 8099, JoyAI VL Live |
| voice-clone | port 8985, MiniMax speech-2.8-hd |
| memory-store | ❌ 未启动（opt-in） |
| hermes-gateway | ❌ 未启动（default 模式不包含） |
| whisper/asr | ❌ 未启动（default 模式不包含） |
| GPU | GeForce RTX 5060 Ti, 16.3 GB VRAM |
| OS | Windows |

---

*报告完毕。下一步：逐条讨论方案优先级与实现分工。*
