# ADR 0006: LLM 网关单入口（v3.37）

- 状态: Accepted
- 日期: 2026-07-13
- 上下文: doc/specs/2026-07-13-llm-path-consolidation.md

## 决策
所有 LLM 调用必须经过 webinfer :8070。webui 不再持有指向 :7060 llama-server
的直接连接。webinfer 暴露两个 HTTP 入口:
- POST /v1/text/chat (纯文本，拒绝 image_url)
- POST /v1/chat/completions (多模态)

## 不变 / 边界
- 系统 prompt 注入、token guard、决策 token 解析、qa_history 写回、memory
  warmup 全部在 webinfer 完成；webui 只做 HTTP 转发 + streamingharness 字段读取。
- webinfer 挂 = 三条入口全瘫。**显式失败，不回退到 :7060 直连**。

## 后果
- webinfer 成为新 SPOF（之前 Jarvis 文本直连绕开了它）。
- _send_to_llm 公共签名不变，向后兼容。
- 决策 token silent regression 兜底（jarvis 侧 fallback 到 decision=response）需要
  在 ADR 里明确写下来（防 schema 漂移）。

## 替代方案（拒了）
- A: 在 webui 层做共享编排 → 维护成本高，webui 已超载。
- C: 各自维护一份编排 → 正是要消灭的两条路径问题。

## 引用
- doc/specs/2026-07-13-llm-path-consolidation.md
- doc/specs/2026-07-13-current-state.md §1
- services/webui/src/joy_interaction_webui/jarvis_mode.py:168-170, :1078
- services/webinfer/live_adapter.py:1164, :3451