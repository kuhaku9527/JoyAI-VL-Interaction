# Spec：Smart Turn v3.2 语义端点检测（end-of-turn）
> 生命周期：草稿（2026-08-06 依 D-2026-08-06-001 派生）
> 上游决策：决策/调研-HF-speech-to-speech-姿态.md（barge-in = 学 Smart Turn）+ VAD 专项 T-VAD-2
> 须配套 ADR：`doc/adr/0018-smart-turn-end-of-turn.md`（ADR0017 已被 drift-gate-launcher 占用，须 0018+）

## §1 因果链（Why）
- **Why**：当前 ASR endpoint detection 仅声学（rule1/2/3 看 trailing silence），用户说「嗯……那个」误判说完、说「行谢谢」无停顿被并段。需语义级 end-of-turn。
- **被否方案**：① 调 rule 参数（治标）；② 加 Silero VAD（T-VAD-1 已否，重复造轮子）；③ 改队列架构（T-HF-H 已否）。→ 选「Smart Turn v3.2 ONNX，在 endpoint detection 之后、LLM 之前加一层语义判断」。
- **风险**：Smart Turn 在思考停顿时可能误判「说完」（0.1% CPU，~50MB 模型，+50ms 延迟），需 e2e 验证。

## §2 范围与负面约束（What NOT）
- **做**：`services/asr/jarvis/` 增 `smart_turn_adapter.py` 包装 pipecat-ai/smart-turn-v3.2 ONNX；在 `asr.py:feed_chunk` 末尾（DIALOG_ACTIVE 内）调用，返回 complete+probability 决定是否跳出 DIALOG_ACTIVE 走 LLM。
- **不做**：不动 KWS；不动 ASR endpoint detection；不改决策 token；不引入新服务进程（同进程 ONNX 推理）。
- **负面约束**：禁止用 Smart Turn 输出替代 EXIT_WORDS（两者互补：Smart Turn 管「说完了没」，EXIT_WORDS 管「明确结束」）；禁止在未 DIALOG_ACTIVE 时调用。

## §3 方案（What）
- 接入点 `asr.py:feed_chunk` 末尾；模型 `pipecat-ai/smart-turn-v3` / `smart-turn-v3.2-cpu.onnx`（~50MB）；CPU 推理 <8s 音频。
- 阈值：probability > 0.5 视为 end-of-turn（待 e2e 标定）。

## §4 Harness
- 验收 harness（可复现）：golden 集 = 「嗯……那个」（应判未完）+ 「行谢谢」（应判完）+ 正常句；pytest 跑 `smart_turn_adapter` 三例断言。属条件性 harness（跨 ≥2 测试复用）→ 可固化。

## §5 验收
- pytest：`tests/` 增 `test_smart_turn.py`，golden 三例通过。
- 手验：Jarvis 模式「嗯……那个」不再误触发 LLM；barge-in 体验不变（Smart Turn 不接管打断）。
