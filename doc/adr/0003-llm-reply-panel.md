# ADR 0003 — LLM 回复面板从黑箱改为可见

- **状态**：Accepted
- **日期**：2026-07-11
- **作者**：Codex

## 背景

用户说："webui 前端里要显示 llm 的回复，没有参考状态都不知道有没有连接上 llm 模型，甚至是调试，对我来说是黑箱的。"

调研后发现：`index.html` 第 3995 行**已经**有 `<div id="llmReplySection">`，第 8738 行**已**有 `pushLlmMessage` / `renderLlmMessages` 函数，第 8822 行**已**有 `pollServiceStatus`。`server.py` 第 80 行**已**有 `notify_session_llm_reply` 推 WS。

**代码都在，但用户实际看不到**。问题在：

1. `llm-reply-section` 没有显式 `display: block` 默认为 `block`（理论可见）— 需要审计
2. 没有流式（LMM final reply）—— 长回复要等 1-3 秒才有，看上去"卡死"
3. 服务状态徽章没有 LLM model 名 + 首字延迟，看不出 LLM 是连上了还是断的

## 决策

执行 3 件事让"黑箱"变"可视"：

### A. 保证可见

- `llm-reply-section` CSS 加 `display:block` + 默认折叠/展开按钮
- 区域放在聊天区**正上方**（不是底部）
- LLM/TTS/KWS 徽章统一 8px 圆角 + emoji 前缀，状态变更时高亮 1 秒

### B. 加 LLM 服务元数据（不阻塞）

- `GET /api/llm/status?session_id=` 返回 `model` / `ttfb_ms` / `connected`
- 前端把 model 名显示在状态徽章旁（如 `LLM OK · joyai-vl 8.19B IQ4`）

### C. 加 LLM 流式增量（中等改动）

- `JARVIS_LLM_STREAMING=true` 时改 `POST /v1/chat/completions`，加 `"stream": true`
- 解析 SSE，**逐 token 推 `llm_reply_delta` WS 消息**给前端
- 前端累积 token，按"打字机"风格实时显字
- 后端安全 fallback：streaming 关时仍走非流式

## 测试

`test_llm_stream_broadcast.py` 验证：
- mock llama-server SSE 返回 `data: {"choices":[{"delta":{"content":"你"}}]}...`
- 每条 delta 都产生一条 `llm_reply_delta` WS 帧
- 累积后等于 final 内容

## 实施现状（2026-07-12 验收）

> 配套补：DELIVERY.md §7 v3.3 + doc/00-main-direction.md §3 "LLM 回复面板可见" / §4.0 #2 半落地。

| ADR 决策 | 状态 | 证据 |
|---|---|---|
| **A. 保证可见**（CSS `display:block` + 8px 圆角徽章 + 状态变更高亮 1s） | ✅ 已落地 | `services/webui/src/joy_interaction_webui/static/index.html` `llm-reply-section` + `.service-badge`（jarvis-mode.md §13.1 "WebUI 加 LLM/TTS/KWS 服务状态徽章 + LLM 回复面板"对应） |
| **B. LLM 服务元数据**（`/api/llm/status?session_id=` 返回 model / ttfb_ms / connected） | ✅ 已落地 | `services/webui/src/joy_interaction_webui/server.py` `llm_status` handler + `setup_jarvis_routes` 注册 `/api/llm/status` |
| **C. LLM 流式增量**（`JARVIS_LLM_STREAMING=true` → SSE → 逐 token 推 `llm_reply_delta`） | ⚠️ 部分落地：env flag + server.py 框架已就位；test_llm_stream_broadcast.py 尚未补全 | jarvis-mode.md 自标 "⚠️ 待全链路 e2e（流式 ASR export 修复 P4 子代理）" 仍是真 |

## 后果


- 用户的"黑箱"焦虑消除；调试（是否连上 LLM / 是不是 LLM 卡）即时可视化
- 流式改动**仅当 env `JARVIS_LLM_STREAMING=true`** 才启用，旧路径不变