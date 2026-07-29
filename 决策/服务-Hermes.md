# 服务真值 — Hermes（记忆后端 :8642）

> 本文件记录 **Hermes（:8642 记忆/agent 网关）** 的已确定决策，覆盖 L2 `D-2026-07-23-048`。
> 所有事实由主理人亲自从 git 提交 + 代码（`services/background-agent/hermes_api`、`scripts/start-hermes-gateway.ps1`）核实（2026-07-28 召回轮，不起子代理）。

---

## D-2026-07-23-048  Hermes 记忆后端：home 固定 `D:\Workspace\hermes-data` + sqlite-only + 取消 psql 复用

- **事实**: Hermes 记忆采用 **sqlite-only**（本地 SQLite 持久化），**固定 home 目录** `D:\Workspace\hermes-data`（NOT `%LOCALAPPDATA%\hermes`、NOT `~/.hermes`、NOT 旧 stale 路径）。**取消之前的 psql/外部 DB 复用**，统一走 sqlite。启动脚本强制 pin `HERMES_HOME`，避免被其它 agent 改写污染。
- **来源**: ADR-001（2026-07-23）+ git `96aba52`（2026-07-23）
- **对话证据**: 会话记录/你是后端对话！…json（07-23 10:16-10:47）：「psql 优先是目标不是现状，线上 MEMORY_BACKEND=sqlite，sqlite 才是真后端」「保留现状用sqlite…gateway 定位 D:\Workspace\hermes-data\bin，key 从 hermes-data\.env 读」—— 与 D-048(07-23) 完全一致
- **校验**:
  1. `grep -n "HERMES_HOME\|hermes-data" services/background-agent/scripts/start-hermes-gateway.ps1` → :13/15/26/33/36 强制 `$env:HERMES_HOME = "D:\Workspace\hermes-data"`（注释说明曾有人把它指向 stale 路径导致 env 损坏，本脚本钉回 canonical）
  2. sqlite 后端存在：`grep -rn "sqlite_backend\|SqliteBackend" services/memory-store/` → `memory_store.backends.sqlite_backend`（Hermes 记忆与 memory-store 均用 sqlite 后端，但为独立库文件）
- **预期**: 启动脚本把 HERMES_HOME 钉到 `D:\Workspace\hermes-data`；记忆持久化为 sqlite（无 psql 依赖）
- **Drift**: 无（历史曾出现 HERMES_HOME 被改写指向 stale 路径，已在脚本层 pin 死，不再漂移）
- **Owner**: 后端 / 架构
- **锁定**: 🔒

---

## 关联索引

- 调用方 background-agent（:8079）+ Local Wiki recall 契约：见 `服务-background-agent.md`（D-049）
- 记忆/长期记忆业务：见 `业务-决策记忆.md`
- sqlite 后端技术同源：见 `服务-memory-store.md`（memory-store 亦 sqlite + USearch）
