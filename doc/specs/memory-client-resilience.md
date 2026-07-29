# Memory-Store Client Resilience Spec (v0.3)

> 状态：**已实现**（2026-07-29）。配套代码：`services/webinfer/memory_store_client.py`、`services/webinfer/memory_io.py`。
> 配套 ADR：`doc/adr/0013-webinfer-memory-client-resilience.md`。
> 配套决策：`决策/服务-webinfer.md` D-2026-07-29-032 / D-2026-07-29-033。

## Problem Statement

`webinfer` 的 `_memory_recall` / `_memory_wiki_recall` / `_memory_warmup` / `_memory_push` 全都
走 `MemoryStoreClient`（HTTP client，`:8996`/`8997`）。memory-store 慢或挂的时候，三个问题让
**chat 主路径被拖累**：

1. **`_memory_wiki_recall` inline await**（`memory_io.py:_memory_recall`，旧版）— 主 chat 路
   径串行等 wiki recall 完成。memory-store 不可达时每次 chat 加 ≤5s timeout（D-022 决策书
   `2026-07-28` 那次 0 字节超时的事故很可能就是这条链路）。
2. **无熔断器**（`memory_store_client.py`，旧版）— 每次失败都重新发起 HTTP 请求，每次都
   重新吃满 `timeout_s`（默认 5s）。memory-store 宕机期间每条 chat 浪费 5s+ 网络往返。
3. **httpx `AsyncClient` 长期持有**（`_get_client` lazy init + `aclose()` 无 shutdown 钩子）
   — 不是热路径问题，但长跑会泄漏连接。

wiki recall 是**富化**而非**阻塞**：当前问题用户没有 wiki 块仍能正常 chat，只是 wiki 召回
慢了点。第 N+1 次 chat 时缓存早就填好了。把"等富化"从主路径拿掉，是这次改的核心。

## Solution

两段独立修复，外加一条 invariant 约束：

### S-1 Wiki recall fire-and-forget

`_memory_recall` 不再 `await self._memory_wiki_recall(...)`；改为
`self._schedule_wiki_recall(state, question)`，内部 `asyncio.create_task` 异步执行。

- 主 chat 路径立即返回，不被 memory-store 拖累。
- 异步任务内仍走 fail-open try/except；任何异常只 `LOGGER.warning`、不抛给主路径。
- 任务在 `state._memory_wiki_tasks` set 里登记（如果存在），避免 `Task was destroyed but
  it is pending` warning；session 清理时可 `await` 等待。
- 第一次 chat 命中前可能没 wiki 块（任务还没跑完），后续 chat 都正常。
- 没有事件循环的单元测试里 `RuntimeError` 静默跳过。

### S-2 MemoryStoreClient 熔断器（v0.3）

新增两个模块级常量 + 两个状态字段 + 三个辅助方法：

```python
_CB_FAILURE_THRESHOLD = 3       # 连续失败次数阈值
_CB_COOLDOWN_S = 30.0           # 开路冷却时长
self._cb_failure_count: int = 0
self._cb_open_until_monotonic: float = 0.0

def _circuit_open(self) -> bool
def _record_failure(self) -> None
def _record_success(self) -> None
```

`recall` / `warmup` / `push` 三处方法在 `try` 之前都加 `if self._circuit_open(): return []`；
HTTP 异常或非 200 都调 `_record_failure`；200 响应后调 `_record_success`（重置计数 + 关路）。

开路后 30s 内所有调用直接返回 `[]`，不打网络、不占 worker、不写日志（首条 `LOGGER.warning
circuit OPEN` 在开路瞬间发）。30s 后下一次调用作为探测被放行：成功关路，失败继续开路。

阈值与冷却时长是模块级常量，要改阈值改这两个常量即可（不要散布在调用点）。

### Invariant（必须保持）

- **所有 memory hook 仍 fail-open**：熔断器和 fire-and-forget 都是性能优化，不是新依赖。
  memory-store 完全下线时 chat 仍要正常返回（仅缺 wiki 块）。
- **`_memory_warmup` 行为不变**：session 首帧的 warmup 仍 `await`（不能在后台跑，否则首
  问有可能命中"未暖机"分支——这是 ADR-0005 / D-025 已锁定的事件语义）。
- **`aclose()` 接口不变**：仅新增熔断器字段，方法签名零变更。
- **不破坏现有 httpx 连接复用**：`_get_client()` lazy init 路径保留；熔断器开路时不开新
  client（同一 client 复用即可）。

## User Stories

1. As a Pilot, memory-store 宕机时 chat 仍 <300ms 返回，不再 5s+ 等 recall timeout。
2. As a Pilot, 同一 session 第 N 次 chat 后 wiki 块已填充到 prompt，跟旧行为一致（虽然第一
   次可能没 wiki，这是可接受的折衷）。
3. As a developer, 当我读 `memory_store_client.py` 时，能直接看出熔断器是模块级行为；不
   用追多个调用点。
4. As a deployer, 我能通过 `LOGGER.warning("memory-store circuit OPEN for 30s after 3
   failures")` 一眼看出"memory-store 挂"的状态，无需 grep 所有 chat 路径。
5. As a CI maintainer, 现有测试不需要改（行为是"更宽松"，不是"更严格"），但需要新增两
   条单测覆盖熔断器 + fire-and-forget。

## Implementation Decisions

### I-1 模块位置

- 熔断器代码留在 `MemoryStoreClient` 类内（`memory_store_client.py`）。不开新模块、不开
  新依赖。
- `_schedule_wiki_recall` 加到 `MemoryIOMixin`（`memory_io.py`），与其它 mixin 方法风格
  一致。

### I-2 常量命名

`_CB_FAILURE_THRESHOLD` / `_CB_COOLDOWN_S` — 显式 `_CB_` 前缀，避免与可能的其它常量冲突。

### I-3 不做的事

- 不引入 `pybreaker` 等第三方熔断库（一个客户端用不上 50 行依赖）。
- 不做"半开路"状态机（half-open）；用 `_circuit_open()` 自动时间检测达到同样效果，
  代码少一半。
- 不做熔断状态对外可见 API（`is_circuit_open()`）；调试靠日志 + 健康端点足够。
- 不改 `MemoryStoreClient` 的 `recall/warmup/push` 方法签名。
- 不把 fire-and-forget 应用到 `_memory_warmup` 或 `_memory_push`——这两个时序与 session
  生命周期强相关（warmup 必须在首问前就绪；push 必须在 session 清理前完成）。

## Test Plan

### T-1 单元测试（`tests/test_memory_store_client.py`）

- `test_circuit_breaker_opens_after_threshold`：用 mock 让 `client.post` 连续抛
  `httpx.ConnectError` 3 次；第 4 次直接返回 `[]` 不发请求（验证 mock 调用次数）。
- `test_circuit_breaker_resets_on_success`：3 次失败 → 第 4 次 mock 返回 200 → 后续失
  败重新累计。
- `test_circuit_breaker_cooldown_expires`：mock 时间快进 31s；下一次 `recall()` 应重
  新发请求（探测）。

### T-2 集成测试（`tests/test_live_adapter_memory_hooks.py`）

- `test_wiki_recall_is_fire_and_forget`：用 stub `MemoryStoreClient` 让 `recall` 阻塞
  10s；`_memory_recall` 调用应在 <100ms 返回（不阻塞）。
- `test_wiki_recall_updates_cache_async`：stub recall 返回固定 blocks；触发 chat → 等
  100ms → 读 `state._memory_wiki_cache` 应非空。
- `test_wiki_recall_failure_does_not_propagate`：stub recall 抛异常；主 chat 路径不抛。

### T-3 端到端（人工验证，已做）

- 2026-07-29 实测：memory-store 关闭（`:8996` `:8997` 都没起）时，连发 8 条 chat，延
  迟从 846ms → 2078ms → 174/190/147/315/315/320ms。修复前预期每条 5s+。

## Cross-References

- 决策书：`决策/服务-webinfer.md` D-2026-07-29-032（fire-and-forget）+ D-2026-07-29-033
  （熔断器）。
- ADR：`doc/adr/0013-webinfer-memory-client-resilience.md`。
- 代码定位：`services/webinfer/memory_io.py:185-225`（`_schedule_wiki_recall`）、
  `services/webinfer/memory_store_client.py:99-139`（熔断器字段+方法）、`:197-216` /
  `:254-273`（warmup/recall 短路+记录）。
- 历史事故：`决策/drift-历史.md` DRIFT-2 来源（chat 5s timeout on memory-store down）；
  `决策/服务-VLM.md` D-022 Drift 列 0 字节瞬态事故。
- 测试待办：上述 T-1 / T-2 三条测试当前**未实现**，下轮 PR #44 一并补。
