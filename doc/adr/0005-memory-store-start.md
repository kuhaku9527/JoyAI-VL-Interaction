# ADR 0005 — Memory-Store v0.1 骨架的几个边界决策

- **状态**：Accepted
- **日期**：2026-07-12
- **作者**：Codex（基于调研 `doc/memory-store-research.md`）

## 背景

按 `doc/memory-architecture.md v3.1` 启动 `services/memory-store/`，落地 v0.1 骨架。
调研产物 `doc/memory-store-research.md`（18KB）已经把现码 + 外部资料摸清，spec 已经覆盖大块（`doc/specs/memory-store-skeleton-spec.md`）；但调研过程中冒出 4 个**默认会跨越 spec 落地**的边界决策，需要 ADR 锁定。

## 决策

### A. `MemoryBlock.score` / `last_hit_at` / `hit_count` v0.1 schema 留位，运行时**不计算**

- **依据**：调研 `live_adapter.py` 完全本地，**没有任何** `score` / `last_hit_at` / `hit_count` 现成实现；spec 假设的字段实现要做额外工作（decay 算法、hit-tracking 异步任务、并发写）
- v0.1 schema 里三字段保留（schema 完整），但：
  - `score` push 时默认 1.0，recall 时**不重排**（只按 spec 的 `min_score` 过滤）
  - `last_hit_at` push 时 `NULL`，recall 时**不更新**
  - `hit_count` push 时 0，recall 时**不递增**
- recency decay（Mem0 Memory Decay 思路：1.5×→0.3× spread）加进来要在 v0.2+

### B. `services/common/` v0.1 不加 httpx / db 客户端工具

- **依据**：`services/common/` 当前只有 `log_with_timestamp.py`（1.7KB）；`httpx` / `pydantic` / `sqlite3` 都直接从 `memory-store` 依赖（与 `hermes_api/main.py` 风格对齐）
- 跨服务 helper 抽出需要在 2 个以上服务有相同需求时才有价值
- v0.1 只有 memory-store 一个服务用，没有复用必要
- v0.2 如果 webui / background-agent 也需要 memory-store 客户端能力，再考虑抽到 `services/common/`

### C. `services/webinfer/tests/` 与 `services/background-agent/tests/` v0.1 不补

- **依据**：调研发现这两个服务当前**没有** `tests/` 目录；memory-store v0.1 落地的 `tests/` 是仓库里**第三个**有 pytest 套件的服务（前两个是 `webui/` 和 `voice-clone/`）
- 主动补 cross-service tests 需要：
  - 同步调整 `services/scripts/run-windows.ps1` 测试编排
  - 与各服务 owner 协调 signoff（voice 那边还在 webinfer 里改 live_adapter.py）
  - 风险扩散到不在我范围内的服务
- v0.1 只给 memory-store 立 pytest 样板；后续 Phase 加"全仓 pytest CI" 时一次性补齐

### D. live_adapter 三段钩子（warmup / push / recall）

- **依据**：调研发现 `memory-architecture.md §2.1` 流程图明说"启动 → 空 dict → **首轮 query X** → pull"；spec §3.2 写"启动首轮 + 长对话定期"
- 早版本错误地把钩子写成了"每轮 recall"——这把 warmup / push / recall 三段混到一起，导致 v0.2 第一行代码就要回头改接口
- v0.1 接口形状（spec §D-9 锁定）：
  - `POST /v1/blocks/recall` 接收 `query="__warmup__"` 表示"无 query 全召回"（按 filter 截 top-k）
  - live_adapter 侧三段钩子（v0.1 不实现）：
    - `_memory_warmup(state)`：接 `SessionState.__init__` 后首轮 → 缓存到 `state._memory_block_cache`
    - `_memory_push(state)`：接 `_session_cleanup_loop`（`live_adapter.py:823`）→ 整批 push
    - `_memory_recall(state, question)`：per-question 走 cache；未命中或 q 相似度过低 → hot-fetch 长对话定期刷新

### E. 端口 8996 + `MEMORY_BACKEND` env 切换

- **依据**：`memory-architecture.md §2.1` 指定 8996（memory-store），与 webui 静态 HTTP / webinfer OpenAI-compat / hermes-api 风格平行
- 端口冲突自检：v0.1 启动时报 `OSError: [Errno 98] Address already in use` → 立即退出非零
- `MEMORY_BACKEND` env，默认 `sqlite`；`psql` / `obsidian` 触发 NotImplementedError 早退

## 不做的事

- ❌ v0.1 不引 embedding（spec §Out of Scope 详述）
- ❌ 不调整 webui / webinfer / background-agent 任何代码
- ❌ 不在 `services/common/` 加 helper（决策 B）
- ❌ 不主动给 webinfer / background-agent 加 tests（决策 C）
- ❌ 不实现 recency decay / score 运行时调整（决策 A）

## 测试

沿 `spec §D-7` 的 4 个测试文件 ~12 test functions：

- `test_sqlite_backend.py`：push/recall roundtrip、score filter、session_ids filter、`__warmup__` 语义、`MemoryBackend` Protocol 契约
- `test_app.py`：5 个 endpoint contract test（health / push / recall / backends / 错误）
- `test_port_conflict.py`：同进程不能同时启两个实例占用 8996

## 后果

- v0.1 落地阻力小：决策 A/B/C/D 把 spec 中需要协调的事项**锁死在 memory-store 服务内**
- v0.2 接 live_adapter 钩子时只需在 `live_adapter.py` 加三段方法名，protocol 已经稳定
- v0.3+ 加 bge-m3 / psql 时，`PsqlBackend` 占位的 NotImplementedError 是起点而非删改起点
- webinfer / background-agent 暂不补 tests 的决定可能 stale（owner 改完代码后再说）

## 参考

- `doc/memory-store-research.md` 全文（18KB 调研产物）
- `doc/memory-architecture.md` v3.1 全读
- `doc/specs/memory-store-skeleton-spec.md`（同次 commit）
- `doc/adr/0004-service-lifecycle.md`（格式参照）