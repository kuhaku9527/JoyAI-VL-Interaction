# 前后端联调报告 — 2026-07-21

## 结论：✅ 全绿，整链打通

入口链路 `浏览器 → 8099(WebUI) → 8070(webinfer) → 7060(VLM)` 全部可达且端到端推理通过。

## 拉起方式
```
start-joyai.ps1 -Mode minimal
```
后台进程仍在运行（`run-windows.ps1` 持有前台，Ctrl+C 或 `-Stop` 停止）。

## 验证结果

| # | 检查项 | 端点 | 结果 |
|---|--------|------|------|
| 1 | WebUI 首页 | `GET 8099/` | HTTP 200 ✅ |
| 2 | webinfer 健康 | `GET 8070/health` | `{"ok":true,...}` ✅ |
| 3 | webinfer 模型列表 | `GET 8070/v1/models` | 含 `joyai-vl-interaction-preview` ✅ |
| 4 | 前端自报后端地址 | `GET 8099/detect-services` | `llm.url=http://127.0.0.1:8070/v1`（契约一致）✅ |
| 5 | 前端→后端代理 | `GET 8099/api/webinfer/summarizer/route` | 正确代理到 `8070→7060` ✅ |
| 6 | WebSocket 路由 | `GET 8099/ws` | 路由存在（GET→400，符合 WS 端点语义）✅ |
| 7 | **端到端真实推理** | `POST 8070/v1/chat/completions` | 经 `7060` 返回 `"OK"` ✅ |

## 端口（均监听 127.0.0.1，已全部拉起）
- 7060 llama-main（VLM，RTX 5060 Ti 真推理）
- 8070 webinfer（后端网关）
- 8099 webui（前端）
- 8985 voice-clone / TTS（MiniMax，`/health` 实测 `minimax_ok=true`）
- 8996 memory-store（sqlite backend，`/health` 实测 `ok=true`）

## 非阻塞降级（不影响联调）
- **memory-store (8996)**：未起。webinfer 报 `memory_store.healthy=false` 但 `enabled=true`，自动降级为 no-op。需 `JOYAI_ENABLE_MEMORY_STORE=1` 才拉起。
- **TTS / voice-clone (8985)**：minimal 模式不拉；且为 MiniMax-only，需配置 MiniMax 凭证。

## 关键坑（已记录，避免再踩）
- 官方脚本用的 venv 是 `D:\AI\envs\joyai-main\python.exe`（里面 `joy_interaction_webui` 已安装）。
- `services/.venv`（python 3.13.14）缺该包且 pyproject 要求 `<3.13`，从它直接 `python -m joy_interaction_webui.server` 会 `ModuleNotFoundError`。联调务必走官方脚本。

## 第二轮：补齐 memory-store / TTS 至全绿（2026-07-21 下午）

用官方 venv `D:\AI\envs\joyai-main\python.exe` 手动拉起两个 minimal 不拉的服务，复刻 `run-windows.ps1` 的 `Start-MemoryStore` / `Start-VoiceClone`：

- memory-store：`python -m memory_store.app`（env `MEMORY_PORT=8996` / `MEMORY_BACKEND=sqlite`）→ `/health` `{"ok":true,...}`
- voice-clone：`python -m uvicorn voice_clone_api.main:app --port 8985`（env `TTS_PROVIDER=minimax` + `MINIMAX_GROUP_ID` + `MINIMAX_API_KEY`）→ `/health` `{"status":"ok","minimax_ok":true}`

webinfer `/health` 的 `memory_store.healthy` 是**启动一次性探针缓存**（`app.py:538` 调 `ping()`，`handle_health` 经 `health_snapshot()` 只读缓存）。因最初 memory-store 未起，标志被钉死 `false`；杀掉 8070 旧进程后用原参数重启 webinfer，标志翻 `true`，7060/8099 不受影响。

## 后端 Bug Handoff（转后端对话修复，本测试对话不改代码）

**标题：webinfer → memory-store 记忆写入静默失败（422）**

**现象**：webinfer `/health` 显示 `memory_store.healthy:true`，但对话产生的长期记忆从未落库。根因是 push 请求被 memory-store 以 422 拒绝，webinfer 静默 no-op（`pushed=0`），不抛错。

**根因（已实测）**：
- 客户端 `services/webinfer/memory_store_client.py:234` 的 `push()` 给每个 block 只发 `content` + `score`。
- 服务端契约 `services/memory-store/src/memory_store/models.py:11` 的 `MemoryBlock` 模型**必填** `session_id` 和 `created_at`（无默认值）。
- `POST /v1/blocks/push` 实测：正确 payload（带两字段）→ `200 {"pushed":1}`；webinfer 实际发的 payload（缺两字段）→ `422` 报 `blocks[0].session_id`/`blocks[0].created_at` `Field required`。
- recall 路径 schema 匹配 → `200` 正常（读没问题，只有写断）。

**建议修复（二选一，推荐 B）**：
- A：webinfer 端在每个 block 补 `session_id` + `created_at` 后发送。
- B（推荐）：服务端 `MemoryBlock` 把两字段改可选，`POST /v1/blocks/push`（`app.py:79`）写入前回填——`created_at` 服务端生成、`session_id` 顶层已传属冗余。

**验证方法（后端改完交回本测试对话复测）**：
- 用 webinfer 风格 payload `{"session_id":"x","blocks":[{"content":"...","score":1.0}]}` 打 `POST /v1/blocks/push`，期望 `200` + `{"pushed":N}`；再 `POST /v1/blocks/recall` 能召回。
- 当前 8996/8985/8070 仍在运行，可直接复测。sqlite 里有一条测试 block（`session_id=integration-test`，无害，无删除端点）。

**状态：✅ 已修复（2026-07-21，commit `a7328c8`，由后端对话执行）** — 采用方案 B：服务端 `MemoryBlock` 的 `session_id`/`created_at` 改 `Optional`，`push_blocks` 端点（`app.py:80`）在写入前回填（`session_id` 取顶层值、`created_at` 用 naive UTC）。QA 用官方 3.12 venv 的 FastAPI `TestClient` 实测：webinfer 风格 payload（不带两字段）打 `POST /v1/blocks/push` 返回 `200` + `pushed=1`，且 `recall` 能召回，写→读闭环打通。建议本测试对话按原验证方法对运行中的 8996 做一次 live 复测确认。

### 测试对话 live 复测确认（2026-07-21 17:2x）
- 运行中的 8996 在 a7328c8 之前启动、加载旧代码，直测仍 `422` → 已重启 memory-store 加载修复（task `twPO3Q`）。磁盘代码已确认：`MemoryBlock.session_id`/`created_at` 改 `Optional`；`push_blocks`（`app.py:81`）写入前回填 `session_id=req.session_id`、`created_at=datetime.now(timezone.utc).replace(tzinfo=None)`（naive UTC）。
- 复测（报告原方法，对重启后的 8996）：
  1. webinfer 风格 push（不带 `session_id`/`created_at`）→ `200` + `{"pushed":1,"session_id":"retest-..."}` ✅（修复前为 422）
  2. recall 召回该块，`created_at` 为服务端 naive UTC（`2026-07-21T09:21:53.105714`）、`session_id` 回填自顶层 → 写→读闭环打通 ✅
  3. 缺 `content` → `422` ✅（模型未放宽，仅 `session_id`/`created_at` 改可选，对旧客户端向前兼容）
- 结论：方案 B 服务端回填在**运行环境**独立验证通过。Bug Handoff ✅ 已修复（后端标记）+ 测试对话 live 复测通过。

## 前端模块化拆分 Handoff（转测试对话跑尺子，本测试对话不改代码）

**目标**：把 `index.html` 单体（~9800 行）增量拆成 IIFE-to-window 模块，复用 `capture_*.js` 模式。每拆完一块，测试对话跑 `bash scripts/smoke-frontend-baseline.sh`（9 项尺子）+ 一次 Playwright 页面加载回归当 CI gate。HTTP 尺子测不到 JS 加载期崩溃，Playwright 必须补。

---

### Block 1 — markdown/escape/render 集群（2026-07-21 晚，前端对话已实施）

**抽出**：`escapeHtml` / `decodeHtmlEntities` / `protectMarkdownCodeSpans` / `restoreMarkdownCodeSpans` / `renderMathToHtml` / `renderMarkdownMath` / `renderMarkdown` / `openLinksInNewTabs` 共 8 个纯函数。

**新文件**：`services/webui/src/joy_interaction_webui/static/render_markdown.js`
- IIFE，挂载 `window.JoyRender`（含上述 8 个导出）。
- 仅依赖 CDN 全局 `marked` / `DOMPurify` / `katex` + `document`，不碰任何内联闭包变量。

**index.html 改动**：
- `head` 在 `capture_rtsp.js` 之后插入 `<script src="./render_markdown.js"></script>`（行 ~3789）。
- 原 8 个 `function` 定义（原 5082–5201）已删除（121 行），替换为解构别名：
  ```js
  const { escapeHtml, decodeHtmlEntities, protectMarkdownCodeSpans,
          restoreMarkdownCodeSpans, renderMathToHtml, renderMarkdownMath,
          renderMarkdown, openLinksInNewTabs } = window.JoyRender;
  ```
  既有的调用点因此无需改动即可工作（作用域内名称不变）。
- **`updateMarkdownToggleUI` 留在内联**：它引用闭包变量 `markdownEnabled` / `markdownIcon` / `markdownText` / `resultText`，不属于纯函数，未拆。

**仍被执行的调用点（回归需覆盖）**：
- `renderMarkdown` → 行 ~5300（结果文本渲染）。
- `decodeHtmlEntities` → 行 ~5561（某表单值处理）。
- `escapeHtml` → 行 ~5689、~5710（静态 HTML 净化集群，后续 Block 也会拆，本次仅别名化）。
- Markdown 开关按钮 → `updateMarkdownToggleUI`（未动，回归确认开关正常）。

**前端已做的离线自检（不取代 live 尺子）**：
- `node --check render_markdown.js` → SYNTAX OK。
- Node + DOM/CDN 桩执行该模块：`window.JoyRender` 8 个导出齐全；`renderMarkdown('# Hello')` 跑通 `marked.parse → DOMPurify.sanitize → openLinksInNewTabs`；`renderMarkdownMath` 跑通 katex 路径 → ALL OK。
- 静态确认：index.html 无残留 `function escapeHtml` / `function renderMarkdown(` 定义；别名与 script 标签就位。

**测试对话回归清单**：
1. `bash scripts/smoke-frontend-baseline.sh` → 期望 9/9 PASS（需 live 栈：8099/8070/7060/8985/8996）。
2. Playwright 页面加载：① 控制台无 JS 报错；② `window.JoyRender` 已定义且含 8 函数；③ 点击 Markdown 开关后结果文本正常渲染（`updateMarkdownToggleUI` 仍工作）。
3. 若动到静态 HTML 净化 UI（capture_webcam/rtsp/screen、Jarvis、TTS UI、memory UI）须一并回归（本 Block 未触及这些）。

**下一块候选**：静态 HTML 净化集群（`sanitizeStaticHtml` 等，行 ~5628 起）——它依赖 `escapeHtml`，现已在 `JoyRender.escapeHtml`，可安全抽取。

### 测试对话回归确认（2026-07-21 20:4x，本测试对话执行）

- **9 项冒烟尺子**：`bash scripts/smoke-frontend-baseline.sh` → **PASS=9 FAIL=0、EXIT=0**（live 栈 8099/8070/7060/8985/8996 全绿、契约一致、端到端 chat 返回 content）。基线无回归。
- **Playwright 页面加载回归**（headless Chromium 1.61.1，NODE_PATH 指向 npx 缓存）：
  - ① 控制台/页面 JS 报错：**除 1 条预存错误外无新增 split 引发错误**。该错误 `modelSelect.addEventListener` on null（Block 1 报 `8099/:7807`，原始未拆版报 `8099/:7914`）——行号差恰为 Block 1 净删 107 行，**A/B 对照证明是拆分工件之前的预存 bug，与本次拆分无关**，不阻塞 Block 1 提交（建议另开 issue 修 `modelSelect` 空值守卫）。
  - ② `window.JoyRender` 已定义且含全部 8 函数（escapeHtml/decodeHtmlEntities/protectMarkdownCodeSpans/restoreMarkdownCodeSpans/renderMathToHtml/renderMarkdownMath/renderMarkdown/openLinksInNewTabs）✅。
  - ③ 运行时渲染链路通：`renderMarkdown('# Hello')` 经真实 CDN `marked`+`DOMPurify`+`katex` 产出 `<h1>` ✅；`escapeHtml('<b>x</b>')` 返回 `&lt;b&gt;x&lt;/b&gt;` ✅。
  - ④ Markdown 开关点击（DOM `.click()` 触发，绕过 headless 视口不可见这一与拆分无关的 quirk）：标签 `"Markdown"` → `"Plain Text"`、`err=null` → `updateMarkdownToggleUI` 与点击处理器（引用闭包变量）在拆分后正常工作 ✅。
- **结论**：Block 1（markdown/escape/render 集群外置为 `render_markdown.js` + `window.JoyRender` 别名）**回归通过，可提交**。唯一残留的 `modelSelect` 报错为预存缺陷，需单列跟踪，不因本次拆分回退。
- 注：本回归在运行中的未提交改动上执行；测试对话未改动任何业务代码。

### Block 2 — 静态 HTML 净化集群（2026-07-21 晚，前端对话已实施）

**抽出**：`completeStaticHtmlDocument` / `sanitizeStaticHtml` / `normalizeStaticHtmlDocument` / `sanitizeStaticHtmlFallback` / `makeStaticHtmlNodeCleaner` / `isSafeStaticUrl` / `sanitizeStaticCss` 共 7 个函数。

**新文件**：`services/webui/src/joy_interaction_webui/static/sanitize_static_html.js`
- IIFE，挂载 `window.JoySanitize`。
- 唯一跨模块依赖：`escapeHtml` 现已在 `window.JoyRender.escapeHtml`（Block 1 抽出）；模块内 `normalizeStaticHtmlDocument` / `sanitizeStaticHtmlFallback` 的兜底分支改为惰性引用 `window.JoyRender.escapeHtml(html)`，不依赖加载顺序。

**index.html 改动**：
- `head` 在 `render_markdown.js` 之后插入 `<script src="./sanitize_static_html.js">`（行 ~3790）。
- 原 7 个 `function` 定义（原 5521–5685，165 行）已删除，替换为解构别名：
  ```js
  const { completeStaticHtmlDocument, sanitizeStaticHtml, normalizeStaticHtmlDocument,
          sanitizeStaticHtmlFallback, makeStaticHtmlNodeCleaner, isSafeStaticUrl,
          sanitizeStaticCss } = window.JoySanitize;
  ```
  既有的调用点因此无需改动即可工作。

**仍被执行的调用点（回归需覆盖）**：
- `completeStaticHtmlDocument` → 行 ~5470、~5487（`normalizeExtractedHtmlDetails`，由提取 HTML 在运行时触发，非同步 init，别名无 TDZ 风险）。
- `sanitizeStaticHtml` → 行 ~5847（background HTML 预览 `iframe.srcdoc`）。

**前端已做的离线自检（不取代 live 尺子）**：
- `node --check sanitize_static_html.js` → SYNTAX OK。
- Node + 桩（JoyRender.escapeHtml 真转义 / DOMPurify stub / DOMParser 留 undefined 走 escape 兜底分支）执行该模块：`window.JoySanitize` 7 个导出齐全；`completeStaticHtmlDocument('<p>hi</p>')` 返回完整 `<!doctype html>` 文档；`sanitizeStaticCss` 剥离 `url(...)`；`sanitizeStaticHtml` 与 `normalizeStaticHtmlDocument` 经 `window.JoyRender.escapeHtml` 跑通 → ALL OK。
- 静态确认：index.html 无残留 `function completeStaticHtmlDocument` / `function sanitizeStaticHtml(` 定义；别名与 script 标签就位。

**测试对话回归清单**：
1. `bash scripts/smoke-frontend-baseline.sh` → 期望 9/9 PASS。
2. Playwright 页面加载：① 控制台无**新增** JS 报错（modelSelect 预存报错单列，不因本次拆分回退）；② `window.JoySanitize` 已定义且含 7 函数；③ background HTML 预览正常（`iframe.srcdoc` 走 `sanitizeStaticHtml` 净化渲染）。
3. 若动到 capture×3 / Jarvis / TTS UI / memory UI 须一并回归（本 Block 未触及这些）。

**下一块候选**：配置/API 集群（`readForm`/`writeForm`/`load`/`save`、`applyApiSettings`）或 WebSocket 集群（`connectWebSocket`）。

---

### Block 3 — 服务配置/API 表单集群（2026-07-21 晚，前端对话已实施）

**抽出**：services-panel 配置 IIFE 的函数体整体 → `window.JoyConfig`，7 个导出：`SERVICES` / `setBadge` / `readForm` / `writeForm` / `load` / `probe` / `save`。

**新文件**：`services/webui/src/joy_interaction_webui/static/config_services.js`
- IIFE，挂载 `window.JoyConfig`。
- 依赖仅全局 `document` / `fetch` / `console` / `alert`，无跨模块依赖。
- **关键约束**：原 IIFE 末尾 `load()` 立即触发（拉 `/api/services/config` 后 `writeForm` 填表）。若把整个 IIFE 搬进 `<head>` 脚本，`load()` 会在 services-panel DOM 就绪前 fire，导致表单永不被填充。因此**按钮绑定 + `load()` 触发保留在 index.html 内联**（行 ~4873，DOM 已解析），仅抽函数体。

**index.html 改动**：
- `head` 在 `sanitize_static_html.js` 之后插入 `<script src="./config_services.js">`（行 ~3791）。
- 原 IIFE 函数体（原 4874–4944，约 71 行）删除，替换为：
  ```js
  (function () {
      const { readForm, writeForm, load, probe, save } = window.JoyConfig;
      const saveBtn = document.getElementById("svcSaveBtn");
      const probeBtn = document.getElementById("svcProbeBtn");
      if (saveBtn) saveBtn.addEventListener("click", save);
      if (probeBtn) probeBtn.addEventListener("click", probe);
      load();
  })();
  ```
  函数取自 `window.JoyConfig`，调用点经别名工作；`SERVICES`/`setBadge` 仅模块内部使用（grep 确认 index.html 已无 `setBadge`/`SERVICES` 残留）。

**仍被执行的调用点（回归需覆盖）**：
- 行 ~4873 内联 IIFE：`svcSaveBtn`/`svcProbeBtn` 绑定 `save`/`probe`；`load()` 在 DOM 解析后运行，拉配置并 `writeForm` 填 4 个 API 槽；`probe()` 拉 `/api/services/status` 写 4 个 badge（OK/ERR）。

**前端已做的离线自检（不取代 live 尺子）**：
- `node --check config_services.js` → SYNTAX OK。
- Node + 桩（document.getElementById 假元素 / fetch 假后端）执行：`window.JoyConfig` 7 导出齐全；`readForm()` 返回 4 槽结构；`writeForm({...})` 正确写入 `svc-llm-api-base`；`probe()` 按假 status 写 badge `[OK,ERR,OK,OK]`；`load()` 拉配置后写 `svc-llm-model=m1`；`save()` 触发 PUT → ALL OK。
- 静态确认：index.html 无残留 `function readForm`/`function writeForm`/`const SERVICES`；别名与 script 标签就位。

**测试对话回归清单**：
1. `bash scripts/smoke-frontend-baseline.sh` → 期望 9/9 PASS（Block 2 + Block 3 同在 worktree，一并回归）。
2. Playwright 页面加载：① 控制台无**新增** JS 报错（modelSelect 预存报错单列，不因拆分回退）；② `window.JoyConfig` 已定义且含 7 函数；③ Services 面板：加载后 4 个 API 槽被后端配置填充（`writeForm` 生效），4 个 badge 显示 OK/ERR（`probe` 生效）；④ 点击 Save / Probe 分别触发 PUT 与 status 重探。
3. 若动到 capture×3 / Jarvis / TTS UI / memory UI 须一并回归（本 Block 未触及这些）。

**下一块候选**：`applyApiSettings`（行 ~8751，较大的独立函数，可单独成块）或 WebSocket 集群（`connectWebSocket`）。

---

### 测试对话回归确认（Block 2+3 一并，2026-07-21 21:3x，本测试对话执行）

- **9 项冒烟尺子**：`bash scripts/smoke-frontend-baseline.sh` → **PASS=9 FAIL=0、EXIT=0**（live 栈全绿、契约一致、端到端 chat 返回 content）。基线无回归。
- **Playwright 页面加载回归**（headless Chromium 1.61.1，NODE_PATH 指向 npx 缓存）：
  - ① 控制台/页面 JS 报错：**仅预存 `modelSelect.addEventListener` on null 一条，无新增**。该行原始未拆版 `7914`、Block 1 `7807`、本次 Block 2+3 `7587` —— 行号随累计删行（Block2 净删 ~165、Block3 净删 ~71，合计 ~220）整体前移；A/B 对照（Block 1 已做）+ 行号算术证明是拆分工件之前的预存 bug，与 Block 2/3 无关，不阻塞提交（同一条 `modelSelect` issue 跟踪）。
  - ② `window.JoyConfig` 定义 + 7 导出齐全（SERVICES/readForm/writeForm/load/probe/save/setBadge）✅；`window.JoySanitize` 定义 + 7 函数齐全 ✅；`window.JoyRender` 连续性完好（8 函数）✅。
  - ③ `sanitizeStaticHtml('<script>alert(1)</script>')` 经 DOMPurify 净化后不含 `<script>` ✅（Block 2 净化链路通）。
  - ④ Services 面板：`writeForm` 把 live `GET /api/services/config` 全 8 字段精确写入表单（4 个 API 槽 api-base + model/api_key 全部与后端一致）✅；`probe` 把 live `GET /api/services/status` 渲染成 4 个 badge = `OK/ERR/OK/OK`（llm OK、summary ERR/401、tts OK、asr OK）✅。
  - ⑤ Save 按钮 → 捕获到 `PUT /api/services/config` 请求 ✅；Probe 按钮 → 捕获到 `GET /api/services/status` 请求 ✅；点击无 JS 报错、无失败 alert（`dialogs: []`）。
- **结论**：Block 2（静态 HTML 净化外置 `sanitize_static_html.js`/JoySanitize）+ Block 3（配置/API 表单外置 `config_services.js`/JoyConfig）**回归通过，可一并提交**。唯一残留仍为预存 `modelSelect` 报错，单列跟踪，不因本次拆分回退。
- 注：本回归在运行中的未提交改动上执行；测试对话未改动任何业务代码。

## 停止
```
start-joyai.ps1 -Stop
```
