# 交互模式与决策 Token 规范（跨域 L4）

> 本文件记录 **三交互模式隔离（live/call/jarvis）+ decision token 处理规范** 的已确定决策。
> 来源 spec: `doc/specs/interaction-mode-isolation.md`；落地 PR #71（前端）/ #72（后端）；main=`6df743b`（2026-08-03）。
> 覆盖 L4 `D-2026-08-03-001` ~ `D-2026-08-03-002`。

---

## D-2026-08-03-001  三交互模式语义与边界（live/call/jarvis）

- **事实**: 系统有三种交互模式，语义隔离、不互通：live（源项目既有，三判断：沉默/主动搭话/回复）、call（纯语音转文字→聊天框，等同打字，无模型决策语义）、jarvis（常驻监听→唤醒→任务→结束词静默退出，静默退出靠 `decision` 字段的既有实现）。call/jarvis 的 user-facing 输出不得含决策 token；live 保留完整三判断。
- **来源**: spec `doc/specs/interaction-mode-isolation.md` + PR #71/#72（2026-08-03 合入 main=`6df743b`）
- **校验**: `grep -rn "interaction_mode" services/webinfer/infer_loop.py services/webui/src/joy_interaction_webui/server.py` → webinfer 读取并透传 live/call/jarvis；call 路径传 `"call"`、jarvis 唤醒词传 `"jarvis"`；`grep -n "NO_DECISION_SYSTEM_PROMPT" services/webinfer/prompt_constants.py` → call 用无 token prompt
- **预期**: 三模式行为隔离；call/jarvis 不露决策 token；live 三判断不变
- **Drift**: 无
- **Owner**: 架构 / 前端 / 后端
- **锁定**: 🔒

---

## D-2026-08-03-002  decision token 处理规范（剥离只作用于 content，decision 字段保留）

- **事实**: 决策 token（`</?silence>`/`</?response>`/`</?delegation>`）剥离**只作用于** `_chat_payload_finalize` 的 user-facing `content`（`strip_decision_tokens`）；`decision` 字段由 `parse_model_decision(ctx.raw_text)` 解析（raw_text 保留 token，不得剥离）。jarvis 静默退出靠 `harness["decision"]`（jarvis_mode.py:1218/1261），**不得破坏**。前端 `getVlmDisplayText`（index.html）为唯一清洗源。`force_silence_before_query` 仅 live+无 query 生效（`_is_forced_silence`）。
- **来源**: spec + PR #71/#72 + 代码 `services/webinfer/response_format.py:110`(strip 正则) / `infer_loop.py:758`(_chat_payload_finalize) / `:535`(_is_forced_silence) / 前端 `index.html`:getVlmDisplayText / `jarvis_mode.py:1218,1261`
- **校验**: `grep -n "def strip_decision_tokens" services/webinfer/response_format.py` → 定义（6 变体+大小写+内部空白）；`grep -n "decision = parse_model_decision(ctx.raw_text)" services/webinfer/infer_loop.py` → :758 附近；`grep -n 'harness\["decision"\]\|decision != "silence"' services/webui/src/joy_interaction_webui/jarvis_mode.py` → 静默退出 intact
- **预期**: user-facing content 无 token；decision 字段有 token；jarvis 静默退出功能 intact
- **Drift**: 无
- **Owner**: 后端 / 前端
- **锁定**: 🔒

---

## 关联索引

- 推理网关契约：见 `服务-webinfer.md`（D-023~035）
- 前端清洗源：见 `服务-webui.md`（D-032~039）
- 端口 / 启动：见 `跨域铁律.md`、`启动链路.md`
- 质量门禁（ruff format）：见 `工程规范.md`（D-2026-08-03-003）
