# 服务真值 — webinfer（推理网关 :8070）

> 本文件记录 **webinfer（:8070 推理网关）** 的已确定决策，覆盖 L2 `D-2026-07-13-023` ~ `D-2026-07-24-031`。
> 所有事实由主理人亲自从 git 提交 + 代码（`services/webinfer/`）核实（2026-07-28 召回轮，不起子代理）。
> 运行态与决策态分开记；运行态背离见 `Drift` 列。

---

## D-2026-07-13-023  webinfer 是推理单入口（webui 不直连 VLM :7060）

- **事实**: webui 只与 webinfer(:8070) 通信；webinfer 再调 VLM(:7060)。VLM 挂则 webinfer 显式失败，**不回退**到其它模型。
- **来源**: ADR-0006（LLM 网关单入口）+ git `d75faf6`（2026-07-13 整体快照，下限）
- **校验**: `curl -fsS http://127.0.0.1:8070/health` 应 200；`grep -rn "7060" services/webui` 应**零命中**（webui 不直接连 VLM）
- **预期**: webui 仅依赖 8070；VLM 不可达时 8070 返回错误而非静默走旁路
- **Drift**: 无
- **Owner**: 后端
- **锁定**: 🔒

---

## D-2026-07-13-024  delegation 闭环（模型决策 → 委派问题）

- **事实**: VLM 输出含 `</delegation>` 决策 token；webinfer 用 `parse_model_decision` 解析出 `decision / clean_text / delegation_question`，delegation 问题经 background-agent 转交外部工具链。
- **来源**: git `20bd224`（v3.28，2026-07-13）
- **校验**: `grep -n "delegation_question" services/webinfer/infer_loop.py` → 命中 :200 / :615 / :623 / :673 / :681（多处调用 parse_model_decision 并传递 delegation_question）
- **预期**: 每处决策解析都把 delegation_question 透传进 context，无丢弃
- **Drift**: 无
- **Owner**: 后端 / ML
- **锁定**: 🔒

---

## D-2026-07-22-025  memory warmup 信号（asyncio.Event）

- **事实**: 会话首帧触发 memory-store warmup（拉取历史 block）；用 `asyncio.Event`（`_memory_warmed`）作完成信号，未就绪时首问短暂等待，失败则 event 留空可重试（fail-open）。
- **来源**: git `2d53508`（2026-07-22）
- **校验**: `grep -n "_memory_warmed\|_memory_warmup_task\|warmup" services/webinfer/adapter_types.py services/webinfer/memory_io.py` → adapter_types.py:137/139 定义 Event/Task；memory_io.py:124-162 实现；infer_loop.py:151 调用 `memory_store.warmup`
- **预期**: `asyncio.Event` 字段存在且 warmup 失败可被重试（event 不置位）
- **Drift**: 无
- **Owner**: 后端
- **锁定**: 🔒

---

## D-2026-07-21-026  决策解析统一 `parse_model_decision`

- **事实**: 所有"模型输出 → 结构化决策"的解析收敛到单一函数 `parse_model_decision(raw_text)`，避免各调用点各写一套正则（ADR-0008 设计落地）。
- **来源**: ADR-0008 + git `36d271f`/`0be0621`/`84e8ed8`（2026-07-21~22，#2/#3/#4）
- **校验**: `grep -n "def parse_model_decision" services/webinfer/response_format.py` → :50 唯一定义；`grep -rn "parse_model_decision" services/webinfer/infer_loop.py` 仅 import 调用、无重复实现
- **预期**: 全仓仅一处定义 + 多处 import 调用
- **Drift**: 无
- **Owner**: 后端
- **锁定**: 🔒

---

## D-2026-07-21-027  14 个共享常量收敛 `prompt_constants`

- **事实**: 散落各文件的 14 个 prompt/路径常量（系统提示、保存根目录等）抽离到 `prompt_constants.py`，统一 import。
- **来源**: git `49b29cf`（2026-07-21，#3）
- **校验**: `grep -rn "from prompt_constants import" services/webinfer/` → app.py:21 / adapter_types.py:13 / io_utils.py:14 等多处 import；`ls services/webinfer/prompt_constants.py` 存在
- **预期**: 常量定义集中在 prompt_constants.py，无散落硬编码
- **Drift**: 无
- **Owner**: 后端
- **锁定**: 🔒

---

## D-2026-07-21-028  并发竞态 `state.lock` 守卫

- **事实**: 单会话并发请求用 `state.lock`（`asyncio.Lock`）串行化 warmup/recall/read，避免重复拉取与竞态写。
- **来源**: git `2520bf2`（2026-07-21，#4）
- **校验**: `grep -n "async with state.lock" services/webinfer/infer_loop.py services/webinfer/memory_io.py` → infer_loop.py:119/230；memory_io.py:140（warmup 持锁）
- **预期**: 所有对 session 可变状态的并发访问均经 state.lock
- **Drift**: 无
- **Owner**: 后端
- **锁定**: 🔒

---

## D-2026-07-22-029  视频端点决策回归测试

- **事实**: 视频端点（截图帧 → VLM）决策解析路径有专门回归测试守护，防止 delegation/clean_text 回归。
- **来源**: git `d4d0d7f`（2026-07-22，#2 P1-b）
- **校验**: `grep -rln "video" services/webinfer/tests/` 或 `grep -n "def test.*video\|video" services/webinfer/tests/test_*.py` 应命中对应测试
- **预期**: 视频端点决策解析有 pytest 守护
- **Drift**: 无
- **Owner**: 测试
- **锁定**: 🔒

---

## D-2026-07-24-030  `request_timeout_seconds = 300.0`

- **事实**: 推理 HTTP 客户端超时 300 秒（5 分钟），仅管 webinfer→VLM 推理链路；**不是前端超时**（前端走 WebSocket，见 服务-webui D-039）。
- **来源**: git 代码 2026-07-24；`services/webinfer/adapter_types.py:75`
- **校验**: `grep -n "request_timeout_seconds" services/webinfer/adapter_types.py services/webinfer/adapter_core.py` → adapter_types.py:75 定义 `= 300.0`；adapter_core.py:76/86 使用该值
- **预期**: adapter_types.py:75 == 300.0；adapter_core 两处 timeout 引用同一常量
- **Drift**: 无
- **Owner**: 后端
- **锁定**: 🔒

---

## D-2026-07-24-031  ⚠️ 漂移：memory_store url 默认 8996（决策态应为 8997）

- **事实**: webinfer 的 `MEMORY_STORE_URL` 默认 `http://127.0.0.1:8996`（已废弃空壳）。真后端是 8997，当前运行实例靠 `MEMORY_STORE_URL` 环境变量注入覆盖；默认拉起会连错端口。
- **来源**: 代码默认 `services/webinfer/app.py:350`（默认 8996）+ `memory_store_client.py:87`（读 `MEMORY_STORE_URL` env）。运行实例探针确认实际连 8997。
- **校验**: `grep -n "8996" services/webinfer/app.py` → :350 默认 8996；`curl -fsS http://127.0.0.1:8070/health` 中 `memory_store.url` 字段应显示 8997（env 注入）
- **预期**: 决策态=连 8997；默认代码=8996 须由 env 覆盖。与 跨域铁律 D-L4-001（端口铁律）、启动链路 D-008 同源漂移，~~待 #43 统一修复（脚本默认改 8997 或强制注入）~~ **已由 PR #83/#84（D-034 端口固定 8997 / D-035 webui 网关导出）闭环，归属非 #43（#43=视频采集延迟调研）**。modified: 2026-08-07｜by AI｜approved: 用户。
- **Drift**: 代码默认 8996 ≠ 运行期望 8997（脚本默认漂移）；已由 run-windows.env 8997 覆盖 + server.py 默认升 8997（D-034/D-035 / PR #83/#84）闭环，归属非 #43。
- **Owner**: DevOps / 后端
- **锁定**: 🔒（已由 D-034/PR #83/#84 闭环；非 #43）


---

## D-2026-07-29-032  wiki recall fire-and-forget（chat 主路径解耦 memory-store）

- **事实**: `_memory_recall`（`services/webinfer/memory_io.py`）不再 `await self._memory_wiki_recall(...)`；改为 `self._schedule_wiki_recall(state, question)`，内部 `asyncio.create_task` 异步执行。主 chat 路径立即返回，wiki 召回异步进行；下一次 chat 会看到 `_memory_wiki_cache` 已填充。
- **来源**: ADR-0013 + `doc/specs/memory-client-resilience.md` S-1 + git diff `services/webinfer/memory_io.py`（本轮）
- **校验**: `grep -n "_schedule_wiki_recall\|asyncio.create_task" services/webinfer/memory_io.py` → 应在 `_memory_recall` 内见 `_schedule_wiki_recall(state, question)` 调用 + 类内新方法定义
- **预期**: chat 延迟与 memory-store 状态解耦；memory-store 不可达时第一次 chat <300ms 返回（不阻塞），后续 chat 走缓存路径
- **Drift**: 无
- **Owner**: 后端
- **锁定**: 🔒

---

## D-2026-07-29-033  memory-store 客户端熔断器 v0.3（3 失败 / 30s 冷却）

- **事实**: `MemoryStoreClient`（`services/webinfer/memory_store_client.py`）新增客户端内置熔断器：`_CB_FAILURE_THRESHOLD=3` 连续失败后开路 30s（`_CB_COOLDOWN_S=30.0`），所有 `recall`/`warmup`/`push` 调用在开路期短路返回 `[]` 不打网络。`recall/warmup` 的 try/except 与非 200 分支分别调 `_record_failure`；200 响应后 `_record_success` 重置计数。
- **来源**: ADR-0013 + `doc/specs/memory-client-resilience.md` S-2 + git diff `services/webinfer/memory_store_client.py`（本轮）
- **校验**: `grep -n "_circuit_open\|_record_failure\|_record_success\|_CB_FAILURE_THRESHOLD\|_CB_COOLDOWN_S" services/webinfer/memory_store_client.py` → 至少 5+ 命中（字段 + 3 个辅助方法 + 3 处调用点短路 + warmup/recall try 块内记录）
- **预期**: memory-store 宕机时 `LOGGER.warning("memory-store circuit OPEN for 30s after 3 failures")` 出现一次；之后 30s 内零网络请求；30s 后探测被放行（成功关路 / 失败继续开路）
- **Drift**: 无
- **Owner**: 后端
- **锁定**: 🔒

---

## D-2026-07-29-034  memory-store 端口固定 8997（脚本默认覆盖空壳 8996）

- **事实**: `services/scripts/run-windows.env` 新增四行：`MEMORY_PORT=8997`、`MEMORY_STORE_URL=http://127.0.0.1:8997`、`JOYAI_MEMORY_STORE_URL=http://127.0.0.1:8997`、`JOYAI_ENABLE_MEMORY_STORE=1`。memory-store launcher（`Start-MemoryStore`）启用默认开（不再是 opt-in）。
- **来源**: ADR-0013 同时客客的 D-L4-001 端口铁律 + DRIFT-2 关闭在 commit HEAD 的 `services/scripts/run-windows.env` + 同 `services/scripts/run-windows.ps1` 的 Start-MemoryStore 部分
- **校验**: `grep -n "MEMORY_PORT|MEMORY_STORE_URL|JOYAI_MEMORY_STORE_URL|JOYAI_ENABLE_MEMORY_STORE" services/scripts/run-windows.env` → 4 匹中和；`grep -n "JOYAI_ENABLE_MEMORY_STORE|Start-MemoryStore" services/scripts/run-windows.ps1` → 默认开通不再 opt-in
- **预期**: 脚本默认连 8997 真后端；webinfer 启动后 `memory_store.url` = http://127.0.0.1:8997
- **Drift**: 无（DRIFT-2 已闭环）
- **Owner**: DevOps / 后端
- **锁定**: 🔒


---

## D-2026-07-29-035  webui 网关 导出 JOYAI_MEMORY_STORE_URL（端口铁律）

- **事实**: `services/scripts/run-windows.ps1:Start-Webui` 的 env 列表新增 `JOYAI_MEMORY_STORE_URL`（优先从 `$env:JOYAI_MEMORY_STORE_URL`，默认走 `$P.MemoryStore`）；`services/webui/src/joy_interaction_webui/server.py:958` in-code 默认从 8996 → 8997（环境 env 仍然最优先）。
- **来源**: DRIFT-3 关闭在 commit HEAD；符号 D-034 的 server.py 端要交服务端；符号 D-032/033 的 spec/ADR
- **校验**: `grep -n "JOYAI_MEMORY_STORE_URL" services/scripts/run-windows.ps1 services/webui/src/joy_interaction_webui/server.py services/scripts/run-windows.env` → 三个文件均出现；`curl -s http://127.0.0.1:8099/v1/providers/health` → 连 8997 不报 "Cannot connect to host 127.0.0.1:8996"
- **预期**: webui 启动后内部 `MEMORY_STORE_URL` = http://127.0.0.1:8997；server.py 默认 8997 只在 env 未注入时用
- **Drift**: 无（DRIFT-3 已闭环）
- **Owner**: 后端
- **锁定**: 🔒

---

## 关联索引

- 推理上游 VLM：见 `服务-VLM.md`（D-020/021/022）
- 前端调用方：见 `服务-webui.md`（D-032~039）
- 端口铁律 / 8996 vs 8997：见 `跨域铁律.md`（D-L4-001）、`启动链路.md`（D-008）
- 记忆 warmup/recall 落地 memory-store：见 `服务-memory-store.md`、`业务-决策记忆.md`
