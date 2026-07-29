# doc/specs/ — 决策前的 spec 落点（待审查组消费）

本目录**本就存在**，是各端对话在提出跨域 / 架构 / 不可逆改动时写 **spec** 的既有位置。ADR 在同级目录 `doc/adr/`。

## 命名约定（沿用既有双轨，不强制统一）
- 日期前缀式：`<YYYY-MM-DD>-<topic>.md`（如 `2026-07-14-loose-coupling-services.md`、`2026-07-13-current-state.md`）
- 功能命名式：`<topic>-spec.md` 或 `<topic>.md`（如 `memory-store-skeleton-spec.md`、`hybrid-wake-confirm.md`、`kws-recall-optimization.md`）
- 新写时二选一即可；spec 内可交叉引用配套 ADR：`doc/adr/XXXX-*.md`（见 `memory-store-skeleton-spec.md` 示例）。

## 内容约定
- 结构参考既有文件：`## Problem Statement` / `## Solution` / `## User Stories` / `## Implementation Decisions` / `## Testing Decisions` / `## Out of Scope`。
- **不写最终决策**（那归 `决策/`）；spec 是决策的前提案（what / options / 推荐）。

## 生产路由（防多端污染）
- **只写不读其他端**：端点写完自己的 spec 后，不读其他端对话；由审查组对话统一召回、交叉验证、写 `决策/`，避免多端互读污染。
- 处理后：spec 保留为过程档案（不删），供追溯。
- 触发：用户手动叫审查组对话"去收 `doc/specs/` + `doc/adr/` 写决策"时才处理，**不自动轮询**。
