# Spec：Smart Turn v3.2 语义端点检测（end-of-turn）
> 生命周期：草稿（2026-08-06 依 D-2026-08-06-001 派生）
> 上游决策：决策/调研-HF-speech-to-speech-姿态.md（barge-in = 学 Smart Turn）+ VAD 专项 T-VAD-2
> 须配套 ADR：`doc/adr/0018-smart-turn-end-of-turn.md`（ADR0017 已被 drift-gate-launcher 占用，须 0018+）
> 实现状态：已落地（适配器 + 接线 + ADR0018 + 测试），见下方「验证收敛」。

## §1 因果链（Why）
- **Why**：当前 ASR endpoint detection 仅声学（rule1/2/3 看 trailing silence），用户说「嗯……那个」误判说完、说「行谢谢」无停顿被并段。需语义级 end-of-turn。
- **被否方案**：① 调 rule 参数（治标）；② 加 Silero VAD（T-VAD-1 已否，重复造轮子）；③ 改队列架构（T-HF-H 已否）。→ 选「Smart Turn v3.2 ONNX，在 endpoint detection 之后、LLM 之前加一层语义判断」。
- **风险**：Smart Turn 在思考停顿时可能误判「说完」（0.1% CPU，~50MB 模型，+50ms 延迟），需 e2e 验证。

## §2 范围与负面约束（What NOT）
- **做**：`services/webui/src/joy_interaction_webui/smart_turn_adapter.py` 用 `onnxruntime` 直接加载 pipecat-ai/smart-turn-v3.2 ONNX（**不依赖 `pipecat` 包**，仓库未安装）；在**编排器结束判定**（`jarvis_mode.py` ASR endpoint → 调 LLM 分支，原 L989 附近）接入，返回 complete+probability 决定是否跳出 DIALOG_ACTIVE 走 LLM。
- **不做**：不动 KWS；不动 ASR endpoint detection；不改决策 token；不引入新服务进程（同进程 ONNX 推理）；不依赖 `pipecat`。
- **负面约束**：禁止用 Smart Turn 输出替代 EXIT_WORDS（两者互补：Smart Turn 管「说完了没」，EXIT_WORDS 管「明确结束」）；禁止在未 DIALOG_ACTIVE 时调用；**默认关闭**（`SMART_TURN_ENABLED=1` 且模型就绪才介入）。

## §3 方案（What）
- 接入点 = 编排器 `jarvis_mode.py` 结束判定分支（非 `asr.py:feed_chunk`；`DIALOG_ACTIVE` 在编排器不在 ASR 层）。适配器实例化于 `__init__`，近期音频缓冲 `~recent_audio`，守卫方法 `_smart_turn_allows_send` 在发送 LLM 前置调用。
- 模型：`smart-turn-v3.2-cpu.onnx`（~50MB），路径 `SMART_TURN_MODEL_PATH` 或 `<JOYAI_MODELS_ROOT>/smart-turn/`；须从 HuggingFace 拉取。
- 阈值：probability > 0.5 视为 end-of-turn（待 e2e 标定）。
- fail-open：模型缺失/`onnxruntime` 不可用 → `is_end_of_turn` 返回 `(False,0.0)` + 日志告警一次，声学 endpoint 仍是真相源。

## §4 Harness
- 验收 harness（可复现）：golden 集 = 「嗯……那个」（应判未完）+ 「行谢谢」（应判完）+ 正常句；`services/webui/tests/test_smart_turn.py` 跑三例。无模型时 golden 自动 skip（同 memory-store bge-m3 本地权重惯例）。

## §5 验收
- pytest：golden 三例（有模型时）；fail-open 单测（无模型 → `(False,0.0)` 不崩）。
- 手验：设 `SMART_TURN_ENABLED=1` + 拉取模型后，Jarvis 模式「嗯……那个」不再误触发 LLM；barge-in 体验不变。

## 验证收敛（2026-08-06，trust but verify）
逐条验证时对 spec 草案做三处修正（均写入 ADR0018）：
1. **接线点**：spec 写「`asr.py:feed_chunk` 末尾（DIALOG_ACTIVE 内）」—— 实际 `DIALOG_ACTIVE` 在编排器状态机，不在 ASR 层；改为 `jarvis_mode.py` 结束判定分支（L989 附近）。
2. **依赖**：spec 写「包装 pipecat-ai」—— 仓库未安装 `pipecat`；改为用 `onnxruntime` 直接加载 ONNX（sherpa 已带）。
3. **适配器位置**：spec 写 `services/asr/jarvis/` —— 消费者是编排器，跨包 import 脆弱；改放 `services/webui/src/joy_interaction_webui/`。
4. **硬依赖**：~50MB ONNX 模型本会话无法获取；故接线为**默认关闭**（`SMART_TURN_ENABLED`），fail-open 保证默认行为零变化。模型拉取 + e2e 标定列为收尾步骤。
