# memory-store v0.1

JoyAI 持久化记忆骨架（spec §`doc/specs/memory-store-skeleton-spec.md`）。当前 v0.1
**只**实现：

- `SqliteBackend`（FTS5 BM25，schema 完整 / score + last_hit_at + hit_count schema 留位运行时未维护）
- `POST /v1/blocks/push` / `POST /v1/blocks/recall` / `GET /health` / `GET /v1/backends`
- `PsqlBackend` / `ObsidianBackend` 占位（`NotImplementedError`）

v0.1 **不**改 `live_adapter.py`；钩子形状在 spec §D-9 锁定。

## 启动

```
cd services/memory-store
pip install -e .[dev]
memory-store            # 默认 :8996 + sqlite backend
# 或
MEMORY_PORT=8996 MEMORY_SQLITE_PATH=./data/memory.sqlite python -m memory_store.app
```

## 测试

```
cd services/memory-store
python -m pytest -q
```

## 端口

- 默认 `8996`，env `MEMORY_PORT` 覆盖
- 端口被占用 → `OSError: [Errno 98]` 退出非零（不抢、不重试）
