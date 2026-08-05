# Spec: T-05 memory-store 健康端点可观测性

- 关联 ADR: 0015-memory-store-health-observability.md
- 状态: Implemented（PR #85 → `49304d2`，2026-08-05）
- 来源: Wayfinder 地图 T-05 块（wiki recall 静默失败可观测性，地图 89-92 行）

## 1. 背景与问题

memory-store 的健康端点（`GET /health`、`GET /v1/providers/health`）存在两个可观测性缺口，导致 FA-4 类问题静默：

1. **local embedder 假绿**：`Embedder.available()` 对 `local` provider 永远返回 `True`（unblocking default 契约），不校验 `EMBEDDING_LOCAL_MODEL` 权重是否真在盘。权重缺失/漂移时 `/health` 仍报 `embedding.configured: true`，召回失败却无信号。
2. **wiki sync 结果不回流**：`/v1/wiki/sync` 返回的 `SyncResponse`（embedded/errors/files/chunks/skipped）未被任何健康端点记录；fire-and-forget + circuit breaker 之下 wiki 召回失败不可见（E4 曾因"静默无向量"难以发现）。

## 2. 目标

- 健康端点暴露 local 模型的**真实可加载性**。
- 健康端点暴露**上次 wiki sync 的结果与时间戳**。
- 不破坏现有契约与测试（向后兼容的字段新增）。

## 3. 接口变更

### 3.1 新增方法
`services/memory-store/src/memory_store/embedder.py`：
```python
def model_present(self) -> bool:
    """local 时探测 EMBEDDING_LOCAL_MODEL 路径（文件 size>0 或非空目录）；
    非 local 直接 True。WARN-once 去重。"""
```

### 3.2 `GET /health` 响应变更
`embedding` 对象（provider == local 时）新增：
- `model_present: bool` —— 权重是否真在盘。
顶层新增：
- `wiki_sync: null | { embedded, errors, files, chunks, skipped, synced_at }` —— 上次 sync 结果；首次为 `null`。

### 3.3 `GET /v1/providers/health` 响应变更
`embedding` 对象（来自 `embedder.health()`，provider == local 时）新增：
- `model_present: bool`
顶层新增：
- `wiki_sync: null | {...}`（同 3.2）

### 3.4 `POST /v1/wiki/sync` 副作用
成功时将 `{**SyncResponse.model_dump(), "synced_at": <ISO8601 UTC>}` 存入 `app.state.last_wiki_sync`；异常路径不变（仍 500）。

## 4. 不变 / 兼容性

- `available()` 语义**不变**（local 仍 True）——保护 `test_local_available_always_true` 与 unblocking default 契约。真可加载性改由 `model_present()`/`health()` 暴露。
- 全部为**新增字段**，向后兼容；旧消费者忽略即可。
- `external_sync` 异常仍 `raise HTTPException(500)`。

## 5. 测试

- `test_embedder_provider.py::test_local_model_present_checks_path`：local 路径存在→True，不存在→False，siliconflow+key→True。
- `test_app.py::test_health_reports_embedding_model_present_and_wiki_sync`：`/health` 含 `wiki_sync`（初始 null）+ local `model_present`（bool）。
- `test_network_settings.py`：`/v1/providers/health` 键断言加入 `wiki_sync`（契约演进，合法）。

## 6. 验收

- 起服务后 `curl /v1/providers/health`：local 时 `embedding.model_present` 反映权重真实状态；`wiki_sync` 在 sync 后为非 null。
- 全量 pytest：71 passed / 8 skipped / 0 failed。
