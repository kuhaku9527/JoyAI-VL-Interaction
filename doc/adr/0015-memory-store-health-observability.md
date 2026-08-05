# ADR 0015: memory-store 健康端点暴露模型可加载性与 wiki sync 结果

- 状态: Accepted
- 日期: 2026-08-05
- 上下文: doc/specs/t05-memory-store-health-observability.md

## 决策

memory-store 的两个健康端点（`/health`、`/v1/providers/health`）新增字段，暴露此前静默的可观测性信号：

1. local embedder 的真实可加载性：新增 `Embedder.model_present()`（仅 `local` 做路径探测：文件 `size>0` 或非空目录；非 local 返回 `True`；WARN-once 去重），并在 health 响应的 `embedding` 对象以 `model_present` 字段暴露。
2. 上次 wiki sync 结果：在 `external_sync` 成功时将 `{**SyncResponse.model_dump(), "synced_at": <ISO8601 UTC>}` 存入 `app.state.last_wiki_sync`，health 响应顶层以 `wiki_sync` 字段暴露（首次为 `null`）。

## 不变 / 边界

- **`available()` 不动**。保持"配置级"语义（provider 选中 / API key 有即 True，local 永远 True）。理由：它是 unblocking default 契约，且 `test_local_available_always_true` 显式钉死；真校验职责移交给 `model_present()`/`health()`。
- **向后兼容**。全部为新增字段；旧消费者忽略即可。
- **`model_present()` 仅 local 探测路径**，非 local 直接 `True`，不触发任何 IO。
- **`external_sync` 异常路径不变**（仍 `raise HTTPException(500)`）；`last_wiki_sync` 只在成功分支写入。
- **`synced_at` 用 `datetime.now(timezone.utc)`**（reviewer 修掉的 `utcnow` 弃用）。

## 后果

正面：
- FA-4「local 永远 available 假绿」被封死——`/health` 一眼可见 `model_present: false`。
- wiki sync 失败 / 静默无向量不再不可见，`wiki_sync` 直接进 health。
- 与 #1/#2「不再静默指向空壳」同一条治理线（约法三章：不静默、不掩盖）。

负面 / 取舍：
- health 响应体变大（两个新字段）。
- `model_present()` 的 WARN 用模块级全局标记去重，跨实例仅告警一次（可接受）。
- `/health` 与 `/v1/providers/health` 对 `model_present` 缺失时的处理略不对称（一处 `None` 一处省略），低风险，follow-up 可统一。

## 替代方案（拒了）

- **A. 改 `available()` 直接真校验模型**。会破坏 unblocking default 契约与 `test_local_available_always_true`，且 `available()` 语义被改为"可加载"会牵动所有调用方。拒。
- **B. 只加 `model_present` 不暴露 `wiki_sync`**。不解决 wiki sync 静默失败（T-05 原问题的另一半）。拒。
- **C. 新增独立 `/wiki/health` 端点**。消费者需打两次；`wiki_sync` 本就是 health 的一部分，独立端点过度拆分。拒。
- **D. 在 `available()` 内 lazy-load 模型验证**。重量级（每次 health 都加载权重），且破坏"配置级"语义。拒。

## 引用

- PR #85 → `49304d2`（2026-08-05，squash 合入 main）
- Wayfinder 地图 T-05 块（`.workbuddy/tmp/wayfinder-map-health-audit.md` 89-92 行）
- FA-4 上下文：`决策/drift-历史.md`
- 同源时期 memory client 韧性：`0013-webinfer-memory-client-resilience.md`
- 关联 spec：`doc/specs/t05-memory-store-health-observability.md`
