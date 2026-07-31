# ADR 0014: 日志事件 schema（JSONL per-service 文件）

- 状态: Accepted
- 日期: 2026-08-01
- 上下文: doc/specs/log-event-schema.md

## 决策

所有运行时事件（webui 请求、webinfer 路由、memory-store 读写、launcher 启停、drift_gate 校验、circuit breaker 状态变化等）必须用 **JSONL 事件流** 落到 `logs/events/<service>-<UTC-YYYY-MM-DD>.jsonl`，schema 见 spec。配套工具 `scripts/log_query.py` 做 `service / time / event-name` 过滤。

四件必填字段：`ts` (ISO 8601 UTC) / `level` ∈ {debug,info,warn,error,critical} / `service` / `event` (kebab-case)。可选字段：`session_id` / `latency_ms` / `status` / `user` / `extra` (object)。**PII 红线**写在 spec S-1：不记 message body / API key / 文件内容 / IP。

## 不变 / 边界

- **Q1 的 4 个文件继续存在**：本 ADR 不废除 `logs/drift-gate-history/` / `logs/launcher-*.log` / `logs/vlm-probes/` / `logs/webui-access-*.log`。它们从"主"日志降级为"历史/取证"日志——`grep` 仍可用，**真值走 JSONL**。
- **不内置索引**。query 工具按文件名 + 流式 grep，drift_gate 的 history 文件已经覆盖了"已知问题"类查询。无 sqlite / Elasticsearch / 时序数据库。
- **不做 alert / dashboard**。drift_gate 的 block severity 已经起 alert 作用；operator 排查用 `tail` + `jq` + `log_query.py` 就够。
- **现有 launcher 落 `logs/launcher-*.log` 的行为不变**。本 ADR 只**新增**一个事件（`launcher.start` / `launcher.stop`）写到 `logs/events/launcher-*.jsonl`。
- **service 列表** = `webui` / `webinfer` / `memory-store` / `vllm-llama` / `launcher` / `drift-gate`。新增 service 必须先写 spec + ADR。
- **字段禁变**。`status` 一直是 `status`，`latency_ms` 一直是 `latency_ms`。breaking change 走 schema_version bump + 决策书。

## 后果

正面：
- 跨 service 事件查询是 O(file-read) 而不是 grep + regex
- PII 边界写进 spec 和 decision book，code review 容易卡
- schema 文档可被 Python `dataclass` 化，q1 工具自动派生
- log_maintenance 的清理范围明确（Q1 老文件 + 新 JSONL events 共用 retention）

负面 / 取舍：
- 每个 service 自己有 logger 配置（重复 boilerplate）。refactor 时抽 helper
- 文件名含 service 名 → service 改名要兼容老 log。spec 规定 service 字段是稳定标识符
- 引入 `python-json-logger` 第三方依赖（比 stdlib 强但需要 `pip install`）
- 4 个 Q1 文件 + JSONL 文件**短期双写**（migration 期间），有冗余

## 替代方案（拒了）

- **A. 单一中心文件 `logs/events-<UTC>.jsonl`**。多 service 并发写要 lock / append-only atomic。lsof 看 + 多 tail -F 不如 per-file 直观。拒
- **B. syslog / Windows Event Log**。Windows Event Log 是 binary indexed 但 query 受限；syslog 协议偏老（RFC 5424），JSONL 是现代事实标准。拒
- **C. 集中 ELK / Loki / Splunk**。本地单机项目，外部依赖 = 维护负担。决策书 §1 "本项目不是什么：不是 SaaS / 云端服务"。拒
- **D. sqlite 索引（`events.db`）**。每次 log 写都要 INSERT + 同步 fsync。drift_gate history 文件 + log_query 流式 grep 已覆盖需求。引入 sqlite 是 over-defence。拒
- **E. 改用 structlog**。学习成本 + 第三方依赖比 stdlib `logging` + `python-json-logger` 多。结构化字段差不多。拒
- **F. 复用 webui 现有 access log 格式（5 字段 JSONL）作为全局 schema**。access log 只关心 HTTP request；webinfer / memory-store 关心 circuit_breaker / wiki_recall_fail 等不同事件类型。spec 字段集（session_id / extra）是 access log 没的。拒

## 引用

- 决策书：`决策/服务-日志.md` D-2026-08-01-060 (schema 锁定) / D-061 (PII 红线) / D-062 (cleanup 衔接)
- Spec：`doc/specs/log-event-schema.md`
- 现存日志来源（Q1 4 个 commit）：
  - `a97ef08` `logs/drift-gate-history/<ts>.json`
  - `822907b` `logs/launcher-<UTC-ISO>.log` (Start-Transcript)
  - `1515054` `logs/vlm-probes/<UTC-ISO>.json`
  - `0ddd390` `logs/webui-access-YYYY-MM-DD.log` (JSONL ad-hoc)
- 现存决策：`决策/drift-历史.md` DRIFT-2/3 涉及日志信号链路
- 配套 ADR：
  - `0013-webinfer-memory-client-resilience.md`（同一时期 memory client 改 — wiki recall event / circuit breaker event 都从此 spec 落地）
