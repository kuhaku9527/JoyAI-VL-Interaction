# Handoff: Block 5 — connectWebSocket 抽取（前端对话 → 测试对话）

> 来源分支：`fix/webui-block5-connectws`（base `origin/main` @ `bbf8b61`，PR #3 已合并）
> 改动文件：`services/webui/src/joy_interaction_webui/static/index.html` + `joy_ws.js`

## 1) 本次做了什么（窄抽取）

`connectWebSocket`（原 ~240 行，是整个 server→client 协议路由 `ws.onmessage` 所在地，引用约 30 个闭包符号，其中 `websocket`/`sessionId` 在运行时重赋值）按**窄抽取**策略拆分：

- **外置到 `joy_ws.js`（`window.JoyWs.connectWebSocket`）**：WebSocket 创建、`onopen`/`onerror`/`onclose`、断线 2s 重连、首次连接后 `applyApiSettings` 应用模型。`websocket`/`sessionId` 经 `setWebSocket`/`getSessionId` 实时访问器与内联脚本的单一真相源同步。
- **保留内联 `dispatchServerMessage(event)`**：原 `ws.onmessage` 协议体作为内联函数留在 monolith 闭包内（因为它重赋值 `sessionId`/`serverConfigApplied`/`lastText`/`fadeTimeout`，必须留在单一真相源）。经 `JoyWs.register({ dispatchServerMessage })` 桥接，`connectWebSocket` 用 `ws.onmessage = dispatchServerMessage` 接线。
- **桥接引用收敛到 ~9 个**：`getWebSocket`/`setWebSocket`/`getSessionId`/`installLlmReplyHandler`/`updateStatus`/`modelSelect`/`isValidModelName`/`fetchModels`/`dispatchServerMessage`（含原 `apiBaseUrl`/`apiKey`）。
- **原 `connectWebSocket` 改为 1 行别名**：`function connectWebSocket() { window.JoyWs.connectWebSocket(); }`，6 个调用点（capture 启动 ×3、`init` 加载、`resetSession`、页面 `load`）零改动。
- **stale-socket 守卫语义保留**：原 `if (websocket !== ws) return;` 改为 `if (websocket !== event.target) return;`（事件目标即触发消息的 socket），行为等价。

## 2) 回归验证结果（前端对话已自测）

环境：8099/8070/8985/8996 在线，7060(llama) 关机。

| 检查 | 结果 | 说明 |
|------|------|------|
| 语法编译（vm.Script 内联 + joy_ws.js） | ✅ | 0 错误 |
| 页面加载 `pageerror` | ✅ 0 | register 无异常；`window.JoyWs.connectWebSocket` / 别名 / `dispatchServerMessage` 均定义 |
| ① 无 `modelSelect` 崩溃 | ✅ | — |
| ② `window.JoyWs` 定义 | ✅ | register/applyApiSettings/cleanupServerSession/connectWebSocket 齐全 |
| ③ WS onopen 发 `update_model` | ✅ | `updateModelOnOpen:true` |
| ④ 改 api-base/key 触发 `update_model` | ✅ | `updateModelOnChange:true`，`errorsAfterChange:0` |
| ⑤ Reset Session → `POST /api/session/cleanup` + WS 重连 | ✅ | `cleanupPostSeen:true`，`sessionIdChanged:true`（cleanup POST 返回 400 系 7060 关、非前端） |
| 9 项尺子 | ✅ 7/9 | ⑥ llama /health 000、⑨ 端到端 chat Connection error 均因 7060 关，与前端无关 |

## 3) 测试对话复测清单

- `bash scripts/smoke-frontend-baseline.sh` → 期望 7/9（7060 关时 ⑥/⑨ 环境阻断）
- Playwright（headless）：① 无 `modelSelect`/`processEvery` 崩溃 ② `window.JoyWs` 含 `connectWebSocket` ③ onopen `update_model` 出站 ④ 改 `svc-llm-api-base`/`-api-key` 触发 `update_model` ⑤ Reset Session 按钮 → `POST /api/session/cleanup` + WS 新 session 重连
- 若起 7060 应达 9/9

## 4) 备注

- 抽取未触动任何业务逻辑，仅重排归属；行为等价（含重连、stale-socket 守卫）。
- 完整栈由前端对话手动拉起（webui/webinfer/voice-clone/memory-store 在跑，7060 关）；测试对话可直接复测，无需重启服务。
- 分支可合并 `main`（base 已含 PR #3）。合并后如需继续 BLOCK 6+，同理基于 `main` 开分支。

## 测试对话回归结论（Block 5，2026-07-22 下午） —— ✅ 通过

- 环境：直接复测前端对话已在跑的完整栈（8099 服务 `fix/webui-block5-connectws`@`08f7436` 的 Block 5 代码；8070/8985/8996 在线；7060 关）。**未建 worktree、未重启服务、未碰共享工作树**——纯只读 HTTP/Playwright 复测（遵循共享工作树事故教训）。
- **9 项尺子 7/9 PASS**：⑥ llama /health=000、⑨ 端到端 chat Connection error 均因 7060 关（环境阻断），非 Block 5 回归（脚本 "!! 存在回归" 是对 FAIL 的通用输出，实为环境项）。其余 7 项全绿。
- **Playwright（headless 1.61.1）全绿**：
  - ② `window.JoyWs` **4 导出齐全**（register / applyApiSettings / cleanupServerSession / **connectWebSocket**）——Block 5 新导出确认存在。
  - ① `pageErrors:[]`，`crashSig` 空——无 `modelSelect`/`processEvery` 崩溃。
  - ③ `updateModelOnOpen:true`——onopen 经 `JoyWs.connectWebSocket` 发 `update_model`（本次共 5 次出站）。
  - ④ 改 `svc-llm-api-base`/`-api-key` → `updateModelOnChange:true` + `appliedFlash:true`（applied 闪烁出现）+ `errorsAfterChange:0`。
  - ⑤ Reset Session → `cleanupPostSeen:true`（捕获 `POST http://127.0.0.1:8099/api/session/cleanup`）+ `wsReconnected:true` + `sessionIdChanged:true`（重连 session `0fc497f2…` → `d3e27ea5…`）。
  - WS 实测 `ws://127.0.0.1:8099/ws?session_id=…`（WebUI `/ws` 代理）；reset 后第二条连接 session_id 变更 → **stale-socket / 重连守卫行为等价保留**。
- **结论**：Block 5 窄抽取**行为等价**——连接生命周期外置 `joy_ws.js` 后，WS 连接 / onopen update_model / api-base 变更触发 update_model / Reset Session cleanup + 重连全链路正常，零 JS 崩溃。PR #3 的 live 项 ③/④/⑤ 在 Block 5 后仍全部通过。**可合并 main**。
- 资源：未起 7060（遵循省显存规则，且 ③/④/⑤ 不需 7060）；未建 worktree；临时 Playwright 脚本在系统 temp（非仓库）。
