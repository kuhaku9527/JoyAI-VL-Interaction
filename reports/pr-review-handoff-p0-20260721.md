# P0 正确性修复 Handoff（review 组 / 测试组 / 前端对话）

> 主理人：齐活林（software-team-lead）｜日期：2026-07-21｜分支：`fix/adapter-p0-correctness`

## 0. TL;DR
P0 三项正确性修复（#2 决策解析统一 / #3 常量收敛 / #4 并发竞态）已完成并独立验证（86 passed，外部契约全绿）。代码落在干净的 `fix/adapter-p0-correctness`（基于里程碑2头 `a689329`，不含任何前端文件）。**P0 提交曾漏进 `milestone2-adapter-core-split`（前端分支），已由前端对话清理（见 §6.1）。** P0 已在隔离 worktree 重做并推送（见 §6.1 / §7）：`fix/adapter-p0-correctness` 远端头 `2d53508`，由后端/测试对话持有；PR #1 现干净（头 `082b916`）。

## 1. 交付物（P0 分支）
分支 `fix/adapter-p0-correctness`，5 个提交（cherry-pick 自原混乱态，已验证功能等价）：
- `84e8ed8` docs(webinfer): add P0 correctness-fix design (ADR 0008) for #2/#3/#4
- `36d271f` fix(webinfer): unify decision parsing via parse_model_decision (#2)
- `49b29cf` refactor(webinfer): consolidate 14 shared constants into prompt_constants (#3)
- `2520bf2` fix(webinfer): guard memory cache with state.lock to fix race (#4)
- `d4d0d7f` test(webinfer): add video-endpoint decision regression test for #2 (P1-b)

差异 vs `a689329`：18 文件，**全部在 `doc/adr/` 或 `services/webinfer/`**，零 `services/webui/`。

## 2. 验证结果（QA 严过关）
- 全量 `pytest services/webinfer/tests`：**86 passed, 0 failed**（基线 81 + #4 并发 1 + 视频端点 5）。
- 导入冒烟：`import live_adapter`、`StreamingInferAdapter`、私有符号 `la._compute_prompt_guard_max_chars/_estimate_messages_chars/_trim_messages_to_ctx`、`__init__.__globals__['AdapterConfig'/'SessionState']` 全部可达。
- #3 收敛：8 模块常量定义 grep 零命中；`pyproject.toml` `py-modules` 含 `prompt_constants`（→19）。
- #2 视频端点：现恒含 `streamingharness.decision∈{silence,response,delegation}` + `delegation_question`；文本端点既有断言通过；新增 5 条视频回归测试覆盖三种 token。
- #4 锁：双检 + IO 在锁外，无 asyncio.Lock 重入死锁；新增并发测试通过。
- 路由判定：**NoOne**（源码无 Bug；QA 自修 1 处自身测试断言）。
- ruff：本环境未装，由 CI `package-smoke` 门禁覆盖。

## 3. ⚠️ 里程碑2 分支污染（需前端对话处理，非后端职责）
P0 提交经共享工作树的分支操作漏进 `milestone2-adapter-core-split`，且前端在该污染分支上继续提交了 Block 4（`2c961f5`）。当前**本地** `milestone2-adapter-core-split` 链：
```
a689329 → 0bddc28(B2/3) → 1dd54f7(P0文档) → 5a3373d(#2) → 07bc4d1(#3) → 9cd725d(#4) → 2c961f5(B4)
```
这违反"P0 不与 PR #1 交叉"。**PR #1 远端头仍是 `a689329`（干净）**——污染仅限本地，远端 PR #1 未受污染。

### 前端对话清理配方（在 `milestone2-adapter-core-split` 上执行）
```bash
git checkout milestone2-adapter-core-split
git reset --hard 0bddc28            # 丢弃 P0 与 Block4，保留前端 B2/3
git cherry-pick 2c961f5            # Block4 重新叠到 B2/3 之上（仅改 services/webui，应无冲突）
# 结果：a689329 → 0bddc28 → 2c961f5'（干净里程碑2 + 前端，无 P0）
```
清理后推送 PR #1（milestone2→main）即只含里程碑2工作，P0 不串入。

## 4. P0 PR 计划（待凭据可用）
- base = `milestone2-adapter-core-split`（清理后），head = `fix/adapter-p0-correctness` → **stacked PR**，依赖 PR #1 先合。
- 阻塞：git 远程 `gh-proxy.com` 在本非交互 shell 无凭据，`git fetch` 失败，无法确认远端最新态，故尚未推送/建 PR。
- 前置条件：**先让前端对话执行 §3 清理并推送干净 milestone2**，否则 P0 推送/建 PR 时会把 P0 带进 PR #1。

## 5. 备份分支（可救回）
- `backup/milestone2-pre-cleanup`：污染前的 milestone2 混乱态。
- `backup/fix-p0-pre-cleanup`：脏 fix 分支（含前端 B2/3 祖先）。

## 6. 设计文档
- `doc/adr/0008-p0-adapter-fixes-design.md`（含 §5 T1-T4 任务、§7 共享约定、§9 风险）
- `doc/adr/0008-p0-adapter-fixes-sequence-diagram.mermaid` / `-class-diagram.mermaid`
- `doc/prd-2026-07-21-p0-adapter-fixes.md`（许清楚 P0 增量 PRD）

## 6.1 状态更正（2026-07-21 晚间，主理人补）

- **里程碑2 污染已清理**：本地 `milestone2-adapter-core-split` 现为 `a689329 → 0bddc28 → 082b916`（干净，仅 `services/webui/`，无 P0）；PR #1 远端头同步为 `082b916`。前端对话确认其 `index.html` WIP 原样保留、未触碰。
- **P0 已重做并推送**：在隔离 git worktree（`<workspace>/workspace/joyai-p0-fix`，与前端分支物理隔离）重做 #2 / #4，推送至 `fix/adapter-p0-correctness`，远端头 `2d53508`。全量 `pytest services/webinfer/tests` **93 passed**（86 基线 + 7 新增回归）。分支含 7 个提交（`a689329..2d53508`），仅改 `services/webinfer/` 与 `doc/adr/`，零 `services/webui/`。
- **§4「待凭据/未推送」已失效**：PR #2 已存在且由后端/测试对话持有，前端对话**勿**合并或修改该分支（约束见 §7）。
- 工作树现状：共享工作树停在 `fix/webui-live-refs`（前端分支）；后端分支独立成栈，互不影响。

## 7. 合并顺序与栈安全约束（给前端对话）

本仓库采用**栈式 PR**：PR #1（`milestone2-adapter-core-split`，前端核心拆分 + webui Block 2/3/4）与 PR #2（`fix/adapter-p0-correctness`，P0 正确性修复）共享同一祖先 `a689329`——二者是**兄弟**而非父子。但 PR #2 的改动目标是 milestone2 所拆出的 `services/webinfer/` 子模块（`response_format.py` / `memory_io.py` / `infer_loop.py` / `adapter_types.py` 等），其 diff **假设 milestone2 的模块结构已存在于 `main`**。因此合并顺序不可逆。

### 7.1 合并顺序（铁律）
1. **先合 PR #1**（`milestone2-adapter-core-split` → `main`）。头 `082b916`，仅含 `services/webui/` 与少量 `doc/`，零 `services/webinfer/`。
2. **后合 PR #2**（`fix/adapter-p0-correctness` → `main`）。头 `2d53508`，仅含 `services/webinfer/` 与 `doc/adr/`。
3. **禁止**在 PR #1 合入前先把 PR #2 合入 `main`——否则 PR #2 的 diff 会指向尚未拆出的旧单文件 `live_adapter.py` 结构，导致冲突或错误落地。

### 7.2 栈安全约束
- **勿 rebase / squash `fix/adapter-p0-correctness`**：保持祖先 `a689329` 不变。该分支已推送且由后端/测试对话持有；改写历史会破坏已开的 PR #2 与远端一致性，并让栈失去锚点。
- **PR #2 由后端对话主导**：前端对话只负责 PR #1；PR #2 的合并、修订、回滚决策归后端/测试对话，前端**勿**在 `fix/adapter-p0-correctness` 上提交或合并。
- **文件集天然隔离（栈可安全合并的前提）**：PR #1 仅碰 `services/webui/`，PR #2 仅碰 `services/webinfer/` + `doc/adr/`，无交叠 → 二者合入 `main` 时无文件冲突。
- **PR #1 合入后**：PR #2 在 GitHub 会显示「落后于 main 若干提交」，但因文件集不交叠，合入 `main` 仍为干净 merge，**无需为追平而 rebase**（再次强调：勿 rebase）。

### 7.3 回滚 / 救回
- 若 PR #2 需回退：直接 `git revert 2d53508`（或整段 `a689329..2d53508`），**不要** `git reset` 共享分支。
- 备份分支仍在：`backup/fix-p0-pre-cleanup`、`backup/milestone2-pre-cleanup`、`backup/pre-rewrite-m2-split`，可救回任意中间态。
- 远端 PR #2 头 `2d53508` 即最终真相；本地若与远端不一致，以 `git fetch origin fix/adapter-p0-correctness` 后的远端为准。
