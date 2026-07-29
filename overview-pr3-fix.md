# PR #3 补修概览 — 前端对话（2026-07-22）

## 做了什么
以前端对话身份修复了测试对话回归暴露的 `processEvery`/`framesPerBatch` 崩溃（PR #3 第二处 monolith 断裂），并顺势修掉修复后暴露的 `checkApiKeyRequirement` 崩溃。

## 修复清单（仅 `index.html`）
1. **恢复两个 `<input>`**：`processEvery` / `framesPerBatch` 在模块化期被误删，已放回 RTSP 捕获块（布局同原 `ff79b3b`；CSS 本就在）。
2. **防御性守卫**：`updatePromptAvailability`、`connectWebSocket` server_config handler、顶部 `addEventListener`（change/blur ×2）全部加 `if` 防未来再删元素时崩 init。
3. **守卫 `checkApiKeyRequirement`**：`apiKeyField`/`apiKeyToggle` 是 Block 3 `svc-*` 重构有意移除的旧折叠控件，元素缺失时安全 no-op（不恢复过时 UI）。顺带守卫 `apiBaseHint` 用法。

## 验证结果（环境：8099/8070/8985/8996 在跑，7060 关）
- **Playwright（headless Chromium）**：`pageErrors: []`（零 JS 崩溃）
  - ① 无 `modelSelect` 崩溃 ✅ ② `window.JoyWs` 定义 ✅
  - ③ `updateModelOnOpen: true`（WS 连上即发 `update_model`）✅
  - ④ `updateModelOnChange: true`（改 api key 触发出站，`errorsAfterChange: 0`）✅
  - ⑤ `cleanupPostSeen: true` + `sessionIdChanged: true`（Reset Session → `POST /api/session/cleanup` + WS 新 session 重连）✅
- **9 项尺子**：7/9 PASS（⑥/⑨ 因 7060 关机环境阻断，非前端回归）。

## 交付
- 提交 `029370c`（仅 `index.html` + `reports/integration-2026-07-21-frontend-fix-handoff.md`），推送到 `fix/webui-live-refs`。
- PR #3（https://github.com/kuhaku9527/JoyAI-VL-Interaction/pull/3）head = `029370c`，现达成 live 验收 ③/④/⑤、页面零 JS 崩溃，**可合并 main**。

## 下一步
PR #3 合并进 `main` 后，基于 `main` 开分支做 **Block 5**（`connectWebSocket` 窄抽取：连接生命周期外置 `joy_ws.js` + `dispatchServerMessage` 桥，桥接引用 ~9 个）。
