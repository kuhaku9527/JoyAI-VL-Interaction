# ADR 0013: webinfer memory-store 客户端韧性策略（v0.3）

- 状态: Accepted
- 日期: 2026-07-29
- 上下文: doc/specs/memory-client-resilience.md

## 决策

`MemoryStoreClient`（`services/webinfer/memory_store_client.py`）引入**客户端内置熔断器**；
`_memory_wiki_recall` 改为 **fire-and-forget**（`asyncio.create_task`）。两条都是
**客户端侧**韧性，不改 memory-store 服务端、不改调用协议。

具体阈值与机制锁死在 `MemoryStoreClient._CB_FAILURE_THRESHOLD = 3`、
`_CB_COOLDOWN_S = 30.0`。

## 不变 / 边界

- **memory-store 仍是 SPOF**（D-023 已锁定）：webui 不绕过 webinfer 直连 VLM；同样 webinfer
  也不绕过 memory-store 回退到内存缓存。**不回退是 ADR-0006 决策的延续**。
- **`_memory_warmup` 仍 inline await**：warmup 与 session 生命周期强相关（首帧就绪），
  不能放后台；这是 ADR-0005 / D-025 已锁的事件语义。
- **`_memory_push` 仍 inline await**：与 session 清理时序绑定，不能 fire-and-forget。
- **fail-open 行为保持**：memory-store 完全下线时 chat 仍 200 OK，仅缺 wiki 块。熔断器
  只是把"每次 5s 等待"压成"开路瞬间 1 条 warning + 之后 0 延迟返回 []"。
- **`aclose()` 接口零变更**：仅新增熔断器字段；调用方零感知。
- **`MemoryStoreClient` 公共方法签名零变更**：仅方法体内加 `if self._circuit_open(): return []`
  和 `_record_failure` / `_record_success` 调用。

## 后果

正面：
- memory-store 宕机时 chat 延迟从 ~5s 降到 <300ms（实测 2026-07-29 8 连测，详见 spec T-3）。
- 减少 webinfer → memory-store 之间的网络往返，节省 worker（每次熔断开路少 5s × N 调用
  的 HTTP 阻塞）。
- 失败状态可观测（开路瞬间 warning 日志），便于 ops 排错。

负面 / 取舍：
- 第一次 chat 可能缺 wiki 块（异步任务还没跑完）。这是可接受折衷——memory-store 慢本来就
  是少数派场景，且第 N+1 次 chat 自动恢复。
- 熔断器是**单客户端**作用域（每个 `MemoryStoreClient` 实例独立计数）。当前只有一个
  client per adapter 实例，所以无影响；未来如果多 client，需重新审视。
- 阈值 3 / 30s 是经验值，未做自适应。下次事故后如果需要可调。

## 替代方案（拒了）

- **A: 加重试 + 指数退避**。memory-store 宕机时重试只会拖更久；3 次重试 + 退避可能 10s+，
  不解决根问题。
- **B: 上游（memory-store）加缓存层**。改服务端超出本次"客户端韧性"范围；服务端缓存
  对所有调用方一视同仁，但与本次"chat 主路径不阻塞"的优化目标无直接关系。
- **C: 引入 `pybreaker` 库**。一个客户端加 50 行依赖不值；模块内 40 行就够。
- **D: half-open 状态机**。当前 `_circuit_open()` 用时间检测自动放行，效果一样、代码
  少一半。

## 引用

- 决策书：
  - `决策/服务-webinfer.md` D-2026-07-29-032（wiki recall fire-and-forget）
  - `决策/服务-webinfer.md` D-2026-07-29-033（memory-store 客户端熔断器 v0.3）
- Spec：`doc/specs/memory-client-resilience.md`
- 代码定位：
  - `services/webinfer/memory_store_client.py:99-139`（熔断器字段 + 辅助方法）
  - `services/webinfer/memory_store_client.py:197-216`（warmup 短路 + 记录）
  - `services/webinfer/memory_store_client.py:254-273`（recall 短路 + 记录）
  - `services/webinfer/memory_io.py:185-225`（`_schedule_wiki_recall`）
- 历史事故：
  - `决策/服务-VLM.md` D-022 Drift 列（2026-07-28 0 字节瞬态）
  - `决策/drift-历史.md` DRIFT-2 来源
- 配套 ADR：
  - ADR-0005（memory-store 骨架）
  - ADR-0006（LLM 网关单入口 — memory-store 不可达不回退的语义）
