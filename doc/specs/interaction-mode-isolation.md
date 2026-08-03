# Spec: 交互模式隔离与决策 Token 处理规范（interaction-mode-isolation）

- 状态: 已落地（PR #71 前端 / PR #72 后端，合入 main=`6df743b`，2026-08-03）
- 关联决策: `决策/交互模式与决策token规范.md`（D-2026-08-03-001 / 002）
- 关联 ADR: 无（架构级改动事后补 spec，先落地后框定）

## 1. 背景与目标

VLM 内部使用决策 token（`</silence>`/`<silence>`/`<response>`/`</response>`/`<delegation>`/`<delegation>`）做模型侧决策（沉默 / 主动搭话 / 回复 / 委派）。这些 token 是模型推理的**内部标记，绝不应当呈现给最终用户**。

历史实现暴露三类问题（即 issue #44 / #45 根因）：
1. 后端多模态路径把原始 token 留在 user-facing `content`（`infer_loop.py` 多模态分支 `content=ctx.generated_text`），而文本路径已剥离 → 两条路径不一致。
2. 前端曾反向转义 `</silence>`/`<response>` 让其可见（`render_markdown.js` 旧逻辑）。
3. `force_silence_before_query` 全局默认 `True` 且无模式分支 → **模式混合**：call/jarvis 也误发 `</silence>`。

本 spec 框定三交互模式的语义边界 + 决策 token 的处理契约，终结模式串扰。

## 2. 三交互模式（语义与边界）

| 模式 | 语义 | 决策 token（user-facing） | 强制静默 | 系统提示 |
|------|------|--------------------------|---------|---------|
| **live**（直播，源项目既有） | 三判断：沉默 / 主动搭话 / 回复 | 保留（模型决策语义） | 仅 live+无 query 时 | `DEFAULT_SYSTEM_PROMPT`（含决策指令） |
| **call**（纯语音转文字→聊天框，等同打字发） | 纯语音转录输出，无模型决策语义 | **不露 UI**（剥离） | 关闭 | `NO_DECISION_SYSTEM_PROMPT` |
| **jarvis**（常驻监听→唤醒→任务→结束词静默退出） | 用户增量；静默退出靠 `decision` 字段 | 保留（`decision` 字段依赖） | 关闭 | `DEFAULT_SYSTEM_PROMPT`（含决策指令） |

硬约束：
- call / jarvis 的 user-facing 输出**不得包含任何决策 token**（剥离在后端 `_chat_payload_finalize`）。
- live 保留完整三判断逻辑（既有行为不变）。
- **jarvis 静默退出是既有实现**（`jarvis_mode.py` 读 `harness["decision"]`、且 `decision != "silence"` 才 TTS）。本 spec 仅要求"关强制静默 + 保留 decision token"，**绝不破坏其已有实现**。

## 3. 决策 Token 处理契约

- **剥离边界**：仅剥离 user-facing `content`（`_chat_payload_finalize` 调 `strip_decision_tokens`）。`decision` 字段由 `parse_model_decision(ctx.raw_text)` 解析，`raw_text` 保留 token，**不得剥离**（jarvis 静默退出依赖此）。
- **前端唯一清洗源**：`getVlmDisplayText`（index.html）是前端展示层**唯一**决策 token 清洗源，覆盖全部 6 种变体（含大小写、内部空白 `</Silence >`）。调试 `response_payload` 经 `sanitizeDebugPayload` 脱敏；`request_payload` 仍显示系统提示词 token *指令名*（非模型决策，预期保留）。
- **强制静默门控**：`force_silence_before_query` 提取为 `_is_forced_silence`，仅 `live + 无 current_query_text` 时返回 `True`（发 `</silence>`）；call/jarvis 一律 `False`。
- **模式透传**：`interaction_mode` 由 webui `server.py`（call 路径 / jarvis 唤醒词路径）经 webinfer `/v1/chat/completions` payload 传入；webinfer 透传到 prompt 构建（缓存 key 含该开关，避免 live/call prompt 串缓存）。

## 4. 验收 / 校验

- `grep -n "def strip_decision_tokens" services/webinfer/response_format.py` → 定义（6 变体 + 大小写 + 内部空白）。
- `grep -n "_is_forced_silence" services/webinfer/infer_loop.py` → 仅 live + 无 query 生效。
- `grep -n "getVlmDisplayText" services/webui/src/joy_interaction_webui/static/index.html` → 主显示路径调用，无旁路重实现。
- `grep -n 'harness\["decision"\]\|decision != "silence"' services/webui/src/joy_interaction_webui/jarvis_mode.py` → jarvis 静默退出 intact。
- 回归测试：webinfer `test_decision_token_isolation.py`（26 例）、webui `render_markdown.test.js`（8 例）。
