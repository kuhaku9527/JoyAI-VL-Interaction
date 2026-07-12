# 记忆持久化骨架 — 调研记录

> 状态：A+C 调研已完成（Phase A 本地现码 + Phase C 外部资料）。Phase B（环境实情）按用户指令延后。
> 目的：在写 `spec` 与 `ADR` 前，把"现码做了什么 / 不做什么"摸清，把 embedding 服务化、sqlite-vec、召回语义、backend 耦合这四条线挖到底。
> 范围：仅覆盖 `doc/memory-architecture.md §6 P2-1` 的骨架阶段，不做 live_adapter 钩子（§6 P2-1.1 / 1.2）、bge-m3（§6 P2-3）、obsidian（§6 P2-2）。
> 后续动作：§5 列出的开放项交给 `doc/specs/memory-store-skeleton-spec.md` 与 `doc/adr/0005-memory-store-start.md` 决定。

---

## §1 背景与范围

### 1.1 触发

`doc/memory-architecture.md v3.1` 已写完，但 `services/memory-store/` 还没起。所有相关代码仍在 `services/webinfer/` 进程内的 `SessionState`（`live_adapter.py:586`）里——`mid_term_summaries`、`mid_term_history`、`long_term_history` 三层 dict 一停即丢。

按 v3.2 路线图（`00-main-direction.md §4`），#3 P2 记忆持久化要在 P0 走顺后再开排期；本调研是 P2 启动前的最后一道设计输入。

### 1.2 v0.1 范围（与骨架外明确边界）

| 在 v0.1 | 不在 v0.1（推迟到后续阶段）|
|---|---|
| `services/memory-store/` FastAPI 骨架（端口 8996）| live_adapter 钩子（`§6 P2-1.1 / 1.2`，v0.2）|
| `SqliteBackend`（FTS5 全文本）| bge-m3 FastAPI（`§6 P2-3`）|
| `MemoryBackend` Protocol + `PsqlBackend` / `ObsidianBackend` 占位| psql + pgvector 接入（要 Phase B 确认 hermes-agent pg 实例）|
| `POST /v1/blocks/push` / `POST /v1/blocks/recall` 路由| webui 知识库页（`§4.3`，v0.3+）|

---

## §2 现状 Fact-Finding（Phase A）

### 2.1 `services/webinfer/live_adapter.py`（118KB，简述结构）

关键位置（line 编号均来自 7/12 当前文件）：

- `SessionState`：`live_adapter.py:586` 起，字段含 `mid_term_summaries: list[dict]`, `mid_term_history: list[dict]`, `long_term_history: list[dict]`, `long_term_compression_next_index`, `memory_state: {"long_term_memory": str, "qa_history": list}`
- 中期摘要生成触发点：`live_adapter.py:2059` ——`if len(state.mid_term_summaries) >= self.config.compress_every_n_chunks: await asyncio.to_thread(self._compress_mid_terms, state)`（默认 `compress_every_n_chunks=5`，env `COMPRESS_EVERY_N_CHUNKS`）
- Session 生命周期：`live_adapter.py:823` `_session_cleanup_loop()` —— **这是 push 钩子的最佳接入点**（不需要新加事件）
- 配置：`live_adapter.py:519` `AdapterConfig`，含 `long_term_memory_window=40` 等

关键事实：
- **完全没有 embedding / vector / recall 现成调用**（grep `embedding|httpx|recall` 仅 `embedding` 这一字面词一次、无人真调）
- `live_adapter` 跑在 aiohttp + llama-server OpenAI 客户端，**没有外部 httpx 调用**

### 2.2 `services/webinfer/memory_summarizer.py`（41KB）

- `SummarizerModel`：`memory_summarizer.py:286` 起，OpenAI 客户端打 llama-server（默认 `api_base=http://localhost:8065/v1`）
- 多模态（图片 base64）做 mid_term，纯文本走 long_term
- 完全本地：导入仅 stdlib + `openai` + `PIL` + `transformers`（tokenizer），**无 httpx、无 embedding、无 vector**

### 2.3 `services/webinfer/system_prompts.py`（5.9KB 全读）

- 角色 prompt 通过 `<character_profile>` 块注入到 base system prompt（`compose_system_prompt(base, character_prompts, language)`）
- 文件扫描 `prompts/*.txt|.md`，环境变量 `CHARACTER_PROMPT_PATH`
- **完全没有 `[Local Wiki]` 或 memory 注入位**——这是必须新加的钩子，给 `live_adapter` 一个 recall 文本插入点（v0.2 任务）

### 2.4 `services/common/`（基本空架）

- 只有 `log_with_timestamp.py`（1.7KB），提供 `setup_timestamped_logger(name, log_dir, level)`
- **没有 http / db client 基础设施**——memory-store 要么自己包装 httpx，要么新加 `services/common/`

### 2.5 `services/background-agent/hermes_api/main.py`（全读 440 行）

- FastAPI + httpx + pydantic，OpenAI-compat 转发到 hermes gateway `:8642`
- **与 psql 完全无关**——纯 HTTP 客户端
- **与 `memory-architecture.md §5.1` "复 hermes 的 psql" 的不一致**：spec 假设的"共享 psql"实际指 hermes-agent 自己的存储，不是这个 shim。需要 Phase B 验证 hermes-agent 用的 pg 实例连接方式

### 2.6 现码与 `MemoryBlock` spec 字段映射缺口

| spec §2.2 字段 | 现码对应 | v0.1 决策 |
|---|---|---|
| `block_id` | 无 | push 时服务端生成 uuid4 |
| `session_id` | `state.session_started_at` + 标识符 | 直接拿 |
| `content` | mid_term summary 文本（`state.mid_term_summaries[i]` dict 中文本字段，待 v0.2 精确定位）| 直接拿 |
| `score` | 无 | push 时默认 1.0；不在 v0.1 调整 |
| `created_at` | `session_started_at` | 直接拿 |
| `last_hit_at` | 无 | v0.1 **不维护**，留 schema 字段默认 NULL |
| `hit_count` | 无 | v0.1 **不维护**，留 schema 字段默认 0 |

**研究意义**：spec 假设的 `score / last_hit_at / hit_count` 三个字段全部要在 v0.1 schema 里预留，但运行时**不计算**——这是把"spec 完备性"和"实现敏捷"分开，避免 v0.1 还没数据就先实现 decay 算法。

---

## §3 候选方案 + 评估（Phase C）

### 3.1 sqlite-vec 当前状态

资料：
- [asg017/sqlite-vec releases](https://github.com/asg017/sqlite-vec/releases) — 最新 `v0.1.10-alpha.4` / 2026-05-18
- [Using sqlite-vec in Python](https://github.com/asg017/sqlite-vec/blob/main/site/using/python.md)

关键事实：
- **pre-v1**，作者明示 "expect breaking changes"
- v0.1.9 (2026-03-31) 是 stable 版；v0.1.10-alpha 系列加入 DiskANN + ivf 实验 ANN
- Python 包 `sqlite-vec` 可 pip 装；用 `sqlite_vec.load(connection)` 加载扩展
- 需要 SQLite ≥ 3.41；Python 3.12 默认满足
- **Windows loadable .tar.gz 可用**（x86_64 138KB），与本地 RTX 5060 Ti 部署路径直接兼容
- 8K GitHub stars，社区活跃但小

**评估**：
- ✅ 用于 v0.1 风险可控（10K-100K 块规模，不需要 ANN）
- ⚠️ 长期 lock-in 风险：v1 API 可能有 breaking changes，建议 schema 层抽象 `MemoryBackend` 把 sqlite-vec 隔在背后
- ❌ **不建议 v0.1 就上 sqlite-vec**——见 §3.3 与 §4，BM25-only 可能就已足够

### 3.2 bge-m3 服务化三选一

资料：[FlagOpen/FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding)、[TEI issue #710: bge-m3 vllm vs TEI](https://github.com/huggingface/text-embeddings-inference/issues/710)、[vLLM bge-m3 PR #14526](https://github.com/vllm-project/vllm/pull/14526)、[vLLM Embedding docs](https://docs.vllm.ai/en/latest/models/pooling_models/embed/)

| 选项 | 工作机制 | 优势 | 劣势 | 本项目适配 |
|---|---|---|---|---|
| **FlagEmbedding 原生** (`BGEM3FlagModel`) | 直接 `pip install FlagEmbedding`，进程内 `encode()` | 零额外服务，~80ms/Q（RTX 5060 Ti FP16），接口简单 | 单进程，并发受 GIL，密集召回会撞上限 | ✅ **v0.1-v0.2 推荐**（一个 service 进程搞定，避免新服务部署） |
| **TEI** (huggingface/text-embeddings-inference) | Rust 高性能 inference server | 优化到极致，async + batching | 新模型支持慢；Rust 二进制重 | ✅ **P2-3 生产路径**（独立 FastAPI :8997） |
| **vLLM** | GPU serving 框架 | 通过 `--hf-overrides '{"architectures": ["BgeM3EmbeddingModel"]}'` 支持 dense + sparse + colbert | GPU 显存重（与本机 llama.cpp server 抢 16GB），架构与 LLM 同进程有冲突 | ❌ 不推荐（显存冲突、维护复杂度） |

**结论**：v0.1-v0.2 用 FlagEmbedding 原生包进 memory-store 进程；P2-3 切到独立 TEI FastAPI :8997（同时把现有的 recall 路径迁过去）。

### 3.3 召回语义工业实践

资料：
- [Mem0 Memory Decay](https://mem0.ai/blog/memory-decay-for-long-running-agents-how-recency-aware-ranking-fixes-retrieval-staleness) — recency-aware re-rank，1.5×→0.3× spread
- [Mem0 retrieval pipeline](https://github.com/mem0ai/mem0/blob/HEAD/skills/mem0/references/architecture.md) — hybrid (vector + BM25 + entity graph)，top_k=20, threshold=0.1
- [agent-knowledge](https://github.com/yucx-go/agent-knowledge) — 纯 BM25 + 知识图谱 + RRF，**LongMemEval-S R@5 96.6% 零向量依赖**
- [Mnemosyne](https://github.com/lucasmailland/mnemosyne) — postgres full-text + dense + graph + 7-stage hybrid
- [Letta Memory](https://docs.letta.com/letta-code/memory/) — git-backed 文件化，**完全不走 vector store**

对本项目（会话级摘要召回，10K-100K 块规模）：
- Mem0 默认 hybrid 路径：top_k=8-20 / threshold=0.1-0.3，召回 100-150ms（+rerank 150-200ms）
- agent-knowledge 证明：**会话级摘要 BM25 召回已可做到 R@5 96.6%**——这正好对应 v0.1 用 FTS5 的可接受底线
- Mem0 Memory Decay：对 BT-7274 这种"近期对话 > 很久前"场景增益明显（~50% boost in fresh-related queries）——**v0.2 必加**
- Letta 的文件化方案：超出本项目范围（我们要保留 RAG，不只是 persona/facts）

**结论**：
- v0.1 用 sqlite FTS5 (BM25) 单路召回，足够覆盖短期会话记忆
- v0.2 加 recency decay（Mem0 style，简单实现即可，无需 ML）
- v0.3+ 才引入向量路径（hybrid）

### 3.4 embedding 与 backend 耦合模式

资料：[Oracle: From RAG to Memory](https://blogs.oracle.com/developers/from-rag-to-memory-systems-building-stateful-ai-architecture)、[Mnemosyne retrieval](https://github.com/lucasmailland/mnemosyne)、[Mem0 architecture](https://github.com/mem0ai/mem0/blob/HEAD/skills/mem0/references/architecture.md)

三种主流：

1. **独立 embedding 服务 + 后端接 vector**（Mem0 / Mnemosyne）：embedding 服务独立进程，backend 调
2. **backend 内置 embedding**（少量自研方案）：backend 自己 load FlagEmbedding，省掉一层网络
3. **纯文本 + BM25**（agent-knowledge / Letta files 部分）：完全无向量

**本项目选型**：v0.1 走路径 3（最简）；v0.2-v0.3 走路径 1 的简化版（FlagEmbedding 嵌入 backend 进程，对网络层是 0 改动）。

---

## §4 推荐方案（v0.1 骨架）

### 4.1 架构原则 + 后端实现策略

**对外 web 表面只有 `services/webui/`（端口 8099 HTTPS，aiohttp + aiortc + `static/`）承担**。
`memory-store` 不渲染 HTML、不挂 JS、不暴露 `static/`；它**只暴露 JSON API**（:8996），
供 webui / live_adapter / 后台 agent 通过 HTTP 调用。
`memory-architecture.md §4.3` 描述的"知识库页面"挂在 webui 的 `static/` 里（约 30 行 Python + 1 个新静态页），
属于 v0.3+ 任务，不在 v0.1。

`memory-store` 内部按 `MemoryBackend` Protocol 抽象出三种实现：

| Backend | v0.1 行为 | 是否落 schema |
|---|---|---|
| `SqliteBackend` | push: insert MemoryBlock + 同步 FTS5 虚表；recall: FTS5 BM25 排序 + score filter + 截 top-k | ✅ 落 schema + 实现 |
| `PsqlBackend` | raise `NotImplementedError("psql 复用 hermes-agent 待 Phase B")` | ❌ 仅 protocol 占位 |
| `ObsidianBackend` | raise `NotImplementedError("v0.3+ 落地")` | ❌ 仅 protocol 占位 |

理由：
- sqlite FTS5 在 `agent-knowledge` 已证明对会话级摘要召回率达 R@5 96.6% 零向量
- 在 `services/common/` 几乎为空、`hermes_api/main.py` 提供 FastAPI+httpx+pydantic 范式的前提下，`SqliteBackend` 是低风险起步
- 三个 backend 都要有 Protocol + 工厂方法 v0.1 写完 v0.2 不能再改接口形状

### 4.2 API 协议（与 spec §3 完全对齐）

```
POST /v1/blocks/push
  req:  {session_id, blocks: [{block_id?, content, score?, created_at?}]}
  resp: {pushed: int, session_id}

POST /v1/blocks/recall
  req:  {query, top_k?, min_score?, filter?: {created_after?, session_ids?}}
  resp: {blocks: [{block_id, content, score, created_at, last_hit_at, hit_count}]}

GET  /health
  resp: {status, backend, db_path?, psql_dsn?, obsidian_root?}

GET  /v1/backends
  resp: {active: str, available: [str, ...]}
```

差异点（与 spec §3 相比）：
- 增加 `/v1/backends` 管理端点（运维 + 测试都用得到）
- `recall` filter 增加 `session_ids`，方便按 session 局部召回（spec §4.1 webinfer 提的"[Local Wiki]"注入是按本会话 + 跨会话混合）
- `push` 的 `block_id` 服务端生成（client 不传 spec 也允许）——简化客户端

### 4.3 与下游 live_adapter / system_prompts 的接口形状（v0.2 不在 v0.1 落地）

按 `memory-architecture.md §2.1` 流程图 + §3.2"启动首轮 / 长对话定期"语义，
live_adapter 侧需要**三段钩子**（spec 必须先写清楚形状，v0.2 才不返工）：

**钩子 A — `_memory_warmup(state)`**（启动首轮 pull）

接 `SessionState.__init__` 之后、`first_question` 之前；按本 session + 时间窗口预拉 top-k，
缓存到 `state._memory_block_cache`，**不直接进** `state.short_term`（short_term deque[20] 自己滚），
也不进 mid_term / long_term（这两层仍走进程内 dict，per spec §2.3）。

**钩子 B — `_memory_push(state)`**（session 结束 push）

接 `_session_cleanup_loop`（`live_adapter.py:823`）；按 spec §4.1"kill webinfer → push 本 session 全部 mid_term 摘要"。

**钩子 C — `_memory_recall(state, question)`**（per-question，from cache）

每轮 `_build_prompt` 时调用，**不再走 HTTP**，只走 session 内缓存；
cache 未命中 或 q 与缓存相似度过低时 才走 hot-fetch（长对话定期刷新，per spec §3.2）。

```python
# live_adapter 侧（live_adapter.py 中新加，不在 v0.1）
async def _memory_warmup(state: SessionState) -> None:
    """A：启动首轮 pull；缓存到 state._memory_block_cache。"""
    payload = {
        "query": "__warmup__",          # 服务端忽略 query，无 query 全召回
        "top_k": 16,
        "min_score": 0.3,
        "filter": {
            "session_ids": [state.session_id],
            "created_after": _seven_days_ago_iso(),
        },
    }
    resp = await http_post("http://localhost:8996/v1/blocks/recall", json=payload)
    state._memory_block_cache = resp["blocks"]   # list[MemoryBlock]

async def _memory_push(state: SessionState) -> None:
    """B：session 结束 push；接 _session_cleanup_loop。"""
    blocks = [
        {"content": s["content"], "score": s.get("score", 1.0),
         "created_at": _iso(state.session_started_at)}
        for s in state.mid_term_summaries
    ]
    if not blocks:
        return
    await http_post("http://localhost:8996/v1/blocks/push",
                    json={"session_id": state.session_id, "blocks": blocks})

async def _memory_recall(state: SessionState, question: str) -> str:
    """C：per-question；命中 cache 返回；未命中再 hot-fetch 一次。"""
    if state._memory_block_cache:
        scored = _rerank_simple(state._memory_block_cache, question)
        blocks = [b for b in scored if b["score"] >= 0.3][:8]
        if blocks:
            return "\n".join(f"- {b['content']}" for b in blocks)
    # hot-fetch path：长对话定期刷新（spec §3.2）
    resp = await http_post("http://localhost:8996/v1/blocks/recall",
                           json={"query": question, "top_k": 8, "min_score": 0.3,
                                 "filter": {"session_ids": [state.session_id]}})
    blocks = resp.get("blocks", [])
    return "\n".join(f"- {b['content']}" for b in blocks) if blocks else ""
```

```python
# system_prompts 侧（接 [Local Wiki] 注入位，v0.2 不在 v0.1）
async def compose_system_prompt_with_memory(base, character_prompts, language,
                                            memory_context: str) -> str:
    base = compose_system_prompt(base, character_prompts, language)
    if not memory_context:
        return base
    return base + f"\n\n[Local Wiki]\n{memory_context}\n(优先用本地资料，无关时才用 web search)\n"
```

**接口形状 v0.1 不实现，但 spec 必须先写清楚**——避免 v0.2 活刚开始就要回头改 protocol。

### 4.4 文件骨架

```
services/memory-store/
  pyproject.toml                       # Python 3.11+ 项目元数据，独立可装
  src/memory_store/
    __init__.py                        # 版本号
    app.py                             # FastAPI app + 路由注册
    models.py                          # MemoryBlock + Request/Response Pydantic
    backends/
      __init__.py                      # MemoryBackend Protocol + get_backend()
      sqlite.py                        # SqliteBackend 落地
      psql.py                          # PsqlBackend 占位
      obsidian.py                      # ObsidianBackend 占位
    errors.py                          # 错误类型 + FastAPI handler
  tests/
    __init__.py
    test_sqlite_backend.py             # push/recall roundtrip + score filter + session_ids
    test_protocol.py                   # MemoryBackend Protocol 契约
    test_app.py                        # /health /push /recall /backends endpoint
    test_port_conflict.py              # 起两个实例验证端口互不挤占
  README.md
  README.zh-CN.md
  scripts/
    run-windows.ps1                    # 标准启动脚本（对齐 webui/scripts 风格）
```

### 4.5 测试基线

`webinfer/` 与 `background-agent/` 当前都**没有 `tests/` 目录**——memory-store 是这两个之外第一个有 pytest 套件的服务。建议基线：

- 4 个测试文件，约 12 个 test function
- 单元 + endpoint 测试为主，集成测试留 v0.2（P2-1.1 钩子接好后再补）
- pytest 跑通即覆盖 push / recall / backend 切换 / score filter / 端口冲突

### 4.6 端口与依赖

- 端口 8996（按 spec §2.1）
- HTTP 服务，复用 `services/common/log_with_timestamp.py` 做时间戳日志
- Python 依赖：`fastapi`、`uvicorn`、`pydantic`、`httpx`（与 `hermes_api/main.py` 完全一致）
- 存储：`sqlite3`（标准库；FTS5 是内置模块，Python 3.11+ 默认满足）

---

## §5 待 spec / ADR 拍板的开放项

| # | 项 | 推荐默认 | 拍板形式 | 阻挡 v0.1 落地？ |
|---|---|---|---|---|
| 1 | `SqliteBackend` 是否 v0.1 就带 sqlite-vec 双索引 | 只 FTS5（不加 vec）| spec | 否（推荐默认即可） |
| 2 | `recall` 是否支持 `session_ids` 过滤 | 支持，默认 `[当前 session]` | spec | 否 |
| 3 | push 时 `block_id` 由谁生成 | 服务端 uuid4 | spec | 否 |
| 4 | `score` 字段 v0.1 语义 | push 默认 1.0，不调整 | spec + ADR | 否 |
| 5 | `last_hit_at` / `hit_count` v0.1 维护与否 | 不维护，留 schema 默认值 | spec | 否 |
| 6 | 端口是否使用 8996（与 spec §2.1 一致） | 是 | spec（无争议） | 否 |
| 7 | 是否开 `tests/` 目录做 pytest 基线 | 是 | ADR（决定 webinfer / background-agent 是否同步补 tests/） | 否 |
| 8 | `services/common/` 是否新增 httpx/db 客户端工具 | v0.1 不加，只用 stdlib + httpx | ADR | 否 |

**推动顺序**：
1. 写 `doc/specs/memory-store-skeleton-spec.md`，把 §4 落地
2. 写 `doc/adr/0005-memory-store-start.md`，把 §5 中需要 ADR 的（#4 半数、#7、#8）落 ADR
3. 走 `to-spec → ADR → 目录骨架 → 红色测试` 的 TDD 节奏开第一张票

---

## §6 参考

### 6.1 项目内已读

- `doc/memory-architecture.md`（v3.1 全读）
- `doc/00-main-direction.md §4`（v3.2 路线图）
- `doc/hermes-integration.md`（头 120 行；其余 Phase C.4 不需要）
- `services/webinfer/live_adapter.py`（grep 结构 + line 586 SessionState + line 823 _session_cleanup_loop + line 2059 _compress_mid_terms）
- `services/webinfer/memory_summarizer.py`（grep 结构 + line 286 SummarizerModel + 280-630 行阅读）
- `services/webinfer/system_prompts.py`（全读 180 行）
- `services/background-agent/hermes_api/main.py`（全读 440 行）
- `services/common/log_with_timestamp.py`（全读 55 行）

### 6.2 外部资料

| 主题 | 链接 |
|---|---|
| sqlite-vec releases | https://github.com/asg017/sqlite-vec/releases |
| sqlite-vec Python | https://github.com/asg017/sqlite-vec/blob/main/site/using/python.md |
| FlagEmbedding | https://github.com/FlagOpen/FlagEmbedding |
| TEI vs vLLM for bge-m3 | https://github.com/huggingface/text-embeddings-inference/issues/710 |
| vLLM bge-m3 PR | https://github.com/vllm-project/vllm/pull/14526 |
| vLLM Embedding docs | https://docs.vllm.ai/en/latest/models/pooling_models/embed/ |
| Mem0 Memory Decay | https://mem0.ai/blog/memory-decay-for-long-running-agents-how-recency-aware-ranking-fixes-retrieval-staleness |
| Mem0 retrieval pipeline | https://github.com/mem0ai/mem0/blob/HEAD/skills/mem0/references/architecture.md |
| agent-knowledge | https://github.com/yucx-go/agent-knowledge（LongMemEval-S R@5 96.6% 零向量）|
| Mnemosyne | https://github.com/lucasmailland/mnemosyne（pgvector + 7-stage hybrid）|
| MemoriesDB arXiv | https://arxiv.org/html/2511.06179 |
| Oracle: From RAG to Memory | https://blogs.oracle.com/developers/from-rag-to-memory-systems-building-stateful-ai-architecture |