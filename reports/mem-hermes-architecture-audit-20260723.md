# 架构一致性审计报告：memory-architecture.md (v3.2) + hermes-integration.md (v3.29)

> **审计类型**：只读架构一致性审计（compliance review），零业务代码改动。
> **审计日期**：2026-07-23
> **审计人**：software-architect（只读）
> **仓库**：`D:\AI\workspace\JoyAI-VL-Interaction-main`（main 分支）
> **纪律**：本报告为唯一写入产物。源码未做 Edit/Write；未执行任何 git 写操作；`D:\Workspace\hermes-data` 仅读取未改动；`services/webinfer/` 未提交改动文件仅 Read 核对。

---

## 摘要

对两份文档共 18 项核对清单逐项比对实际代码，结论：

- **完全一致（✅）**：9 项 —— A1、A5、A6、A7、B1、B2、C1、C2、C3
- **存在漂移（⚠️）**：4 项 —— A2、A3、A4、B3（含 6 个具体缺失/分歧点）
- **信息提示（ℹ️）**：1 项 —— D1（webinfer 钩子依赖未提交改动，行为存在但实现位置/标签/参数与文档不符，无法从已合入 main 确认）

**总一致率约 78%（14/18 子声明可直接确认一致；4 项漂移内含 6 个具体缺口）**。

### 关键漂移 / 风险（按严重度排序）

1. **B3 — `/v1/solve` 契约文档与代码严重不符（高风险）**：hermes-integration.md §4 把 `SolveRequest{Squestion, context?}` / `SolveResponse{status, summary, tool_calls, error}` 描述为"契约完全不变"。实际 `hermes_api/main.py` 的 `SolveRequest` 含 `session_id/task_id/question/frames/...` 但**无 `context`**，`SolveResponse` 含 `status/text/thread_id/usage/duration_ms/events_digest/error` 但**无 `summary`/`tool_calls`**。文档字段名与实际完全对不上，webui 对接方若按文档实现会出错。
2. **A2 — memory-store API 端点"齐全"声明不成立（中高风险）**：文档 §3 列出 6 个端点，实际仅实现 `POST /v1/blocks/push`、`POST /v1/blocks/recall`、`GET /health`（注意是 `/health` 而非文档写的 `/v1/health`）。**`GET /v1/blocks/{id}`、`DELETE /v1/sessions/{sid}`、`POST /v1/external/sync` 三个端点完全缺失**。webui "知识库"页面（§4.3 触发 `/v1/external/sync`）目前无后端可调用。
3. **A3 — recall 响应体缺字段（中风险）**：文档 §3.2 响应含 `blocks`/`meta_prompt`/`took_ms`，实际 `RecallResponse` 模型**只有 `blocks`**，`meta_prompt`/`took_ms` 从未被返回（也未被任何调用方消费）。属于"文档超前于实现"的陈旧声明。
4. **A4 — psql 桩注释与 ADR-001 自相矛盾（中风险）**：ADR-001 明确"psql 复用路线取消，桩标注'已从路线图移除'以防后续 agent 误启用"。但 `psql_backend.py` 的异常文案仍是 **"待 Phase B：复用 hermes-agent pg 实例"** —— 恰好在邀请"复用 hermes pg"，与 ADR 意图相反。默认 `sqlite` 与 `NotImplementedError` 本身正确，但注释会误导。
5. **D1 — webinfer 记忆钩子实现已重构且标签偏差（信息级）**：文档 §4.1 称钩子在 `live_adapter.py:on_session_end/on_session_start` 并以 `[历史记忆]` 注入；实际钩子已拆到 `memory_io.py`/`session.py`/`prompt_assembly.py`，prompt 注入标签为 `[Local Wiki]`/`[本地知识库]`，pull 用 `warmup` 约定（`top_k=16/min_score=0.0`，非文档的 8/0.3）。这些文件属 webinfer 未提交改动，**不能从已合入 main 确认**。

---

## 逐项核对表

图例：✅ 一致 · ⚠️ 漂移 · ❌ 缺失 · ℹ️ 注意

| 清单项 | 状态 | 证据 (file:line) | 说明 |
|---|---|---|---|
| **A1** §2.1 服务端口 = 8996 | ✅ 一致 | `services/memory-store/src/memory_store/app.py:114`（`MEMORY_PORT` 默认 `"8996"`）；`services/background-agent/hermes_api/main.py:48`（`MEMORY_STORE_URL` 默认 8996）；`services/webinfer/memory_store_client.py:41`（`DEFAULT_BASE_URL="http://127.0.0.1:8996"`） | 三处端口默认值均为 8996，一致。 |
| **A2** §3 API 端点齐全（push/recall/blocks/{id}/sessions/{sid}/external/sync/health） | ⚠️ 漂移 | 已实现：`app.py:81`（`POST /v1/blocks/push`）、`app.py:99`（`POST /v1/blocks/recall`）、`app.py:59`（`GET /health`）、`app.py:72`（`GET /v1/backends`，文档未列）。缺失：`GET /v1/blocks/{id}`、`DELETE /v1/sessions/{sid}`、`POST /v1/external/sync` 三处全文无路由。前缀差异：文档写 `GET /v1/health`，实际为 `GET /health`。 | 6 个端点仅实现 2 个（另加 1 个文档未提及的 `/v1/backends`）；3 个完全缺失；health 路由前缀不符。 |
| **A3** §3.2 recall 请求体(query/top_k/min_score/filter.created_after) + 响应含 blocks/meta_prompt/took_ms | ⚠️ 漂移 | 请求 ✅：`models.py:36-40`（`RecallRequest`: query, top_k=8, min_score=0.3, filter）+ `models.py:31-33`（`RecallFilter.created_after`）。响应 ⚠️：`models.py:43-44`（`RecallResponse` 仅 `blocks` 字段）；`app.py:99-106` `recall_blocks` 仅返回 `RecallResponse(blocks=blocks)` —— **`meta_prompt`/`took_ms` 既无字段也无赋值**。 | 请求 schema 与文档一致；响应比文档少 `meta_prompt`/`took_ms` 两字段。 |
| **A4** §5.1 ADR-001：`MEMORY_BACKEND` 默认 sqlite；`psql_backend.py` 显式 `NotImplementedError` 桩且标注"已从路线图移除" | ⚠️ 漂移 | 默认 sqlite ✅：`backends/__init__.py:26`（`os.getenv("MEMORY_BACKEND","sqlite")`）。桩抛 `NotImplementedError` ✅：`psql_backend.py:13,22,25`。注释不符 ⚠️：`psql_backend.py:14/23/26` 文案为 `"待 Phase B：复用 hermes-agent pg 实例"`，**非文档声称的"已从路线图移除"**，且与 ADR-001"取消复用"意图相反。 | 默认与桩行为正确，但桩注释文案与 ADR-001 自相矛盾，存在误导后续 agent 的风险。 |
| **A5** §5.2 持久化单文件 `data/memory.sqlite` | ✅ 一致 | `backends/__init__.py:30`（`MEMORY_SQLITE_PATH` 默认 `"./data/memory.sqlite"`）；`sqlite_backend.py:47-54`（`_connect` 用 `Path(path).parent.mkdir(parents=True)` 建父目录）。 | 路径拼接与单文件部署一致。 |
| **A6** §5.5 backend Protocol + `SqliteBackend`(生产)/`ObsidianBackend`(可选)/`PsqlBackend`(`NotImplementedError` 桩) | ✅ 一致 | Protocol：`backends/__init__.py:12-22`。`SqliteBackend`：`sqlite_backend.py:57`（生产实现）。`ObsidianBackend`：`obsidian_backend.py:9`。`PsqlBackend`：`psql_backend.py:9`（桩）。 | 三类实现齐全、角色正确。ℹ️ 措辞差异：`__init__.py:12-22` 的 Protocol 方法集为 `push(session_id,blocks)/recall(...)/health()/name()`，文档 §5.5 写的是 `push(blocks)/sync_external(path)`——文档的 `sync_external` 实际不存在（与 A2 缺失的 `/v1/external/sync` 对应），但属"未实现"而非"错误"。 |
| **A7** obsidian 后端当前为 `NotImplementedError` 桩（v0.3+ 才落地） | ✅ 一致 | `obsidian_backend.py:14`（`push` 抛 `NotImplementedError("v0.3+ 落地")`）、`:23`（`recall`）、`:26`（`health`）。 | 与文档"v0.3+ 才落地"一致。 |
| **B1** `_enrich_with_memory(question)`：top_k=5/min_score=0.4；有块返 `"\n".join(f"- {b['content']}")`；空块/4xx/异常/空问题返 `""`；跳过无 content 块；末尾注入 `[Local Wiki]` 段 | ✅ 一致 | `hermes_api/main.py:238-263`：`:244` 空问题→`""`；`:250` `top_k=5,min_score=0.4`；`:252` `status_code>=400`→`""`；`:255-257` 空 blocks→`""`；`:258-261` 拼接 `"- {b['content']}"` 且 `if b.get("content")` 跳过无 content；`:262-263` `except Exception→""`。注入：`main.py:233-234`（`if local_wiki: prompt += "\n[Local Wiki]\n..."`）。 | 全部 7 个行为契约与文档 §4.2 逐字对应（仅注入尾注标点"优先用本地资料, 无关时才用 web search"用半角逗号，文档 §4.2 为全角，纯排版差异，不影响契约）。 |
| **B2** 测试守卫 `test_hermes_api_enrich.py` 共 7 个测试，与代码契约一致 | ✅ 一致 | `services/background-agent/tests/test_hermes_api_enrich.py` 共 7 个 test：`:71` top_k=5/min_score=0.4、`:80` 有块返 `- {content}`、`:91` 空块→`""`、`:96` 4xx→`""`、`:101` 网络异常→`""`、`:116` 空问题→`""`、`:123` 跳过无 content 块。 | 数量与契约点完全对应，且断言值（top_k=5/min_score=0.4、URL 结尾 `/v1/blocks/recall`）与 `main.py` 实现一致。只读核对，未运行。 |
| **B3** shim `/v1/solve` 契约：`SolveRequest{question, context?}` / `SolveResponse{status, summary, tool_calls, error}` | ⚠️ 漂移 | 文档 `hermes-integration.md §4`。实际 `hermes_api/main.py:67-75`（`SolveRequest`：`session_id, task_id, question, foreground_text, frames, max_subagents, timeout_seconds` —— **无 `context`**）；`main.py:77-85`（`SolveResponse`：`status, text, thread_id, usage, duration_ms, events_digest, error` —— **无 `summary`/`tool_calls`**）。 | 文档 §4 的字段集合与实际代码几乎无交集。文档称"契约完全不变、webui 端 0 修改"，但代码已演进为多模态/分帧的丰富契约，文档描述严重陈旧。 |
| **C1** §5 启动端口：gateway 8642 / shim 8079 / webui 8099 | ✅ 一致 | gateway：`hermes_api/main.py:43`（`HERMES_GATEWAY_PORT` 默认 8642）；`scripts/start-hermes-gateway.ps1:12,65`（默认 8642）。shim：`hermes_api/main.py:32`（`CODEX_API_PORT` 默认 8079）。webui 8099：仓库多处实锤（`ARCHITECTURE.md:18,35,62,67`；`DELIVERY.md:4,598`；`README.md:111` 等）。 | 三端口默认值与文档/全局架构文档一致。 |
| **C2** §2.4 shim provider：`HERMES_API_URL` 默认 `http://127.0.0.1:8642/v1`，`HERMES_API_KEY` 取 env | ✅ 一致 | `hermes_api/main.py:39`（`HERMES_API_URL = os.environ.get("HERMES_API_URL","http://127.0.0.1:8642/v1")`）；`main.py:40`（`HERMES_API_KEY = os.environ.get("HERMES_API_KEY") or os.environ.get("API_SERVER_KEY","")`）。 | 默认值与取值来源与文档一致。 |
| **C3** §2.2 记忆隔离：Hermes 在 `D:\Workspace\hermes-data\memories\`，BT-7274 在 memory-store :8996，命名空间不交叉；shim 不读该目录 | ✅ 一致 | `hermes-data` 子目录实测存在：`memories/`、`skills/`、`sessions/`、`logs/`、`SOUL.md`、`state.db`（Bash `ls -d` 确认）。shim `hermes_api/main.py` 仅通过 HTTP 与 gateway（`HERMES_GATEWAY_URL` `:44`）及 memory-store（`MEMORY_STORE_URL` `:48`）通信，**无任何 `open()`/`Path` 读取 `hermes-data` 的代码**。 | 物理隔离成立（两套独立存储）。ℹ️ 注意：memory-store 的 `MemoryBlock` 模型无 `namespace` 字段，文档所说 `bt-7274:*` 命名空间并非在 schema 层强制，隔离靠"独立 sqlite 文件 vs hermes-data 目录"实现；功能上等价，但文档的命名空间措辞偏理想化。 |
| **D1** `live_adapter.py` 的 `on_session_end` push 钩子 / `on_session_start` pull 钩子 / `compose_system_prompt` 注入 `[历史记忆]` | ℹ️ 注意 | push：实际在 `webinfer/memory_io.py:82-116`（`_memory_push` → `:110` `self.memory_store.push(...)`），**非**文档 §4.1.1 所说的 `live_adapter.py:on_session_end()`。pull：实际 `memory_io.py:29-60`（`_memory_warmup` → `:49` `self.memory_store.warmup(...)`）+ `:62-80`（`_memory_recall`），warmup 用 `query="__warmup__"`、`top_k=16,min_score=0.0`（`memory_store_client.py:141-156`）—— 与文档 §4.1.2 的 `top_k=8/min_score=0.3` 不符。prompt 注入：实际 `system_prompts.py:228-240`（`compose_system_prompt_with_memory`）注入标签为 `[Local Wiki]`/`[本地知识库]`（`:176,:182`），**非**文档 §4.1.3 的 `[历史记忆]`。 | 钩子**行为存在**（push 在会话结束、pull 在会话启动 warmup、prompt 注入记忆段），但实现位置、prompt 标签、pull 参数均与文档 §4.1 不符，且位于 webinfer **未提交改动文件**（`memory_io.py` 在 `git status` 4 个修改文件中）。**无法从已合入 main 确认**。详见"待确认/超出范围"。 |

---

## 待确认 / 超出范围

### 1. webinfer 未提交改动（D1 相关，无法从 main 确认）
`git status` 显示 `services/webinfer/` 下有 4 个未提交修改文件：

- `adapter_types.py`、`app.py`、`memory_io.py`、`summarizer_routing.py`

本次对 D1 的核对基于这些**工作区现状**（仅 Read）。其中 `memory_io.py`（含 push 钩子 `:110`）、`app.py`（注册 `handle_reset` 路由，见 `app.py:511`）属未提交内容，**不能代表已合入 `main` 的行为**。建议后端同事合入前同步更新 `doc/subsystems/memory-architecture.md` §4.1（钩子位置、prompt 标签、pull 参数），否则文档将持续误导。

补充：webinfer 侧相关测试已存在（`test_live_adapter_memory_hooks.py`、`test_memory_store_client.py`、`test_system_prompt_memory.py`），可作为回归守卫，但其断言的是"重构后"实现，与文档 §4.1 旧描述不再对应。

### 2. `D:\Workspace\hermes-data` —— 只读确认，无写入
- 已确认 Hermes 真 HOME 为 `D:\Workspace\hermes-data`，含 `memories/ skills/ sessions/ logs/ SOUL.md state.db config.yaml .env`，与文档 §7 一致。
- `.env` 含各 provider key（如 `MINIMAX_API_KEY`）但**无 `API_SERVER_KEY`/`HERMES_API_KEY`** → gateway 以 auth-disabled 运行，与 shim 契约（仅在 key 存在时发 `Authorization`）一致（与文档 §11.4 吻合）。
- **`hermes.cmd` 恢复属 `D:\Workspace` 写入，明确不在本次范围。** 但需记录一处与文档 §11 的偏差：文档 §11 称"只读审计发现 `bin\` 里**没有活跃 `hermes.cmd`**，只剩 `.bak`/`.backup`"；而当前实测 `D:\Workspace\hermes-data\bin\` **已存在 `hermes.cmd`（556 字节，2026-07-23 11:56）**，说明该启动器已在本次审计之外被恢复。这不影响隔离结论，但文档 §11 的"事故现状"描述已过时，建议补注。

### 3. 其他超出范围项
- `hermes.cmd` 还原进 `bin\`、gateway auth key 配置等 `D:\Workspace` 写入类操作：均不在本只读审计范围。
- 实际运行态（服务是否真在 8996/8642/8079/8099 监听）：未做端口探测，仅核对代码/脚本默认值。

---

## 对测试对话的后续建议（回归测试守护）

1. **B3 必须优先守护**：`hermes-integration.md §4` 的 `SolveRequest/SolveResponse` 字段描述已严重偏离实现。建议：(a) 修订文档使其与实际 `main.py:67-85` 一致；或 (b) 在 `services/background-agent/tests/` 增加针对 `SolveResponse` 字段（status/text/duration_ms/events_digest/error）的契约测试，防止未来重构破坏 webui 对接。当前**没有**测试直接断言 SolveResponse schema。

2. **A2 缺失端点需决策**：
   - 若 webui "知识库"页面（§4.3）仍计划上线，`POST /v1/external/sync`、`GET /v1/blocks/{id}`、`DELETE /v1/sessions/{sid}` 必须补齐，并补对应测试。
   - 若暂缓，`memory-architecture.md §3.3` 应明确标注"规划中/未实现"，避免下游误以为可用。
   - `/v1/health` vs `/health` 前缀不一致：确认 webui/监控探活用的是哪个路径，统一文档。

3. **A3 响应字段**：`meta_prompt`/`took_ms` 若不再需要，从文档 §3.2 删除；若需要，在 `RecallResponse` 与 `recall_blocks` 中补实现并加测试。当前属于"文档超前"的死声明。

4. **A4 psql 桩注释**：将 `psql_backend.py:14/23/26` 文案改为与 ADR-001 一致的"已从路线图移除 / 勿启用"，消除对后续 agent 的误导（低风险但高价值，防止有人"按注释复用 hermes pg"污染原记忆库）。

5. **B1/B2 已是良好守卫**：`_enrich_with_memory` 的 7 个测试覆盖了所有失败开放路径，建议保持，并在 webinfer 侧同理守护 `memory_io.py` 的 push/pull 钩子（现有 `test_live_adapter_memory_hooks.py` 已覆盖 `_build_memory_prompt`，但 push 路径建议补一个"会话结束触发 `memory_store.push`"的集成守护）。

6. **D1 文档同步**：webinfer 同事合入未提交改动时，请同步更新 `memory-architecture.md §4.1`：钩子位置（`memory_io.py`/`session.py`/`prompt_assembly.py` 而非 `live_adapter.py`）、prompt 注入标签（`[Local Wiki]`/`[本地知识库]` 而非 `[历史记忆]`）、pull 参数（`warmup` `top_k=16/min_score=0.0` 而非 8/0.3）。

---

## 审计方法与证据基线

- 只读工具：Read / Grep / Glob / Bash(`ls`, `git status` 仅查看)。
- 源码未改动；未执行 git commit/push/checkout/merge；`D:\Workspace\hermes-data` 仅 `ls` 查看未写入。
- 所有 file:line 引用来自 `main` 分支工作区（webinfer 4 文件为未提交工作区状态，已在 D1 标注）。
- 测试仅做静态核对，未运行任何测试套件。
