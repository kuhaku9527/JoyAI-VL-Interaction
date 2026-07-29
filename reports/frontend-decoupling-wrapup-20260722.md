# 前端解耦收尾报告（2026-07-22）

> 角色：前端对话。本文档把"monolith → IIFE-to-window 模块"拆分的第一阶段画句号，并给出剩余视图层的后续评估。

## 一、阶段成果：Blocks 1–6 全部外置完成

| Block | 外部模块 | 行数 | 导出 / 内容 |
|------|---------|------|-----------|
| 1 | `render_markdown.js` | 157 | `window.JoyRender`（markdown 渲染，8 函数） |
| 2 | `sanitize_static_html.js` | 201 | `window.JoySanitize`（HTML 消毒，7 函数） |
| 3 | `config_services.js` | 88 | `window.JoyConfig`（API 表单 `svc-*` 读写/探测/保存） |
| 4 | `joy_ws.js` | 182 | `window.JoyWs.applyApiSettings` / `cleanupServerSession` |
| 5 | `joy_ws.js`（同文件扩展） | — | `window.JoyWs.connectWebSocket`（连接生命周期） |
| 6 | `capture_webcam.js` / `capture_rtsp.js` / `screen_capture.js` | 136 / 135 / 171 | `window.start*Capture` 系列（WebRTC 视频源） |

- 外部模块累计约 **1070 行**逻辑已外置。
- monolith `index.html` 由约 **9800 → 9438 行**（瘦身约 360+ 行，含 capture 三模块与 Blocks 1–5）。
- 调用点统一用 `const { fn } = window.X` 别名解构保留；重赋值闭包变量走 `register(ctx)` 桥（get/set 访问器）。

## 二、静态收尾体检（本对话执行，纯静态、不改代码）

- **语法**：`node --check` 7/7 全部 OK。
- **重复定义**：monolith 内无任何与外部模块导出全局名重复的 `function` 定义（capture 抽取完整，无半吊子残留）。**0 处。**
- **加载顺序**：7 个 `<script src>` 均在调用它们的内联脚本（body 末尾）之前按序加载：
  `screen_capture → capture_webcam → capture_rtsp → render_markdown → sanitize_static_html → config_services → joy_ws`。✅
- **模块引用**：4 个命名空间模块经解构别名在 monolith 使用（4896 / 5047 / 5484 / 8710–8711 / 8949）；capture 三模块的 `start/stop/is*` 函数均被 monolith 调用。**无孤儿模块。**
  - 注：初版体检脚本把 `JoyRender/JoyConfig/JoySanitize` 误报为 unused（正则未匹配 `} = window.X` 解构结尾），已人工核实为正常使用。
- **弱死代码候选（建议保留）**：capture 模块导出的 3 个只读 getter——`getWebcamStream` / `getWebcamVideo` / `getRtspStream`——当前 monolith 及跨模块均无调用方，属公共 API 冗余。低风险，列为可选清理项；删除前需 Playwright 回归。

## 三、剩余 monolith 内联区块（视图 / 控制层，强耦合 DOM/闭包）

剩余约 5600 行 JS 全部与 DOM、闭包状态（`sessionId`/`lastText`/`fadeTimeout`/`vlmHistory` 等）深度纠缠，窄抽取收益递减、行为等价风险上升：

| 区块 | 行号区间 | 体量 | 特征 | 后续候选 |
|------|---------|------|------|---------|
| 背景富内容渲染/解析 | 5007–5706 | ~700 行 | `extract*/parse*/normalize*/score*` 纯函数 + canvas 绘制 + 模态框 | Block 7 |
| TTS 播放 | 5823–6135 | ~310 行 | `pcm16ToAudioBuffer`/`normalizePcmChunk` 纯函数 + AudioContext/WS 耦合 | Block 8 |
| VLM 历史渲染 + 背景跳转 | 6200–6862 | ~660 行 | 耦合 DOM/闭包状态 | Block 9 |
| 摄像头控制 UI | 4594–4694 | — | 强耦合 UI | 不建议抽 |
| 布局/面板/全屏 | 7027–7395 | — | 强耦合 UI | 不建议抽 |
| 状态/服务检测 | 7429–7680 | — | 强耦合 UI | 不建议抽 |

## 四、结论与下一步

- **第一阶段（可独立测试的纯逻辑层外置）已达成**，建议在此画句号。
- Block 7–9（视图层）抽取需逐块 + 测试对话 Playwright 回归配合，风险/收益比不优，**非必需**。
- 可选收尾：① 删 3 个 capture getter（需回归）；② 前端缺 JS lint 门禁（PR #5 已加 ruff 后端门禁，前端未覆盖）。
- **回归基线**：测试对话 2026-07-22 对 PR #4 结论——9 项尺子 7/9（7060 关机环境阻断）+ Playwright ②/①/③/④/⑤ 全绿、零 JS 崩溃。capture 三模块包含在该验证范围内。

## 五、当前 git 状态

- `origin/main` = `b6b9fd0`（PR #4 connectWebSocket + PR #5 ci/quality-gate 均已合并）。
- 本地 `main` 已对齐 `origin/main`，工作树对 tracked 文件干净。
- Block 分支 `fix/webui-block5-connectws`（913c25d）为 main 祖先，可保留亦可删。
