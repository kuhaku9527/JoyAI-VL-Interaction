# Review Handoff — PR #1 · Milestone 2 `adapter_core` Split

> **Audience**: review 组 / 测试组（WorkBuddy 其他对话）。本文件是后端对话交给你们的 handoff。
> **PR**: https://github.com/kuhaku9527/JoyAI-VL-Interaction/pull/1
> **Base**: `main` · **Head**: `milestone2-adapter-core-split`
> **Date**: 2026-07-21

---

## 1. TL;DR

里程碑 2：把 `services/webinfer/adapter_core.py`（1992 行）**机械**拆分为 5 个职责 Mixin + 一个薄 coordinator 门面（142 行）。**零行为变更**——纯结构解耦，运行时契约不变。

⚠️ 这个 PR 同时是**本地 `main` 累计改动首次同步到 GitHub**（GitHub 上此前完全没有 `services/webinfer/`）。所以 PR 里除了本次拆分，还带着里程碑 1（`live_adapter.py` 9 模块）、打包修复、memory-store 修复、前端 Block 1、安全加固。review 时**请聚焦本次拆分的 6 个文件**，其余作为背景。

## 2. 本次拆分的核心文件（重点 review）

| 文件 | 行数 | 职责 |
|------|------|------|
| `services/webinfer/adapter_core.py` | 142 | coordinator 薄门面：仅 `StreamingInferAdapter` 类定义 + `__init__` + re-export + `__all__` |
| `services/webinfer/session.py` | ~487 | `SessionMixin`（25 方法：会话/状态管理） |
| `services/webinfer/prompt_assembly.py` | ~302 | `PromptAssemblyMixin`（14 方法：prompt 拼装） |
| `services/webinfer/memory_io.py` | ~152 | `MemoryIOMixin`（5 方法：记忆读写） |
| `services/webinfer/summarizer_routing.py` | ~338 | `SummarizerRoutingMixin`（9 方法：摘要路由） |
| `services/webinfer/infer_loop.py` | ~740 | `InferLoopMixin`（12 方法 + 5 个 `_chat_payload_*` 子步骤） |
| `services/webinfer/tests/test_adapter_core_split.py` | — | 14 项契约测试（MRO / 71 方法 hasattr / 10 私有符号 / `__init__.__globals__`） |

**MRO 顺序**：`StreamingInferAdapter` → `SessionMixin` → `InferLoopMixin` → `SummarizerRoutingMixin` → `MemoryIOMixin` → `PromptAssemblyMixin`。

## 3. 外部契约（拆分不可破坏，请重点核对）

- `live_adapter.py` 门面 re-export 的 `StreamingInferAdapter` 类身份不变。
- 私有符号 `la._xxx`（如 `_apply_decision`、`_infer_once` 等 10 个）必须保持可访问。
- `StreamingInferAdapter.__init__.__globals__["AdapterConfig" / "SessionState"]` 仍可用（构造期注入）。
- console script `joyvl-webinfer-adapter = "live_adapter:main"` 不受影响。

## 4. 测试证据（后端对话已跑）

- webinfer 包：**66 原有测试 + 14 新增契约测试 = 80 passed**。
- ruff gate（F401/F811/F821/E402/I001/D100）= **0 错误**（注意：joyai-main venv 未预装 ruff，本地 lint 需走 CI 或装 ruff 的环境）。
- 设计文档：`doc/adr/0007-milestone2-design.md`（含 §2.1 方法→文件总表 66 方法、§5 T1–T7 任务、§7 import 纪律/私有符号 re-export、类图/时序图 mermaid）。

## 5. 请在 review 中确认

1. 6 个文件的方法归属是否合理（按职责簇，无跨簇耦合）。
2. 所有原 `adapter_core.py` 方法是否**无遗漏**迁移（设计声称 66 方法，契约测试已覆盖 hasattr）。
3. import 纪律：子模块只 `from .adapter_core import` 必要的类型；私有符号通过门面 re-export 保持可见。
4. `__init__` 超类调用顺序（MRO）与拆前一致，无 `super()` 断裂。
5. 是否引入了任何隐式行为差异（应完全为零）。

## 6. 已知 deferred / out-of-scope（不要在本 PR 阻塞）

- **CI workflow 改动**（`quality.yml` 的 package-smoke 门禁）**未进本分支**：部署令牌缺 `workflow` scope，无法推送改 workflow 的提交。将作为独立 PR 跟进。
- **P0 正确性修复**（独立于结构拆分，建议另开 PR）：
  - #2 决策解析链路统一
  - #3 常量收敛到 `prompt_constants`
  - #4 并发竞态（`_memory_block_cache` warmup 未持锁）
- 本地未提交的进行中前端改动（Block 2 `sanitize_static_html.js` 集群、drawer 微调）未纳入。

## 7. 本地复跑（如需自行验证）

```bash
# 默认 venv 是 D:\AI\envs\joyai-main\python.exe（非 services/.venv，后者是 3.13 且缺包）
cd services/webinfer
python -m pytest tests/test_adapter_core_split.py -q   # 14 契约测试
python -m pytest tests/ -q                              # 全量 80
```

## 8. 分支历史说明（供追溯）

为绕过 `workflow` scope 限制，分支历史已用 `git filter-branch` 摘掉 `6315215` 与 `96b5d56` 中对 `.github/workflows/quality.yml` 的改动（保留其余修复）。原始 tip 已备份在本地分支 `backup/pre-rewrite-m2-split`，如需对照。
