# Spec：Partial Transcript 前端实时反馈（liveTranscript）
> 生命周期：草稿（2026-08-06 依 D-2026-08-06-001 派生）
> 上游决策：决策/调研-HF-speech-to-speech-姿态.md（UI 纪律 = 学，含 partial feedback）

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
