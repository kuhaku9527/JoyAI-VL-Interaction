# 增量 PRD — Milestone 2 后 P0 正确性修复（adapter_core 拆分遗留）

- **文档类型**：增量 PRD（简单 PRD）
- **日期**：2026-07-21
- **作者**：许清楚（产品经理 / software-product-manager）
- **团队**：`software-adapter-p0-fixes`
- **关联基线**：
  - PR #1（adapter_core 拆分，已落地）：https://github.com/kuhaku9527/JoyAI-VL-Interaction/pull/1
  - 评审报告：`doc/review-20260720-live-adapter-split.md`
  - 设计基线：`doc/adr/0007-milestone2-design.md`、`doc/adr/0007-split-live-adapter.md`
- **项目**：JoyAI-VL-Interaction — `services/webinfer/`（消费级单卡 Windows 本地部署的 8B VLM 实时交互系统，开源小项目）

> 本 PRD 建立在「里程碑 2 adapter_core 拆分已完成」之上，是**增量**文档，**不重复描述拆分本身**。三项修复在评审中被标为 P0、且被刻意从结构拆分 PR 中剥离，需**独立成另一个 PR**。

---

## 1. 产品目标

在不破坏任何外部契约（`StreamingInferAdapter` 类身份、`la._xxx` 私有符号、`__init__.__globals__["AdapterConfig"/"SessionState"]`）的前提下，消除里程碑 2 拆分后遗留的三项正确性债务：决策解析分叉（#2）、prompt/常量重复（#3）、记忆块缓存 warmup 并发竞态（#4）。

---

## 2. 用户故事

- **US-#2（调用方 / 前端集成方视角）**：作为一名同时对接 `/v1/chat/completions`（视频流）与 `/v1/text/chat`（文本）的调用方，我希望两条路径对模型返回的 decision / delegation 给出**完全一致**的结构化字段，以便我的客户端无需为两条路径写两套解析分支、也不会因路径差异漏掉 delegation。
- **US-#3（维护者视角）**：作为一名项目维护者，我希望系统提示与共享常量集中在一处定义、由各模块 import，以便在修改文案/阈值时**只需改一处**，不再担心 8 份副本静默漂移导致行为分叉。
- **US-#4（维护者 / 运维视角）**：作为一名维护者，我希望记忆块缓存的 warmup 读写都受**同一把锁**保护，以便在多端并发触发同一会话的记忆预热时，不会出现缓存撕裂（torn read）或丢失更新（lost update）。

---

## 3. 需求池

### P0（Must have — 本次 PR 必须交付）

#### P0-#2 决策解析链路统一
- **目标**：将模型返回的「decision / 工具调用 / 动作」输出统一为**单一解析入口**，消除文本路径与视频路径两套分叉实现。
- **验收标准**：
  - 单一解析入口（建议落点 `response_format.py`，如 `parse_model_decision(raw_text) -> (decision, clean_text, delegation_question)`）同时被 `_handle_text_payload`（`infer_loop.py:189`）与 `_chat_payload_finalize`（`infer_loop.py:517-595`，视频路径）调用。
  - 视频路径结果须包含与文本路径一致的 `streamingharness.decision` 与 `delegation_question`（当前视频路径调用 `_chat_completion_response` 时**未传** `decision`/`delegation_question`，见 `infer_loop.py:589-595`，导致这两个字段缺失或为 `None`）。
  - `</delegation>` token 在两条路径行为一致（当前 `normalize_model_output` **不识别** `</delegation>`，仅 `_parse_decision_tokens` 识别，见 `response_format.py:80-102` vs `:113-151`）。
  - 现有 66 测试全绿；文本路径既有断言（`tests/test_text_chat_endpoint.py:207/232/252`）继续通过。

#### P0-#3 常量收敛到 `prompt_constants`
- **目标**：新建（或复用）共享 `prompt_constants.py`，让各模块从其 import 共享常量，删除各自副本。
- **验收标准**：
  - 新建 `services/webinfer/prompt_constants.py`，集中定义 `DEFAULT_SYSTEM_PROMPT`、`DEFAULT_SYSTEM_PROMPT_EN`、`DEFAULT_SAVE_ROOT`、`TIME_RANGE_RE`（当前在 8 个模块逐份复制，见 §7 调研佐证）。
  - 上述 8 个模块改为 `from prompt_constants import ...`，**删除**本地副本；不得引入循环导入（遵守 ADR 0007 §7.1 import 纪律：子模块不得反向 import `adapter_core`/`live_adapter`）。
  - 不破坏外部契约：确认无外部代码依赖 `from <module> import <这些常量>`（里程碑 2 已对 `adapter_core` 副本做过 grep 确认，无引用）。
  - 收敛范围确认：是否一并纳入评审报告列出的 `USER_QUERY_HEADER_*` / `VIDEO_HISTORY_HEADER_*` / `QA_*_LABEL_*` / `_CHARS_PER_TOKEN_BUDGET` / `_CTX_SAFETY_FACTOR` / `_PROMPT_GUARD_MIN_RECENT`（见 §6 待确认）。

#### P0-#4 并发竞态（`_memory_block_cache` warmup 未持锁）
- **目标**：让记忆块缓存 warmup 的读写都在同一把锁保护下进行，消除读-写/写-写竞态。
- **验收标准**：
  - `state._memory_block_cache` 与 `state._memory_warmed` 的全部写操作须在同一把锁（`state.lock`，`asyncio.Lock`，定义于 `adapter_types.py:159`）保护下进行。
  - 重点修复：`session.py:57-58` 启动的 fire-and-forget 后台 warmup 任务 → `memory_io._memory_warmup`（`memory_io.py:29-46`，写 `state._memory_block_cache = blocks` @45、`state._memory_warmed = True` @38）当前**未在锁内**；须使其在写缓存前获取 `state.lock`。
  - 同步核对 `infer_loop.py:151`（文本路径写缓存，已在 `state.lock` 内）与 `prompt_assembly.py:135` / `infer_loop.py:461-462`（读缓存，在请求锁内）以及 `memory_io._memory_recall`（`memory_io.py:57/62` 读）保持锁使用一致。
  - 不得改变 warmup 的 fail-soft 语义与「仅首次生效」语义（`_memory_warmed` guard）。

### P1（Should have — 与三项相关但可延后）

- **P1-a 收敛范围扩展**：若 §6 确认扩大收敛范围，则把评审报告列出的其余重复常量（`USER_QUERY_HEADER_*` 等）也并入 `prompt_constants.py`（影响更多文件，需额外 import 改造与回归）。
- **P1-b 决策解析回归测试**：为统一后的解析入口补充测试，覆盖**视频路径**（live adapter chunk 流转）在 `</response>` / `</silence>` / `</delegation>` 三种 token 下的 decision/silence/delegation 判定，确保与文本路径一致。当前 `tests/test_text_chat_endpoint.py` 仅覆盖文本路径，视频路径 decision 字段无断言保护。

### P2（Nice to have）

- **P2-a 移除残留 DEBUG 日志**：删除 `_handle_chat_payload` 内的 `DEBUG v0.2` 日志块（`infer_loop.py:456-466`，含单引号字符串，违反 `quote-style = double`；评审 nit #6）。
- **P2-b 工程化门禁**（弱相关）：落实评审 P2 项——CI wheel 构建 + import 冒烟门禁、lint-baseline「只降不升」。建议随独立工程化 PR 处理，不阻塞本 PR。
- **P2-c 解析器去重收尾**（可选）：`normalize_model_output` 与 `_parse_decision_tokens` 统一后，清理二者间「镜像」token 扫描的重复实现，保留其一为内部归一化助手。

---

## 4. 非目标 / 边界

- **不改外部契约**：`StreamingInferAdapter` 类身份、`la._xxx` 私有符号可达性、`__init__.__globals__["AdapterConfig"/"SessionState"]` 必须保持（ADR 0007 §7.2 / §9）。
- **不动里程碑 2 已落地的拆分结构**：5 个 mixin（session / prompt_assembly / memory_io / summarizer_routing / infer_loop）+ coordinator 薄门面（`adapter_core.py`）保持不变。
- **不引入新第三方依赖、不引入新功能/新行为**：仅修复正确性，输出语义等价（零行为变更）。
- **不改动打包 / `py-modules`**：已在 `96b5d56` 修复，与本 PR 无关。
- **不处理评审报告的 🔴 阻断项**（打包缺口）：已于本基线前独立修复。

---

## 5. UI 设计稿

**N/A** — 纯后端正确性修复，无界面。

---

## 6. 待确认问题

- **#2 统一入口签名与落点**：统一后的解析函数命名/签名（建议 `response_format.py`，返回 `(decision, clean_text, delegation_question)`）；视频路径 `finalize` 如何把 `decision` 写入 `streamingharness.decision`（目前 `_chat_completion_response` 仅在 `decision is not None` 时写该字段，见 `response_format.py:265-266`，需确认视频路径是否也应总是产出 decision，还是沿用「缺省即 None」）；`normalize_model_output` 是否保留为内部归一化助手。
- **#3 模块命名与导出方式**：新建模块是否命名 `prompt_constants.py`、是否加 `from __future__ import annotations`、是否需 re-export 进 `live_adapter.__all__`；**收敛范围**——是否纳入评审列出的其余常量（`USER_QUERY_HEADER_*` 等）；各模块改 import 后是否产生循环依赖（需静态核验，尤其 `adapter_types`/`config` 不反向 import 的既有约束）。
- **#4 用哪把锁 / 锁粒度**：warmup 后台任务用 `state.lock`（`asyncio.Lock`）是否足够，还是需要独立 `_memory_lock`；锁粒度是整段 `_memory_warmup` 加锁还是仅缓存赋值加锁；`_memory_recall` 的懒 warmup 路径（`memory_io.py:58-59`）是否也需纳入锁临界区。
- **验证范围**：66 测试全绿 + 契约验证脚本（ADR T7 清单）在本 PR 仍需跑；是否补充新的并发/一致性单测（见 P1-b）。

---

## 7. 调研佐证

> 下列文件/符号/行号均为**里程碑 2 拆分后**的真实当前位置（已用 Grep/Read 核实）。

### #2 决策解析分叉（已定位，确实存在）
- **文本路径**：`services/webinfer/infer_loop.py:189` `_handle_text_payload` 调用 `_parse_decision_tokens(raw_text or "")` 得到 `(decision, clean_text, delegation_question)`，并在 `:205-206` 传入 `_chat_completion_response(decision=..., delegation_question=...)`。
- **视频路径**：`services/webinfer/infer_loop.py:498-502` `_chat_payload_build_and_infer` 用 `normalize_model_output(raw_text)`（**非** `_parse_decision_tokens`）；`:521` `_chat_payload_finalize` 调 `extract_response_payload`；`:589-595` 调 `_chat_completion_response(...)` 时**未传** `decision`/`delegation_question` → 结果缺 `streamingharness.decision`。
- **两份解析器实现于** `services/webinfer/response_format.py`：
  - `normalize_model_output`（`:80-102`）：仅识别 `</response>` / `</silence>`，**不识别** `</delegation>`。
  - `_parse_decision_tokens`（`:113-151`）：识别 `</response>` / `</silence>` / `</delegation>` 三种 token。其 docstring 显式声明「mirroring `normalize_model_output` behaviour so both paths stay in lock-step」——即本应一致、当前未一致。
- **字段写入逻辑**：`response_format.py:265-266` `if decision is not None: harness["decision"] = decision`；`:269` `delegation_question` 恒写入（可为 `None`）。
- **既有测试仅覆盖文本路径**：`tests/test_text_chat_endpoint.py:207 / :232 / :252`。
- 与评审报告高优先 #2（「帧路径未走 `_parse_decision_tokens`、缺 `decision`/`delegation_question` 字段」）及 ADR 0007 §8 落点建议（「决策解析统一可落在 infer_loop + response_format」）一致。

### #3 常量重复（已定位，确实存在）
- **`prompt_constants.py` 当前不存在**：全仓 grep `prompt_constants` 仅命中 `doc/` 与 `reports/` 引用，无实际模块文件。
- 以下 **4 个常量在 8 个模块各自复制定义**（逐字相同，含 "You are a real-time video streaming assistant..." 系统提示文本）：

  | 模块 | 行号 |
  |------|------|
  | `config.py` | `:42` / `:43` / `:50` / `:62` |
  | `app.py` | `:58` / `:59` / `:66` / `:78` |
  | `prompt_building.py` | `:45` / `:46` / `:53` / `:65` |
  | `io_utils.py` | `:47` / `:48` / `:55` / `:67` |
  | `adapter_types.py` | `:47` / `:48` / `:55` / `:67` |
  | `request_parsing.py` | `:46` / `:47` / `:54` / `:66` |
  | `response_format.py` | `:47` / `:48` / `:55` / `:67` |
  | `time_ranges.py` | `:42` / `:43` / `:50` / `:62` |

  （常量：`DEFAULT_SAVE_ROOT`、`TIME_RANGE_RE`、`DEFAULT_SYSTEM_PROMPT_EN`、`DEFAULT_SYSTEM_PROMPT`）
- 里程碑 2 拆分时仅删除了 `adapter_core.py` 内部那份未使用的重复常量（ADR 0007 §2.2）；原评审报告计数 9 份 → 现 8 份。
- 评审报告另列重复集合：`USER_QUERY_HEADER_*` / `VIDEO_HISTORY_HEADER_*` / `QA_*_LABEL_*` / `_CHARS_PER_TOKEN_BUDGET` / `_CTX_SAFETY_FACTOR` / `_PROMPT_GUARD_MIN_RECENT`（本次调研确认 `USER_QUERY_HEADER_*` 等亦跨多模块重复，但**精确成员与是否全量纳入收敛范围待 §6 确认**）。

### #4 并发竞态（已定位，确实存在）
- **锁定义**：`services/webinfer/adapter_types.py:159` `lock: asyncio.Lock = field(default_factory=asyncio.Lock)`。
- **缓存字段**：`adapter_types.py:192` `_memory_block_cache: list = field(default_factory=list)`；`:193` `_memory_warmed: bool`；`:195` `_memory_warmup_task: Optional[asyncio.Task]`。
- **未持锁写（竞态源）**：`session.py:57-58` `get_session` 内 `state._memory_warmup_task = asyncio.ensure_future(self._memory_warmup(state))` 启动后台任务，**未获取 `state.lock`**；该任务 → `memory_io.py:29-46` `_memory_warmup` 在 `:38` 写 `state._memory_warmed = True`、`:45` 写 `state._memory_block_cache = blocks`，**均无锁**。
- **持锁读/写（请求路径）**：
  - `infer_loop.py:117` `handle_text_chat` 内 `async with state.lock:` 包裹 `_handle_text_payload`，其 `:151` 写 `state._memory_block_cache = list(blocks)`（有锁）。
  - `infer_loop.py:219` `handle_chat_completions` 内 `async with state.lock:` 包裹 `_handle_chat_payload`，其 `:461-462` 读 `_memory_block_cache`（有锁）。
  - `prompt_assembly.py:135` `_build_memory_prompt` 读 `list(getattr(session_state, "_memory_block_cache", None) or [])`（在请求锁内）。
  - `memory_io.py:57 / :62` `_memory_recall` 读，且 `:58-59` 可能触发**未持锁**的懒 warmup 写。
- **结论**：后台 warmup 写路径（无锁）与请求路径读写（有锁）**锁使用不一致** → `_memory_block_cache` / `_memory_warmed` 存在读-写/写-写竞态（torn read / lost update）。与评审报告高优先 #4（「memory warmup 写 `_memory_block_cache` 未持锁」）及 ADR 0007 §8 落点建议（「并发竞态修复集中在 `memory_io._memory_warmup` 与 `session.get_session` 的锁临界区」）一致。
