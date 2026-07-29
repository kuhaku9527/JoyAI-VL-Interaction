# Handoff：上下文溢出根治（移植上游 PR #25）· 后端对话实装

> 来源方案：`reports/optimization-plan-context-architecture-20260723.md`（§2.1 / §2.2）
> 决策状态：**默认值已 owner 拍板锁定**（qa_history_window=12 / long_term_memory_max_tokens=1800），不再阻塞实现。
> 执行对话：**后端对话**（本交接文档读者）。回归：测试对话（见 §7）。
> 范围纪律：本对话（架构/测试）只产方案+回归，**不动业务码**；本文档即 handoff，后端对话读此路径取任务。

---

## 1. 目标（一句话）

把上游 `jd-opensource/JoyAI-VL-Interaction` PR #25 的"长会话上下文溢出"修复移植进本 fork 已拆分的 `live_adapter`，用两层边界化（工作记忆窗口 + 长期记忆 token 预算）根治 turn 100+ 必崩，并保留 `main_ctx_tokens` 作硬兜底。

## 2. 背景（已只读核验，非口头推断）

- 上游根因1：`qa_history` 无界 append，每轮全文塞进 system content → 溢出。
- 上游根因2：`long_term_memory` 只 append / 只按条数裁，不重压缩降阶 → 累计 token 爆窗。
- **本 fork 现状（核验）**：
  - `memory_io.py::_update_text_qa_history:146` 只 `append`，**无 window**（根因1 **存活**）。
  - `summarizer_routing.py:190-199` 有 count-window 裁剪 + 算 `token_count` 但**无 token 预算 while 循环**（根因2 **部分存活**）。
  - `prompt_building.py:165-179` 每轮把 `memory_state["qa_history"]` **全文注入 system content** → 正是上游根因路径。
  - 本 fork 自有 `main_ctx_tokens=16384` 字符预算（`prompt_building.py:72`）**只裁对话轮次，不裁 system content 的 qa_history 块** → 该路径未被保护。

## 3. 锁定默认值

| 字段 | 默认值 | 角色 |
|---|---|---|
| `qa_history_window` | **12** | 工作记忆：保留最近 12 轮问答（0=旧无界行为） |
| `long_term_memory_max_tokens` | **1800** | 工作记忆：重建 long_term_memory 的累计 token 预算（0=禁用） |
| `main_ctx_tokens` | 16384（不动） | 硬兜底 |

> 取舍：更保守，优先零溢出 + 更低每轮 prompt 成本；代价=单会话引用窗口更短；缓解=重要事实已外置 `memory-store`(8996) 召回。

## 4. 改动总览（4 个源文件，仅改非 `build/` 源码）

| # | 文件 | 改动 | 锚点 |
|---|---|---|---|
| 1 | `services/webinfer/adapter_types.py` | 新增 2 个 `AdapterConfig` 字段 | 紧邻 `keep_qa_history`（~L48）/ `long_term_memory_window`（~L72） |
| 2 | `services/webinfer/memory_io.py` | `_update_text_qa_history` 末尾加 window 裁切 | `qa_history.append(...)` 块之后（~L154） |
| 3 | `services/webinfer/summarizer_routing.py` | 补 token 预算 while 循环 | `window = int(self.config.long_term_memory_window...)` 块（L190-199） |
| 4 | `services/webinfer/app.py` | 新增 2 个 CLI arg + 在 `AdapterConfig(...)` 构造里传 2 字段 | `--no-qa-history`（~L114）/ `--long-term-memory-window`（~L242）/ 构造体（~L419,~L443） |

> ⚠️ **只改 `services/webinfer/` 下的源文件，改 `adapter_types.py`/`memory_io.py`/`summarizer_routing.py`/`app.py` 这 4 个；`services/webinfer/build/lib/` 下的同名文件是 build 产物/陈旧副本，勿动。**

## 5. 精确 diff

### 5.1 `adapter_types.py` — 两个新字段

**插入点 A**（紧邻 `keep_qa_history: bool = True` 之后，~L48）：
```python
    keep_qa_history: bool = True
    qa_history_window: int = 12   # 0 = 禁用(旧无界行为)；保留最近 N 轮问答
```

**插入点 B**（紧邻 `long_term_memory_window: int = 40` 之后，~L72）：
```python
    long_term_memory_window: int = 40
    long_term_memory_max_tokens: int = 1800   # 0 = 禁用；重建 long_term_memory 的累计 token 预算
```
> 注意区分：`long_term_max_tokens`（已存在=2000）是**单次生成上限**；新 `long_term_memory_max_tokens`（=1800）是**累计重建文本预算**，二者语义不同，别混。

### 5.2 `memory_io.py` — `_update_text_qa_history` 加窗口裁切

**before**（~L145-154，函数结尾）：
```python
        if existing is None:
            qa_history.append(
                {
                    "query_time": now_iso,
                    "query": last_user_text,
                    "responses": [{"prediction": clean_text, "decision": decision}],
                    "archived_in_chunk": None,
                    "text_path": True,
                }
            )
```
**after**（在 `if existing is None:` 块之后、方法返回前，加 8 空格缩进的窗口裁切）：
```python
        if existing is None:
            qa_history.append(
                {
                    "query_time": now_iso,
                    "query": last_user_text,
                    "responses": [{"prediction": clean_text, "decision": decision}],
                    "archived_in_chunk": None,
                    "text_path": True,
                }
            )

        # Bound qa_history the same way long_term_history is bounded (upstream PR #25
        # root cause 1): without this, every session eventually overflows the main
        # model context window regardless of max_model_len.
        window = int(self.config.qa_history_window or 0)
        if window > 0 and len(qa_history) > window:
            del qa_history[: len(qa_history) - window]
```

### 5.3 `summarizer_routing.py` — 补 token 预算 while 循环

**before**（L190-200）：
```python
        window = int(self.config.long_term_memory_window or 0)
        if window > 0 and len(state.long_term_history) > window:
            dropped_count = len(state.long_term_history) - window
            del state.long_term_history[:dropped_count]
            state.memory_state["long_term_memory"] = "\n\n".join(
                entry["compressed_text"].rstrip()
                for entry in state.long_term_history
                if entry.get("compressed_text")
            )
            token_count = self.summarizer.estimate_tokens(state.memory_state["long_term_memory"])
            long_term_entry["token_count_after_slide"] = token_count
```
**after**（补 token 预算循环；并把 `token_count` 计算移到块外，顺手修掉原 `long_term_memory_window=0` 时 `token_count` 未定义的潜在 NameError）：
```python
        window = int(self.config.long_term_memory_window or 0)
        token_budget = int(self.config.long_term_memory_max_tokens or 0)

        def _rebuild_long_term_memory() -> str:
            return "\n\n".join(
                entry["compressed_text"].rstrip()
                for entry in state.long_term_history
                if entry.get("compressed_text")
            )

        trimmed = False
        if window > 0 and len(state.long_term_history) > window:
            del state.long_term_history[: len(state.long_term_history) - window]
            trimmed = True
        if token_budget > 0:
            while (
                len(state.long_term_history) > 1
                and self.summarizer.estimate_tokens(_rebuild_long_term_memory()) > token_budget
            ):
                del state.long_term_history[0]
                trimmed = True
        if trimmed:
            state.memory_state["long_term_memory"] = _rebuild_long_term_memory()

        # Always recompute so token_count is defined for the LOGGER line below
        # (original only set it inside the window>0 branch → NameError when window=0).
        token_count = self.summarizer.estimate_tokens(state.memory_state["long_term_memory"])
        long_term_entry["token_count_after_slide"] = token_count
```
> `estimate_tokens` 精度：tokenizer 加载成功用真编码、失败退化 `len//4`（见 `memory_summarizer.py:455`）。token 预算是尽力而为；`main_ctx_tokens` 硬兜底兜住退化情形。

### 5.4 `app.py` — 两个新 CLI arg + 构造传参

**插入点 A**（紧邻 `--no-qa-history` 块之后，~L117）：
```python
    parser.add_argument(
        "--qa-history-window",
        type=int,
        default=_env_int("QA_HISTORY_WINDOW", 12),
        help="Max recent Q&A pairs kept in memory_state['qa_history'] (0 = unbounded/legacy).",
    )
```
**插入点 B**（紧邻 `--long-term-memory-window` 块之后，~L245）：
```python
    parser.add_argument(
        "--long-term-memory-max-tokens",
        type=int,
        default=_env_int("LONG_TERM_MEMORY_MAX_TOKENS", 1800),
        help="Cumulative token budget for rebuilt long_term_memory text (0 = disable).",
    )
```
**构造体传参**（在 `AdapterConfig(...)` 内）：
- 紧邻 `keep_qa_history=not args.no_qa_history,`（~L419）之后加：
  ```python
        qa_history_window=args.qa_history_window,
  ```
- 紧邻 `long_term_memory_window=args.long_term_memory_window,`（~L443）之后加：
  ```python
        long_term_memory_max_tokens=args.long_term_memory_max_tokens,
  ```

## 6. ⚠️ fork 专属映射（最重要，别改错地方）

上游 PR #25 把 window 加在 `archive_chunk_response_records`。**本 fork 已把 qa_history 的 append 拆到独立的 `_update_text_qa_history`**，而三处 `archive_chunk_response_records` 调用（`session.py:386` / `infer_loop.py:342` / `memory_io.py:164`）是 **chunk 输出落盘记录，与 qa_history 无关**。

→ **窗口逻辑必须落在 `_update_text_qa_history`（§5.2），不要动 `archive_chunk_response_records` 及其调用点。** 改错地方等于没修根因。

## 7. 验证计划（后端实装后 → 交测试对话回归）

- **单测**（扩展既有 `services/webinfer/tests/test_qa_history_archived_chunk_none.py` + `test_adapter_core_split.py`）：
  - 构造 `memory_state["qa_history"]` 长度 > `qa_history_window`，断言裁到窗口、且旧轮在头部被丢。
  - 构造 >1 batch 且累计 token 超 `long_term_memory_max_tokens` 的 `long_term_history`，断言 while 循环 drop 最旧 batch 至 ≤ 预算；并断言 `token_count` 在 `window=0` 时仍被定义（验证 §5.3 的 NameError 修复）。
- **集成**：模拟长会话（turn 200+、小 `main_ctx_tokens`），断言零 `context-length` 错误，且 `long_term_memory` token 数 plateau 在 ~1800（若单 batch 已 >1800，循环停在 1 batch，实际下限=单 batch 大小 → 真机复核项）。
- **本地命令**（建议，py3.12 venv）：
  ```
  python -m pytest services/webinfer/tests -o asyncio_mode=auto -q
  ```

## 8. CI 门禁（必看 landmine）

- 本仓库 `quality.yml` 的 `ruff` job **既跑 `ruff check` 也跑 `ruff format --check`**（services/webinfer 全目录）。**只跑 `ruff check` 绿 ≠ 门禁绿**。改任意 `.py` 后必须用 pinned ruff `0.15.22`（`D:/AI/ruffmig/bin/ruff.exe`）同时验：
  ```
  ruff check services/webinfer --extend-ignore <现有 ignore 集>
  ruff format --check services/webinfer
  ```
  否则 `format --check` 红照样挂 Quality Gate（前车之鉴：PR #11/#18）。
- **pytest 矩阵缺口（重要）**：当前 `quality.yml` pytest job matrix = `[memory-store, background-agent]`（PR #18 落地），**`webinfer` 尚未进矩阵**。本修复的回归测试若在 `services/webinfer/tests/`，默认不被 CI 跑。建议：要么本地充分验证，要么另开 PR 把 `webinfer` 加进 pytest 矩阵（推荐——否则此修复无 CI 守护）。如加矩阵，沿用既有写法 `matrix=[memory-store, background-agent, webinfer]`、`fail-fast=false`、显式 `pip install pytest pytest-asyncio` + `python -m pytest -o asyncio_mode=auto -q`。

## 9. 可逆性 / 回滚

- 两项均为配置门控：`qa_history_window=0` / `long_term_memory_max_tokens=0` 即回到旧行为（无界）。
- 出问题时 `export QA_HISTORY_WINDOW=0 LONG_TERM_MEMORY_MAX_TOKENS=0` 即可回退，无需回滚代码。
- 建议先在 `run-windows.env`（或对应启动 env）显式写死 12 / 1800，便于一键改。

## 10. 分工与交接

- **后端对话**：实装 §5 四处精确改动 → 本地 ruff check+format 双验 → 本地 pytest → 提 PR（建议标题 `fix(webinfer): bound qa_history + long_term_memory tokens (PR #25 port)`）。
- **测试对话**：接 §7 回归；复核 §8 的 CI landmine 与 pytest 矩阵缺口，确认门禁真正守护此修复。
- **本架构对话**：不碰码，仅产出方案+此 handoff；如需调整默认值回到方案文档，默认值已锁定不再阻塞。
- **不要抄**：上游 `livekit` 分支、整 Docker 化（见方案文档 §1 对照矩阵 #9/#10）。

## 11. 测试对话完成 ✅（2026-07-23）— §7 单测扩充

**交付**：新增 `services/webinfer/tests/test_context_overflow_bounds.py`（6 测试，commit `9f4521d`），覆盖 §7 两处边界：
- **qa_history 窗口**（调 `MemoryIOMixin._update_text_qa_history`，3 测）：窗口=3 时裁到 3 轮且头部最旧 3 轮被丢；window=0 退化为旧无界（6 条）；window>len 不动。
- **long_term_memory token 预算**（调 `SummarizerRoutingMixin._compress_mid_terms`，3 测）：token 预算=10 时 while 循环丢弃最旧 batch 至 ≤10（停在 len==1，保最新）；window=2 时按条数裁到 2；**`window=0` 时 `token_count_after_slide` 仍被定义**（直接钉死 §5.3 的 NameError 修复——未打补丁的代码此处必 NameError）。

**验证**：venv `D:\AI\envs\joyai-main\python.exe`（pytest 9.1.1 / pytest-asyncio 1.4.0 / py3.12，`-o asyncio_mode=auto`）→ 新 6 测全过；**整 `services/webinfer/tests` 99 passed（无回归）**。`ruff` 双验（pinned 0.15.22 + webinfer `--extend-ignore` 集 + `format --check`）全绿。测试用最小 mixin 替身（`_MemIO`/`_Router` + `_FakeSummarizer` 的 `estimate_tokens` 退化 `len//4`），不拉重 adapter 图，确定性高。

**分支**：新建 `test/webinfer-context-overflow`（基于实现分支 `fix/webinfer-context-overflow-bound`@`c5723ff`），已推 origin（`9f4521d`）。独立 worktree 操作，根树 `fix/webinfer-context-overflow-bound` 原封未动。

**⚠️ 副作用（需后端确认）**：实现分支 `fix/webinfer-context-overflow-bound` 尚为**本地分支、未推 origin**。测试分支基于它，故推送测试分支时把实现 commit `c5723ff` 也作为祖先推上了 origin。即实现代码目前经测试分支历史已可见于 origin。后端开 impl PR 时直接 push `fix/webinfer-context-overflow-bound` 即可（`c5723ff` 已在 origin，仅加 ref）；或把测试分支并入 impl PR 一起合。

**§8 landmine 复核**：本仓库 `quality.yml` 的 `pytest` 矩阵 = `[memory-store, background-agent]`（**webinfer 未进矩阵**），故这 6 测**当前不被 CI 跑**。要真让 CI 守护此修复，需另开 PR 把 `webinfer` 加进矩阵（§8 推荐写法 `matrix=[memory-store, background-agent, webinfer]`）。否则测试仅提供本地验证 + 未来矩阵扩展后的守护。

**下一步**：等后端推 impl PR（`fix/webinfer-context-overflow-bound`）；测试对话可应要求把 `test/webinfer-context-overflow` 并入该 PR 或单独开测试 PR。另建议把 webinfer 加进 pytest 矩阵以关门禁缺口。
