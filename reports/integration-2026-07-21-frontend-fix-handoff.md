# 前端修复 Handoff — 2026-07-21（测试对话回归用）

承接 `integration-2026-07-21.md` 的 Block 4 结论：**Block 4 抽取本身正确、可交付、零新错**，
但测试对话指出 live 功能项 ③/④ 需修 `modelSelect` + `apiBaseUrl`/`apiKey` 旧引用，且 `resetSession` 无调用点。
本文件记录前端对话的修复与交付状态。

## 状态总览
| 项 | 状态 | 链接/提交 |
|---|---|---|
| PR #1（里程碑2 结构拆分 Blocks 1-4） | ✅ 已合并 | merge commit `a2256df` → `main` |
| PR #3（live 引用修复 + Reset Session 接线） | 🟡 已开 PR，待测试对话回归 | https://github.com/kuhaku9527/JoyAI-VL-Interaction/pull/3 |
| PR #2（后端 P0 修复） | 依赖 PR #1 已解除 | base `milestone2-adapter-core-split`=082b916，现已在 `main` 内 → 可合 |

## PR #1 合并要点（后端要求先合，以解锁 PR #2）
- 合并方式：**merge commit**（非 squash/rebase），保留 `a689329` 为祖先 → PR #2 不会脱钩。
- 验证：`a2256df` 的父为 `[ff79b3b(old main), 082b916]`；`082b916` ⊃ `a689329` → `main` 现含 `a689329`。
- `082b916` 内容 = Block1(c41a0cd) → Block2+3(0bddc28) → Block4(082b916)，无 P0 污染。

## PR #3 修复内容（仅 `index.html`，前端）
根因：Block 3 把 API 表单字段改名为服务作用域的 `svc-*` id，导致旧 `modelSelect`/`apiBaseUrl`/`apiKey`
指向已不存在的元素，且 `apiBaseUrl`/`apiKey` 从未重新声明。单体在首个 `modelSelect.addEventListener`（null）处整体中止，
且 `applyApiSettings`(joy_ws.js) 从未拿到 `register()` 上下文 → ③/④ 全断。

1. **声明修正**（~4383）：`modelSelect/apiBaseUrl/apiKey` 重新指向 `svc-llm-model` / `svc-llm-api-base` / `svc-llm-api-key`。
2. **`fetchModels` 重写**：原逻辑用 `innerHTML='<option>'` + `appendChild` 构建下拉；`svc-llm-model` 是 `<input type=text>`，
   `appendChild` 会抛错。改为设 `.value`（无模型时自动选首个并 `applyApiSettings({showFeedback:false})`）。
3. **`refreshModelsBtn` 守卫**：该按钮被 Block 3 删除（由 Services 面板的 Probe 取代），但其 `addEventListener` 仍在
   顶部层级执行 → 会抢在 `register()`(8684) 之前崩溃。加 `if (refreshModelsBtn)` 守卫。
   （`fetchModels` 仍会在加载期与 API Base 变更时经 `applyApiSettings({refreshModels:true})` 触发。）
4. **`detectServices` hintDiv 守卫**：`svc-llm-api-base` 无 hint 兄弟节点，原 `hintDiv.textContent` 会抛（已在 try 内被吞，
   但会跳过后续；加 null 守卫避免噪音）。
5. **Reset Session 按钮**：在视频浮层控制区加 `<button id="resetSessionBtn">`，并在 `resetSession` 定义后接线
   `resetSession({clearConversation:true, cleanupServer:true})`（原 `resetSession` 无任何调用点）。

## 离线自检（不取代 live 尺子）
- `node --check` 四个模块（joy_ws / config_services / sanitize_static_html / render_markdown）：全过。
- 内联单体 `<script>`（226 KB）经 `vm.Script` 编译：无语法错误。
- 静态审计：脚本内所有 `getElementById('X')` 里，缺失对应 HTML 元素的 id 全列出；其中唯一会在顶部层级 `addEventListener`
  崩溃的 `refreshModelsBtn` 已守卫；`apiPresetsBtn` 原已 `if` 守卫；`apiKeyField`/`apiKeyToggle` 仅在函数内惰性解引用（被 try/catch 或异步包裹，不中止单体）。
- 等价测试对话早前 relay 的诉求：modelSelect + apiBaseUrl/apiKey 现已读到 live `svc-*` 值。

## 测试对话回归清单（PR #3）
1. `bash scripts/smoke-frontend-baseline.sh` → 期望 9/9 PASS。
2. Playwright 页面加载：① 控制台**无** JS 加载崩溃（修复前 `modelSelect.addEventListener` 整体中止 → 现在应消失）；
   ② `window.JoyWs` 定义且含 `register`/`applyApiSettings`/`cleanupServerSession`；
   ③ **live ③**：WS 连上后页面加载经 `connectWebSocket` onopen 发 `update_model`，且 `svc-llm-model` 被 `fetchModels` 正确填充/应用；
   ④ **live ④**：改 `svc-llm-api-base`/`svc-llm-api-key`（即旧 `apiBaseUrl`/`apiKey`）触发 blur/change → 无报错、`applied` 闪烁出现、`update_model` 出站；
   ⑤ **Reset Session 按钮**：点击捕获到 `POST /api/session/cleanup`（`cleanupServerSession` 生效），且新 session 重连 WS。
3. 注意：本次只改 API 设置 / session 清理 / 模型字段读取路径，未触及 capture×3 / Jarvis / TTS / memory UI。

## 共享工作树事故（重要，给测试对话预警）
- 现象：本对话编辑中途，共享工作树被另一并发对话 `git checkout fix/adapter-p0-correctness`，导致本地 `HEAD` 漂到 `d4d0d7f`、
  且 `joy_ws.js`/`config_services.js`/`sanitize_static_html.js` 在磁盘上"消失"（→ 8099 若从该树起服会 404）。
- 处置：通过 `git reflog` 确认远程 `milestone2-adapter-core-split` 仍为 `082b916`（本对话此前 force-push），
  `git checkout milestone2-adapter-core-split` 即可恢复干净工作树（远程未被动）。**结论：并发对话共享同一工作树会无声覆盖/回退另一对话的分支。**
- 建议：测试对话继续用独立 `git worktree`（如 `D:/tmp/joyai-ms2`）跑回归，避免 stash/checkout 事故；本对话已切回 `fix/webui-live-refs` 分支。

## 下一块候选
`connectWebSocket`（~240 行，Block 5）——沿用 `window.JoyWs` 的 `register` 桥，把 `websocket`/`sessionId`/`isAnalysisRunning`/
`resultText`/`lastText` 等可重赋闭包变量以访问器暴露给模块。这是最大、耦合最深的块，建议拆分前先与测试对话确认 live 栈可拉起再做。

---

## 测试对话回归结论（2026-07-22）

环境：栈 `8070`(webinfer)/`8985`(TTS)/`8996`(memory-store)/`8099`(webui) 在跑；`7060`(llama VLM) 关机（省显存）。
8099 服务的是 PR #3 修复版（served HTML 含 `resetSessionBtn`/`svc-llm-model`/`joy_ws.js` 标签 → 已确认是修复版）。

### 1) 9 项尺子：7/9 PASS（2 项环境阻断，非前端回归）
- PASS：① WebUI 首页 / ② detect-services 契约(8070/v1+8985) / ③ summarizer 代理 / ④ /ws 路由 / ⑤ webinfer 健康+memory_store.healthy / ⑦ TTS minimax_ok / ⑧ memory-store ok
- FAIL（环境）：⑥ `llama /health -> 000`（7060 关）；⑨ 端到端 `8070→7060` chat → `Connection error`（7060 关，webinfer 连不上 llama）
- 结论：**无前端回归**；⑥/⑨ 失败纯因 llama 未起，与 PR #3 无关。

### 2) Playwright 页面加载（headless Chromium 1.61.1）
- ① **PASS**：`modelSelect.addEventListener on null` 崩溃已消失（pageerror 不含 modelSelect；PR #3 主修复生效）。
- ② **PASS**：`window.JoyWs` 定义且含 `register`/`applyApiSettings`/`cleanupServerSession`。
- ③/④/⑤ **BLOCKED（未通过）**：init 在 `updatePromptAvailability`（index.html:7430 `processEvery.disabled = isAnalysisRunning`）抛
  `TypeError: Cannot set properties of null (setting 'disabled')`，栈 `updatePromptAvailability @ 7430 ← @ 8678`（顶部层级）。
  该崩溃**中止内联脚本**，导致 `register()`(8684) 未执行、`connectWebSocket` 未真正建连
  （`wsUrls:[]`、`wsSentCount:0`）→ update_model 出站 / Reset Session cleanup POST 均无法验证。

### 3) 根因（供前端对话修复）
- **`processEvery` / `framesPerBatch` 两个 `<input>` 在模块化过程中被删**：
  原 `ff79b3b`(main) 有 `id="processEvery"`(4067) 与 `id="framesPerBatch"`(4072)；
  到 `a689329`（模块化基线，当前 main 祖先）已消失，PR #3 仍未恢复。这是**前端模块化自有回归**（非原始 app bug）。
- 内联脚本在 4387-4388 声明 `const processEvery/framesPerBatch = getElementById(...)`（得 null），并在
  `updatePromptAvailability`(7430/7432) 与 `connectWebSocket` 的 `server_config` handler(9106/9109/9136/9139) 中**无守卫**使用 → 崩溃。
- 该 bug 被 PR #3 之前的 `modelSelect` 崩溃掩盖；PR #3 修好 `modelSelect` 后才暴露（whack-a-mole）。

### 4) 全量缺失 id 审计（13 个被引用但 HTML 无此 id）
`apiBaseHint, apiKeyField, apiKeyToggle, apiPresetsBtn, apiPresetsMenu, **framesPerBatch**, **processEvery**, refreshModelsBtn, rtspControls, screenControls, startBtn, stopBtn, webcamControls`
- 已安全：`startBtn`/`stopBtn`(4775+)、`apiPresetsBtn` 已有 `if` 守卫；`apiKeyField`/`apiKeyToggle` 仅函数内惰性解引用；`refreshModelsBtn` 已由 PR #3 守卫。
- **唯 `processEvery`/`framesPerBatch` 在顶部层级 init 路径无守卫 → 本次崩溃元凶**。恢复后应重测是否还有下一处。

### 5) 修复建议（前端对话，并入 PR #3 或新 PR）
- 恢复 `<input type="number" id="processEvery" value="1" min="0.1" max="60" step="0.1">` 与
  `<input type="number" id="framesPerBatch" value="1" min="1" max="30" step="1">`（含其容器/label，原在 settings 区；CSS 见 ff79b3b:3001-3064）。
- 防御性给 `updatePromptAvailability` 与 `connectWebSocket` server_config handler 的 `processEvery`/`framesPerBatch` 引用加 `if` 守卫。
- 恢复后由测试对话重跑：9 项尺子 + Playwright（①/② 已绿，重点验 ③ update_model 出站、④ api-base/key 变更触发 update_model、⑤ Reset Session → POST /api/session/cleanup + WS 重连）。

### 6) 当前裁决
- PR #3 的代码改动**正确**，修复了 `modelSelect`（①/② PASS）；但**未达 live 验收标准 ③/④/⑤**——
  因模块化期移除的 `processEvery`/`framesPerBatch` 导致 init 仍崩溃。需前端对话补修复（恢复元素 + 守卫）后再回归。

---

## 前端对话补修（2026-07-22，并入 PR #3）

按测试对话裁决执行。结果：**③/④/⑤ 全部 PASS，页面零 JS 崩溃**。

### A) 修复 1 — 恢复 `processEvery`/`framesPerBatch`（功能必需）
- 在 RTSP 捕获块内、RTSP Beta Warning 之后恢复两个 `<input>`（含 `<label>` + `.input-hint`），
  与原 `ff79b3b` 布局一致：`id="processEvery"`(value=1, 0.1–60, step 0.1)、`id="framesPerBatch"`(value=1, 1–30, step 1)。
- CSS 未丢（`#processEvery` 在 3014/3025/3044/3077 仍存在），无需补。
- 防御性守卫（防未来再删元素时崩溃 init）：
  - `updatePromptAvailability`(7440-7447)：`if (processEvery)` / `if (framesPerBatch)` 包裹 `.disabled`/`.title`。
  - `connectWebSocket` server_config handler(9106-9111, 9136-9139)：`process_interval`/`frames_per_batch` 赋值加 `&& processEvery`/`&& framesPerBatch`。
  - 顶部 `addEventListener`(change/blur ×2)：`if (processEvery) processEvery.addEventListener(...)` / `if (framesPerBatch) ...`（8788/8806/8824/8840）。

### B) 修复 2 — 又一处 whack-a-mole：`checkApiKeyRequirement` 崩溃
- 恢复 `processEvery` 后 init 不再中止，WS 连上、`server_config` 带回 `api_base` → 调 `checkApiKeyRequirement(apiBaseUrl.value)`(9116) 抛
  `TypeError: Cannot read properties of null (reading 'classList')`：`apiKeyField`/`apiKeyToggle` 被 Block 3 的 `svc-*` 表单**有意取代**
  （旧表单用折叠控件显隐 API Key；新 `svc-llm-api-key` 是直显密码框），故这俩元素**非误删、是重构移除**。
- 修法：**守卫**而非恢复——`checkApiKeyRequirement`(7411-7421) 的 `apiKeyField`/`apiKeyToggle` `.classList` 调用加 `if (apiKeyField && apiKeyToggle)`，
  元素缺失时安全 no-op（svc 表单始终显密钥框，无需折叠）。
- 顺带守卫 `apiBaseHint` 用法(8788-8790)：`if (hint) hint.textContent = …`（同属 Block 3 移除、仅函数内引用）。

### C) 重测结论（同环境：8099/8070/8985/8996 在跑，7060 关）
- **Playwright**：`pageErrors: []`（零 JS 崩溃）、`modelSelectCrash:false`、② `window.JoyWs` 定义。
  - ③ `updateModelOnOpen:true`（WS onopen 发 `update_model`，`svc-llm-model`=streaming-infer-adapter 已应用）✅
  - ④ `updateModelOnChange:true`（改 api key 触发 `update_model` 出站）、`errorsAfterChange:0` ✅
  - ⑤ `cleanupPostSeen:true` + `sessionIdChanged:true`（Reset Session → `POST /api/session/cleanup` + WS 新 session 重连）✅
  - `wsSentCount:14`，控制台仅剩环境噪声：无摄像头 `NotSupportedError`、某探测 `400`（非前端崩溃）。
- **9 项尺子**：7/9 PASS（⑥/⑨ 因 7060 关环境阻断，与本次无关；无前端回归）。
- 剩余 11 个"被引用但无元素"的 id 全部已被守卫路径覆盖，运行时零崩溃。

### D) 更新裁决
- **PR #3 现达成 live 验收标准**：①/②/③/④/⑤ 全 PASS，页面零 JS 崩溃。可合并入 `main`。
- 下一步：Block 5（`connectWebSocket` 窄抽取）基于合并后的 `main` 开分支实施。
