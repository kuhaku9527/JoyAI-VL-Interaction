# 服务真值 — webui（前端 :8099）

> 本文件记录 **webui（:8099 浏览器前端单页应用）** 的已确定决策，覆盖 L2 `D-2026-07-13-032` ~ `D-2026-07-24-039`。
> 所有事实由主理人亲自从 git 提交 + 代码（`services/webui/`）核实（2026-07-28 召回轮，不起子代理）。

---

## D-2026-07-13-032  webui 单页应用（原生 HTML/JS + WebSocket 主链路）

- **事实**: 前端是原生 `index.html` + 模块化 JS，主通信走 WebSocket（视频帧/控制）；HTTP 仅用于配置探测与 Local Wiki 代理。
- **来源**: git `d75faf6`（2026-07-13 整体快照，下限）
- **校验**: `grep -n "default=8099\|--port" services/webui/src/joy_interaction_webui/server.py` → :1175 `default=8099`；`grep -n "WebSocket\|new WebSocket" services/webui/src/joy_interaction_webui/static/index.html` 应命中主链路
- **预期**: server.py 监听 8099；index.html 存在 WebSocket 主链路
- **Drift**: 无
- **Owner**: 前端
- **锁定**: 🔒

---

## D-2026-07-21-033  前端模块化：Blocks 1-5 → `window.Xxx`

- **事实**: 巨型 `index.html` 中的功能块外置为独立 JS 模块，挂到 `window.JoyXxx` 命名空间（如 `window.JoyConfig` / `window.JoyRender` / `window.JoySanitize` / `window.JoyWiki` / `window.JoyWs`），index.html 仅做 IIFE 注册。外部契约不变。
- **来源**: git `c41a0cd`（Block1，2026-07-21）/`08f7436`（Block5，2026-07-22）/`a2256df`（merge，2026-07-22）；原审计记为 PR #3/#4
- **校验**: `grep -n "window.JoyConfig\|window.JoyRender\|window.JoySanitize\|window.JoyWiki\|window.JoyWs" services/webui/src/joy_interaction_webui/static/index.html` → 分别 :1283 / :1434 / :1871 / :3595 / :5106（多模块挂接）
- **预期**: 至少 5 个 `window.JoyXxx` 命名空间被外置模块定义并注册
- **Drift**: 无
- **Owner**: 前端
- **锁定**: 🔒

---

## D-2026-07-24-034  P0 前端质量基座（Vitest + CSS 外置 + a11y）

- **事实**: 补前端测试基座（Vitest）、把内联 CSS 抽成 token 文件、加 a11y 标签 —— 审计（2026-07-23）指出的前端三大缺口。
- **来源**: git `ecfa78d`（#28，2026-07-24）；ADR 关联审计 P0
- **校验**: `ls services/webui/vitest.config.js services/webui/tests/` → vitest 配置 + 测试存在；`grep -n "vitest" services/webui/package.json` → `"test": "vitest run"` + `vitest ^4.1.10`
- **预期**: vitest 配置与测试套件存在；package.json 含 vitest 脚本
- **Drift**: 无
- **Owner**: 前端 / 测试
- **锁定**: 🔒

---

## D-2026-07-26-035  Local Wiki 前端 F1-F4（设置/网络/知识库 UI）

- **事实**: 前端新增 Local Wiki 设置面板：F1 健康检查、F2 健康状态展示、F3 网络设置（代理/provider）、F4 知识库（namespace 列表/同步/删除）。后端路由由 #38 补齐（见 服务-memory-store D-042）。
- **来源**: git `9692d01`（#37，2026-07-26）；ADR-0012
- **校验**: `grep -n "window.JoyWiki\|knowledgeBase\|loadHealth\|loadNetwork\|loadNamespaces" services/webui/src/joy_interaction_webui/static/index.html services/webui/src/joy_interaction_webui/static/wiki_frontend.js` → index.html:3595-3694（JoyWiki 调用）；wiki_frontend.js 定义面板逻辑
- **预期**: 前端存在 JoyWiki 面板 + 健康/网络/namespace 调用
- **Drift**: 无
- **Owner**: 前端
- **锁定**: 🔒

---

## D-2026-07-27-036  F4 syncWiki 真正读取 `wikiNamespace` 显式输入

- **事实**: 修复 F4 知识库同步——此前 syncWiki 用推断的 namespace，现改为读取用户显式输入的 `wikiNamespace` 字段（避免错建 namespace）。
- **来源**: git `c91b22c`（#39，2026-07-27）
- **校验**: `grep -n "wikiNamespace" services/webui/src/joy_interaction_webui/static/wiki_frontend.js` → :183（sync 时读取 input value）/ :205（namespace 输入）
- **预期**: wiki_frontend.js 两处显式读取 wikiNamespace 输入
- **Drift**: 无
- **Owner**: 前端
- **锁定**: 🔒

---

## D-2026-07-23-037  webui 网关代理 memory-store 路由（盲转发）

- **事实**: webui 网关把 Local Wiki 管理请求**盲转发**到 memory-store(:8997)：`GET /v1/providers/health`（B3）、`GET|PUT /v1/settings/network`（B4）、`GET /v1/namespaces`、`POST /v1/external/sync`、`POST /v1/external/ingest-text`、`DELETE /v1/namespaces/{ns}`。memory-store 不可达时优雅 502。
- **来源**: git 代码 2026-07-23（网关契约）；`services/webui/src/joy_interaction_webui/server.py:1219-1221` 等
- **校验**: `grep -n "_proxy_to_memory_store\|/v1/providers/health\|/v1/settings/network\|/v1/namespaces\|/v1/external/sync" services/webui/src/joy_interaction_webui/server.py` → 路由注册（:1219 GET health / :1220 GET network / :1221 PUT network，及 sync/namespaces/ingest/delete 邻近行）
- **预期**: 上述路由均注册到 `_proxy_to_memory_store`
- **Drift**: 无
- **Owner**: 前端 / 后端
- **锁定**: 🔒

---

## D-2026-07-23-038  webui 网关→memory-store 代理超时（30s / 60s）

- **事实**: webui 网关转发 memory-store 的客户端超时：常规代理 `total=30s`（server.py:976），ingest（建库）`total=60s`（:1022）。**这是网关 HTTP 客户端超时，不是前端 LLM 超时**。
- **来源**: git 代码 2026-07-23；`server.py:976` / `:1022`
- **校验**: `grep -n "ClientTimeout(total=30)\|ClientTimeout(total=60)" services/webui/src/joy_interaction_webui/server.py` → :976 =30 / :1022 =60
- **预期**: 两个超时值分处 30/60
- **Drift**: 无
- **Owner**: 前端
- **锁定**: 🔒

---

## D-2026-07-24-039  前端零 timeout/abort（LLM 主链路走 WebSocket）

- **事实**: 前端 `wiki_frontend.js` / `index.html` **无任何 `AbortController` / `signal` / `timeout`**。LLM 主交互走 WebSocket，无 HTTP 超时概念；"30s 报错"是**用户感知**层面（VLM 无响应时 UI 等待），非前端代码设置的 timeout。
- **来源**: 主理人核验 2026-07-24（纠此前误述"前端 30s vs 后端 300s"）；`services/webui/src/joy_interaction_webui/static/wiki_frontend.js`
- **校验**: `grep -nE "AbortController|signal|timeout" services/webui/src/joy_interaction_webui/static/wiki_frontend.js` → **零命中**（确认前端无 timeout）；注意 `server.py` 的 asr.py:133/tts.py:212 等 `total=None` 是 ASR/TTS 客户端、vlm_service.py:764 `total=5` 是 VLM 探测，均非 LLM 主链路前端超时
- **预期**: wiki_frontend.js 无任何 timeout/abort 声明
- **Drift**: 无
- **Owner**: 前端
- **锁定**: 🔒

---

## 关联索引

- 后端网关契约 / 端口：见 `服务-webinfer.md`、`跨域铁律.md`
- Local Wiki 全链路：见 `业务-LocalWiki.md`（D-060~074）
- 网关默认 8996 漂移：见 `跨域铁律.md`（D-L4-015）、`服务-webinfer.md`（D-031）
