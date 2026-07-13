# Spec: LLM 路径合并（Option B）— 2026-07-13

> **状态：✅ 已实施（v3.37）**（2026-07-13）：所有 5 slices TDD 落地：webinfer 52 + webui 96 测试全绿。
> 当前快照见 `doc/specs/2026-07-13-current-state.md` §1（v3.37 唯一权威）。

> **目的**：把当前两条独立的 LLM 调用路径合并到 **webinfer 单一入口**，让 voice / video 两条链路共享 system prompt + 记忆 + token guard + 决策 token 解析。
> **范围**：
> - **webinfer**：新增 `POST /v1/text/chat`（纯文本 + 编排）端点
> - **webui / jarvis_mode**：`_send_to_llm` 默认走 webinfer，新增决策 token 剥离 + 委派触发
> - **不动**：现有 `POST /v1/chat/completions`（多模态链路）
> **驱动问题**：见 `doc/specs/2026-07-13-current-state.md` §3.2 + 上轮对话的两条 LLM 路径分析。

---

## 1. 设计原则

1. **单一入口**：所有 LLM 调用走 webinfer（含 text-only + multimodal）。`llama-server :7060` 不再被 webui 直接连接。
2. **编排复用**：character profile / `[Local Wiki]` / prompt token guard / 决策 token 解析在两路里行为一致。
3. **决策 token 不进 TTS**：webinfer 在返回前剥离 `</silence>` / `</response>` / `</delegation>`，避免 BT-7274 把委派标记念出来。
4. **`</delegation>` 仍触发后台**：webinfer 解析到 `</delegation>` 时返回 `streamingharness.decision="delegation"` + `delegation_question`，webui 收到后调 `BackgroundModelService.handle_foreground_response`（沿用现有视频链路委派逻辑）。
5. **端点语义清晰**：`/v1/text/chat` 仅纯文本（拒绝 image_url content），`/v1/chat/completions` 维持多模态。

---

## 2. Endpoint 契约

### 2.1 `POST /v1/text/chat`

**请求**

```http
POST /v1/text/chat HTTP/1.1
Content-Type: application/json
x-streaming-session: jarvis-<uuid>     # 可选；缺省从 body.session_id 取；都没有则用 "default"

{
  "model": "joyai-vl-interaction-preview",     # 可选；走 MAIN_BACKENDS 路由
  "session_id": "jarvis-<uuid>",                # 可选；与 header 同义
  "language": "zh",                             # 可选；默认 "en"，仅影响 [Local Wiki] 头
  "messages": [
    {"role": "system", "content": "..."},       # 可选；若提供则覆盖默认 system prompt
    {"role": "user", "content": "铁驭，帮我查一下 RTX 5060 Ti 跑 Qwen3-7B 的显存占用"},
    {"role": "assistant", "content": "Looking that up."}
  ],
  "max_tokens": 200,                            # 可选；缺省走 AdapterConfig.main_max_tokens
  "temperature": 0.7                            # 可选
}
```

**400 拒绝条件**
- 任一 message 的 content 是 list 且含 `type=image_url` / `type=image` 的 part。
- 任一 message 的 content 含 `data:image/...;base64,...`（防止误传帧）。
- 任一 message 的 role 不是 `system|user|assistant`。

**200 响应**（OpenAI chat completion 兼容）

```json
{
  "id": "chatcmpl-text-<uuid>",
  "object": "chat.completion",
  "created": 1752432000,
  "model": "joyai-vl-interaction-preview",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Looking that up."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 1234, "completion_tokens": 8, "total_tokens": 1242},
  "streamingharness": {
    "decision": "response",
    "delegation_question": null,
    "memory_chars": 0,
    "qa_history_len": 3,
    "prompt_chars": 4521,
    "trimmed_turns": 0
  }
}
```

`streamingharness.decision` 取值：
- `"silence"`：模型吐 `</silence>`，`choices[0].message.content` 为空串。
- `"response"`：模型吐 `</response> X`，content 为 X。
- `"delegation"`：模型吐 `</delegation> Q`，content 为空串（前台短句），`delegation_question=Q`。

**502 错误条件**
- 主 LLM 调用失败（llama-server 不可达 / 超时）。
- 字符预算严重超限导致 trim 后仍 > ctx（保留原 502 行为）。

### 2.2 与 `/v1/chat/completions` 的关系

| 维度 | `/v1/chat/completions` | `/v1/text/chat` |
| --- | --- | --- |
| 接受 image_url content | ✅ | ❌（400） |
| 帧持久化 / chunk summary / mid-term 更新 | ✅ | ❌（text-only 不耗 chunk） |
| System prompt 注入（character + Local Wiki） | ✅ | ✅ |
| Prompt token guard | ✅ | ✅ |
| Decision token 解析 | ✅ | ✅ |
| QA history 更新 | ✅ | ✅ |
| 适用场景 | 视频/VLM 多模态 | Jarvis 语音对话纯文本 |

---

## 3. webui / jarvis_mode 改动

### 3.1 默认 URL

```python
# services/webui/src/joy_interaction_webui/jarvis_mode.py
@dataclass
class JarvisConfig:
    llm_api_url: str = "http://127.0.0.1:7060/v1"           # 旧（直连 llama）
    llm_chat_path: str = "/chat/completions"                # 旧
    # ↓ 新默认值
    llm_api_url: str = "http://127.0.0.1:8070/v1"           # 走 webinfer
    llm_text_path: str = "/text/chat"                        # 纯文本端点
    llm_multimodal_path: str = "/chat/completions"           # 兜底保留
```

`_send_to_llm` 路由逻辑：
```python
if image_b64:
    url = self.config.llm_api_url + self.config.llm_multimodal_path
else:
    url = self.config.llm_api_url + self.config.llm_text_path
```

环境变量（向后兼容）：
- `JARVIS_LLM_API_URL`：覆盖 `llm_api_url`
- `JARVIS_LLM_TEXT_PATH`：覆盖 `llm_text_path`，默认 `/text/chat`
- `JARVIS_LLM_MULTIMODAL_PATH`：覆盖 `llm_multimodal_path`，默认 `/chat/completions`

### 3.2 决策 token 处理

`_send_to_llm` 收到 webinfer 响应后：
- 读 `streamingharness.decision`
- 当 `decision == "silence"`：broadcast 空字符串 + 不触发 TTS
- 当 `decision == "response"`：broadcast 干净文本 + 触发 TTS
- 当 `decision == "delegation"`：broadcast 前台短句（兜底用 `delegation_question` 截前 30 字），调 `BackgroundModelService.handle_foreground_response(text + delegation_question)`

`_conv_history` 始终记录 `(user, text)` 与 `(assistant, response_text)`（response_text 为干净文本）。

### 3.3 不变量

- `_send_to_llm` 公共签名不变：`async def _send_to_llm(self, text, *, stream_tts=True, image_b64=None)`
- `notify_session_llm_reply` 收到的 payload 永远是干净文本（决策 token 已剥离）
- TTS 收到的是干净文本

---

## 4. 测试策略（TDD vertical slices）

每片都是「先红后绿」，每片完成后跑该片测试，确认通过再开下一片。

### Slice 1 — `/v1/text/chat` 基本通路
- `test_text_chat_rejects_image_url`：请求带 image_url content → 400
- `test_text_chat_rejects_data_url_in_text`：content 含 `data:image/...;base64` → 400
- `test_text_chat_returns_clean_text_on_response`：主模型吐 `</response> hi` → 200, content=`hi`
- `test_text_chat_returns_empty_on_silence`：主模型吐 `</silence>` → 200, content=`""`

### Slice 2 — system prompt 注入
- `test_text_chat_includes_character_profile`：mock 主模型收到 messages[0].content 含 BT-7274 块
- `test_text_chat_includes_local_wiki`：mock 主模型收到 messages 含 `[本地知识库]`

### Slice 3 — prompt token guard
- `test_text_chat_token_guard_trims_old_turns`：构造超长 history → mock 主模型收到的 messages 比 inbound 少

### Slice 4 — 委派 + qa_history
- `test_text_chat_parses_delegation`：主模型吐 `</delegation> Q` → decision=`delegation`, delegation_question=`Q`
- `test_text_chat_updates_qa_history`：两次调用 → 第二次主模型收到的 messages 含上一轮 assistant

### Slice 5 — jarvis_mode 路由
- `test_jarvis_default_uses_webinfer_text_chat`：`_send_to_llm(text)` 时 mock httpx 收到 POST 到 `:8070/v1/text/chat`
- `test_jarvis_image_b64_uses_webinfer_chat_completions`：`_send_to_llm(text, image_b64=b"...")` 时 mock httpx 收到 POST 到 `:8070/v1/chat/completions`

### Slice 6 — jarvis_mode 决策 token
- `test_jarvis_strips_decision_tokens`：webinfer 返回 decision=`response` → `_stream_tts` 收到 `hi`（不是 `</response> hi`）
- `test_jarvis_triggers_delegation_on_decision`：webinfer 返回 decision=`delegation` + delegation_question=`Q` → `BackgroundModelService.handle_foreground_response` 被调一次，参数含 Q
- `test_jarvis_skips_tts_on_silence`：webinfer 返回 decision=`silence` → 不创建 `_tts_task`

### Slice 7 — 集成
- `test_jarvis_e2e_webinfer_text_chat`：起本地 webinfer（test app）+ mock 主模型 → jarvis_state_machine._send_to_llm → 期望最终 on_llm_response 收到干净文本

---

## 5. 失败兜底

| 场景 | 行为 |
| --- | --- |
| webinfer 不可达 | jarvis 回退到原直连 llama 7060？**否**：必须显式失败 + log error；不让两条路径并存（这正是要消灭的问题） |
| 主 LLM 502 | webinfer 返回 502 → jarvis `_send_to_llm` 捕获，broadcast `[LLM error: ...]`，不 TTS |
| decision=`delegation` 但 background-agent 不可达 | webinfer 已返回，jarvis 调 BackgroundModelService 时吞掉异常（fail-soft）；前台文本仍 broadcast |

---

## 6. 回滚

1. webinfer `/v1/text/chat` 是新增端点，删除即回滚视频路径（不删它）。
2. jarvis_mode 默认 URL 改回 `7060/v1`，`_send_to_llm` 路由删除（强制走 `/text/chat`）— 2 行代码。

---

## 7. 不在范围

- 不动 `_forward_text_only`（`/v1/chat/completions` 的纯文本快速通道，保留供内部 / 显式 opt-out 使用）。
- 不动 background-agent 实现（仍沿用 `BackgroundModelService.handle_foreground_response`）。
- 不动 memory-store（不增加新端点）。
- 不做 SSE streaming（响应仍是完整 JSON，与现有 `/v1/chat/completions` 一致）。

---

> 本 spec 是 B 选项的实施合同。

---

## 8. 实施记录（v3.37）

| Slice | 内容 | 测试文件 | 测试数 |
| --- | --- | --- | --- |
| 1 | `POST /v1/text/chat` 基本通路 + 400 image 拒绝 | `services/webinfer/tests/test_text_chat_endpoint.py` | 9 |
| 2 | system prompt 注入（character + Local Wiki） | `services/webinfer/tests/test_text_chat_prompt.py` | 5 |
| 3 | jarvis_mode webinfer 路由（按 `image_b64` 选 path） | `services/webui/tests/test_jarvis_webinfer_routing.py` | 7 |
| 4 | jarvis_session `_background_service` 注入 + `_make_llm_callback` 去重 | `services/webui/tests/test_jarvis_background_wiring.py` | 3 |
| 5 | 集成 e2e（真实 aiohttp AppRunner + 后台 daemon loop） | `services/webui/tests/test_jarvis_webinfer_e2e.py` | 3 |

**总计**：webinfer 52 passed（其中 slice 1+2 占 14）；webui 96 passed（其中 slice 3+4+5 占 13）。

**关键代码改动**：
- `services/webinfer/live_adapter.py`：新增 `handle_text_chat` / `_handle_text_payload` / `_update_text_qa_history`；`_chat_completion_response` 加 `decision`/`delegation_question`/`memory_chars`/`qa_history_len`/`prompt_chars`/`trimmed_turns`；路由注册 `/v1/text/chat`。
- `services/webui/src/joy_interaction_webui/jarvis_mode.py`：`JarvisConfig` 加 `llm_api_url` 默认 `http://127.0.0.1:8070/v1` + `llm_text_path=/text/chat` + `llm_multimodal_path=/chat/completions`；`_send_to_llm` 改为按 `image_b64` 路由；读 `streamingharness.decision`；delegation 触发 `BackgroundModelService.handle_foreground_response`。
- `services/webui/src/joy_interaction_webui/jarvis_session.py`：`create_session` 注入 `_background_service`；`_make_llm_callback` 删除 delegation 路由避免双触发。
- `services/webui/tests/conftest.py`：`webui/src` + `webinfer` 加到 sys.path（e2e 启动 webinfer app 需要）。

**关键决策**：
1. `/v1/text/chat` 拒绝任何 image_url / data:image 内容（400）。
2. caller-supplied system message 被 composed prompt **替换**（不是追加）。
3. composed 为空时只转发 caller messages（不做空 system 注入）。
4. `_make_llm_callback` 只 broadcast，不再做 delegation routing（避免与 `_send_to_llm` 双触发）。
5. `_background_service` 通过 session_manager 注入，缺失时 graceful（不影响主路径）。
改动量：webinfer 新增 ~120 行（端点 + 编排复用）+ jarvis_mode 修改 ~40 行（路由 + 决策处理）+ ~250 行测试。**预计 TDD 7 片**。
