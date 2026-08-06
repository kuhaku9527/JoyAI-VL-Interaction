# Spec：Partial Transcript 前端实时反馈（liveTranscript）
> 生命周期：已实现（收敛，2026-08-06 逐条验证发现功能已具备）
> 上游决策：决策/调研-HF-speech-to-speech-姿态.md（UI 纪律 = 学，含 partial feedback）

## 验证收敛（2026-08-06，trust but verify）

逐条验证时发现：**本 spec 旨在补的「前端 partial 实时反馈」实际已实现**，并非缺失。

- 前端 `services/webui/src/joy_interaction_webui/static/index.html` 的 `installLlmReplyHandler` 已处理 `asr_partial` 消息（L850-858）：非 final 调 `renderAsrDraft(text)` 渲染草稿气泡，final / `pilot_utterance` 调 `clearAsrDraft()` 移除。
- `renderAsrDraft` / `clearAsrDraft`（L890-918）是完整实现（创建 `.asr-draft` 气泡、更新文本、final 时 `removeChild`），非桩。
- 后端 `jarvis_session.py:214` 在 Jarvis 会话中持续推送 `asr_partial` → 前端闭环已通。

**误判根因**：codex/HF 调研按字面 grep `liveTranscript` 未命中即判定「前端无 liveTranscript 元素」，但功能以 `asr-draft` 气泡命名存在——**命名差异导致的 false negative**，恰是「逐条验证、不盲信」要规避的陷阱。

**结论**：**不新增 `liveTranscript` 元素**。新增会与 `asr-draft` 重复显示，违反「约法三章·增新删旧」。本 spec 收敛为「确认 asr-draft 已满足 partial 反馈意图」，无需代码改动。若后续要统一命名为 `liveTranscript`，须同步删除 `asr-draft`（增新删旧），单列任务。

## §1 因果链（Why）
- **Why**：Jarvis 模式 ASR 定稿后才显示 `pilot_utterance`，用户说话过程中前端无「正在输入」反馈，体验断层。后端已通过 `on_asr_partial` → `notify_session_asr_partial`(jarvis_session.py:214) 推送 partial，仅缺前端元素（grep 无 `liveTranscript`）。
- **被否方案**：① 轮询 final（延迟高）；② 改 ASR 协议（过度）。→ 选「前端增 liveTranscript 半透明元素，订阅既有 partial 事件」。

## §2 范围与负面约束（What NOT）
- **做**：`services/webui/src/joy_interaction_webui/static/` 增 `liveTranscript` 元素 + 在 partial 事件写文本（半透明打字动画）。
- **不做**：不改后端 partial 管道；不与 `pilot_utterance`(final) 冲突（一个 partial 一个 final 共存）。
- **负面约束**：禁止用 partial 文本触发任何决策（仅展示）；禁止阻塞主对话事件总线。

## §3 方案（What）
- 前端订阅 `notify_session_asr_partial` 的现有事件，渲染到 liveTranscript；final 到达后淡出。

## §4 Harness
- 无（前端 feature）。

## §5 验收
- 浏览器手验：用户说话时 liveTranscript 半透明显示逐字；final 后淡出，`pilot_utterance` 仍正常。
