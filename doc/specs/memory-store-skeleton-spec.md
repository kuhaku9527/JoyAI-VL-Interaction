# Memory-Store Skeleton Spec (v0.1)

> 状态：**设计完整**，待实施。配套调研文档 `doc/memory-store-research.md`（18KB）。
> 范围：仅 `doc/memory-architecture.md §6 P2-1` 骨架阶段，不做 live_adapter 钩子（§6 P2-1.1 / 1.2）、bge-m3（§6 P2-3）、obsidian（§6 P2-2）、psql + pgvector（Phase B 之后）。
> 配套 ADR：`doc/adr/0005-memory-store-start.md`。

## Problem Statement

`webinfer` 的 `SessionState`（`live_adapter.py:586`）把 `mid_term_summaries` / `long_term_history` 全放在进程内 dict：

- `mid_term_summaries` 满 `compress_every_n_chunks=5` 即 `summaries.clear()`
- `long_term_history` 超过 `long_term_memory_window=40` 即切片
- 服务一停，全失

现在没有持久化、没有 RAG、没有外部接口。唯一的"持久化"是 `LIVE_SAVE_OUTPUTS=true` 把响应写 `logs/sessions/<sid>.jsonl`——那是响应日志，**不是记忆**。

`doc/memory-architecture.md v3.1` 已经把架构写完，但 `services/memory-store/` 没起。本次骨架（v0.1）目的是把"会话结束 push + 启动首轮 pull"两端落到**可运行代码**，embedding / psql / obsidian 全部留 v0.2+。

## Solution

起 `services/memory-store/`，FastAPI 跑在 `:8996`。`SqliteBackend` 用 sqlite FTS5 BM25（`agent-knowledge` 项目 R@5 96.6% 零向量方案证明足够；sqlite-vec pre-v1 breaking-change 风险绕开）作为唯一可用 backend；`PsqlBackend` / `ObsidianBackend` 占位（raise NotImplementedError）。

v0.1 **不引入 embedding 服务**；**不渲染 HTML，不挂 `static/`**——按 `doc/memory-store-research.md §4.1` 的"对外 web 表面唯一由 webui 承担"原则。memory-store 只暴露 JSON API。

live_adapter 三段钩子形状（v0.1 **不实现**，spec 锁定）：`_memory_warmup`（接 `SessionState.__init__` 后的首轮 pull，缓存到 `state._memory_block_cache`）、`_memory_push`（接 `_session_cleanup_loop`，session 结束整批 push）、`_memory_recall`（per-question 走缓存，未命中或 q 与缓存相似度过低时 hot-fetch 长对话定期刷新）。

## User Stories

1. As a Pilot, when a session ends, mid_term 摘要必须被持久化；下次同 session / 全局启动首轮，我能召回上轮对话的关键事实，而不是只看到最近 20 轮短记。
2. As a Pilot, in 对话中我不需要每轮都重算召回；只有首轮 / 周期刷新才走 HTTP，平时走 session 内缓存（避免每轮 +50ms 网络）。
3. As a developer, `MemoryBackend` Protocol 必须能让后续 `PsqlBackend` 接入不破坏现有调用方；新增 backend 只需 `MEMORY_BACKEND=psql` env 切换。
4. As a developer, `POST /v1/blocks/{push,recall}` 字段形状必须先稳定，避免 v0.2 live_adapter 钩子活刚开始就要回头改 protocol。
5. As a deployer, 我能 `curl /health` 看到 backend 状态 / `curl /v1/backends` 看到当前激活的 backend 名，方便 ops 排错。

## Implementation Decisions

### D-1 服务骨架

- 路径：`services/memory-store/`，标准 Python 项目（pyproject.toml + src layout）
- 入口：`src/memory_store/app.py`，FastAPI + uvicorn
- 端口：`:8996`（按 `memory-architecture.md §2.1`）
- 进程模型：与 webinfer / hermes-api 平行，HTTP 长连接
- 日志：复用 `services/common/log_with_timestamp.py`

### D-2 路由

```
POST /v1/blocks/push    # 入库
POST /v1/blocks/recall  # 召回（top-k + score filter + session_ids filter）
GET  /health            # backend 状态
GET  /v1/backends       # 当前 backend 名 + available list
```

`/v1/backends` 是相对 `memory-architecture.md §3` 多加的运维端点，方便 test + ops。

### D-3 数据模型

```python
# src/memory_store/models.py
from datetime import datetime
from pydantic import BaseModel

class MemoryBlock(BaseModel):
    block_id: str                                # 服务端 uuid4 生成
    session_id: str
    content: str                                 # 摘要文本
    score: float = 1.0                           # v0.1 写入即默认 1.0；recall 时不重排
    created_at: datetime
    last_hit_at: datetime | None = None          # v0.1 不维护，schema 留位
    hit_count: int = 0                           # v0.1 不维护，schema 留位

class PushRequest(BaseModel):
    session_id: str
    blocks: list[MemoryBlock]

class PushResponse(BaseModel):
    pushed: int
    session_id: str

class RecallFilter(BaseModel):
    session_ids: list[str] | None = None
    created_after: datetime | None = None

class RecallRequest(BaseModel):
    query: str                                    # "__warmup__" 服务端忽略
    top_k: int = 8
    min_score: float = 0.3
    filter: RecallFilter | None = None

class RecallResponse(BaseModel):
    blocks: list[MemoryBlock]
```

### D-4 Backend Protocol

```python
# src/memory_store/backends/__init__.py
class MemoryBackend(Protocol):
    name: str
    async def push(self, session_id: str, blocks: list[MemoryBlock]) -> int: ...
    async def recall(self, query: str, top_k: int, min_score: float,
                     filter: RecallFilter | None) -> list[MemoryBlock]: ...
    async def health(self) -> dict: ...

def get_backend() -> MemoryBackend:
    name = os.getenv("MEMORY_BACKEND", "sqlite").lower()
    if name == "sqlite":
        return SqliteBackend(...)
    if name == "psql":
        return PsqlBackend()      # raise NotImplementedError("待 Phase B")
    if name == "obsidian":
        return ObsidianBackend()  # raise NotImplementedError("v0.3+")
    raise ValueError(f"unknown backend: {name}")
```

### D-5 `SqliteBackend`（v0.1 唯一落地）

- 存储路径：`data/memory.sqlite`（相对启动目录）；env `MEMORY_SQLITE_PATH` 覆盖
- Schema：
  ```sql
  CREATE TABLE memory_blocks (
    block_id    TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    content     TEXT NOT NULL,
    score       REAL NOT NULL DEFAULT 1.0,
    created_at  TEXT NOT NULL,
    last_hit_at TEXT,                                  -- v0.1 schema 留位，运行时 NULL
    hit_count   INTEGER NOT NULL DEFAULT 0             -- v0.1 schema 留位，运行时 0
  );
  CREATE INDEX memory_blocks_session_idx  ON memory_blocks(session_id);
  CREATE INDEX memory_blocks_created_idx  ON memory_blocks(created_at);
  CREATE VIRTUAL TABLE memory_blocks_fts USING fts5(
    content, block_id UNINDEXED, session_id UNINDEXED,
    content="memory_blocks", tokenize="porter unicode61"
  );
  -- 通过 INSERT / DELETE / UPDATE trigger 同步
  ```
- push：单事务 = `INSERT INTO memory_blocks` + `INSERT INTO memory_blocks_fts`；`block_id` 服务端 uuid4
- recall：
  - `query == "__warmup__"`：按 `filter` 排序（`created_at DESC`）截 `top_k`
  - 否则 FTS5 BM25 排序 → 取 `top_k * 1.5`（余量）→ `min_score` 过滤 → filter (`session_ids` / `created_after`) → 截 `top_k`
  - `score` 字段不参与 rerank（默认 1.0，recall 时也不调整）
- 健康：`health()` 返 `{ "ok": true, "path": "...", "blocks": <count> }`

### D-6 `PsqlBackend` / `ObsidianBackend`（占位）

```python
async def push(self, *args, **kwargs):
    raise NotImplementedError("待 Phase B：复用 hermes-agent pg 实例")
```

（`ObsidianBackend` raise `"v0.3+ 落地"`）

### D-7 测试基线

- 路径：`services/memory-store/tests/`
- 文件：
  - `test_sqlite_backend.py`：push/recall roundtrip、score filter、session_ids filter、`__warmup__` 语义、`MemoryBackend` Protocol 契约
  - `test_app.py`：5 个 endpoint contract test（health / push / recall / backends / 错误）
  - `test_port_conflict.py`：同进程不能同时启两个实例占用 8996
  - `conftest.py`：临时 `data/memory.sqlite`（`tmp_path` 隔离）
- pytest ≥ 8；与 `services/webui/tests/` 风格一致（直接 pytest，无需 conftest 配置）
- **测试基线是给 `webinfer` / `background-agent` 立样**——不强求他们 v0.1 同步补（ADR 0005 决策 C）

### D-8 配置文件

```toml
# pyproject.toml
[project]
name = "memory-store"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "pydantic>=2.5",
  "httpx>=0.27",
]

[project.scripts]
memory-store = "memory_store.app:main"
```

### D-9 live_adapter / system_prompts 钩子接口（v0.1 不实现；spec 锁定形状）

按 `doc/memory-store-research.md §4.3` 三段钩子：

- `_memory_warmup(state)`：首轮 pull → `state._memory_block_cache`
- `_memory_push(state)`：session 结束 push（接 `_session_cleanup_loop` `live_adapter.py:823`）
- `_memory_recall(state, question)`：per-question 走缓存，未命中 hot-fetch 长对话定期
- `compose_system_prompt_with_memory(base, prompts, lang, memory_context)`：接 `[Local Wiki]` 注入位

完整代码块见 `doc/memory-store-research.md §4.3`。

## Testing Decisions

- 静态 / 单元 / endpoint 三层覆盖
- 一律用临时 sqlite 文件（pytest `tmp_path`）
- backend swap 测试用 mock 注入而非环境变量（避免 env 干扰）
- 不引入 integration 测试（v0.2 live_adapter 接好后再加 roundtrip）

## Out of Scope

- live_adapter.py 实际改动（v0.2 P2-1.1 / 1.2）
- bge-m3 / FlagEmbedding / TEI（v0.3 P2-3）
- psql + pgvector 接入（Phase B 之后）
- obsidian sync（v0.3+ P2-2）
- webui 知识库 page（v0.3+ `memory-architecture.md §4.3`）
- `MemoryBlock.score` 字段运行时调整 / `last_hit_at` / `hit_count` 维护
- recency-aware re-rank（v0.2+ 后续 spec）
- embed 注入路径（backend 内 / backend 外）—— v0.1 完全不涉及

## Further Notes

- sqlite 文件位置 / 端口 8996 都可通过 `MEMORY_SQLITE_PATH` / `MEMORY_PORT` env 覆盖（默认与 spec 一致）
- Phase B 推进后顺序：`PsqlBackend` 接通 → 本地 sqlite 删除 → 再接 obsidian
- 中间 schema 变更：v0.1 直接覆盖 sqlite（无 migration）；Phase B 引入 alembic 再谈