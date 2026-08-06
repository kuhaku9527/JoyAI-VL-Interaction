# ADR-0018：Smart Turn 语义端点检测（end-of-turn）

- **状态**：Accepted（2026-08-06，审查组）
- **上游**：决策/调研-HF-speech-to-speech-姿态.md（barge-in = 学 Smart Turn）+ VAD 专项 T-VAD-2
- **关联 Spec**：doc/specs/smart-turn-end-of-turn-spec.md（草稿）

## 背景（Context）

当前 ASR endpoint detection 仅声学（`asr.py` rule1/2/3 看 trailing silence）：
- 用户说「嗯……那个」被误判说完，提前触发 LLM；
- 用户说「行谢谢」无停顿被并入下一段。

需要在「声学 endpoint」之后、调 LLM 之前，加一层**语义级 end-of-turn** 判断。

## 决策（Decision）

1. 采用 **pipecat-ai/smart-turn-v3 的 `smart-turn-v3.2-cpu.onnx`（CPU int8，~8.6MB）**，在 endpoint detection 之后、LLM 之前加语义判断。
2. **同进程 ONNX 推理**，不引入新服务进程。
3. **接入点 = 编排器结束判定**（`jarvis_mode.py` 的 ASR endpoint → 调 LLM 分支，原 `feed_audio`/L989 附近），**不是** `asr.py:feed_chunk` 末尾——`DIALOG_ACTIVE` 状态机在编排器而不在 ASR 层（spec 草案的落点有误，验证后修正）。
4. **不替换** EXIT_WORDS（管「明确结束」）与声学 endpoint（管「声学停顿」）；Smart Turn 只补「说完了没」的语义层。
5. **不依赖 `pipecat` 包**（仓库未安装）；直接用 `onnxruntime` 加载 ONNX（`onnxruntime` 随 sherpa-onnx 已在 ASR/WebUI 运行时可用）。
6. **适配器位置**：`services/webui/src/joy_interaction_webui/smart_turn_adapter.py`（消费者是编排器，跨包 import `asr/jarvis` 脆弱）——与 spec 草案写的 `asr/jarvis/` 路径不同，验证后修正。
7. **fail-open + 默认关闭**：
   - 模型资产缺失 / `onnxruntime` 不可用 → `is_end_of_turn` 返回 `(False, 0.0)`，日志告警一次，**不抛异常、不伪造结果、不阻断 ASR 管线**；声学 endpoint 仍是真相源。
   - 接线为 `SMART_TURN_ENABLED=1` **且**模型资产就绪才介入；默认行为 100% 不变。

## 后果（Consequences）

- ✅ 补语义 end-of-turn，改善「嗯……那个」「行谢谢」误判。
- ➖ 已从 HuggingFace 拉取 `smart-turn-v3.2-cpu.onnx`（~8.6MB int8，`pipecat-ai/smart-turn-v3`）到 `D:/AI/models/smart-turn/`（或 `SMART_TURN_MODEL_PATH` / `JOYAI_MODELS_ROOT`）。
- ➖ 精确输入张量契约须对照拉取的模型卡核验；golden 测试（trailing_thought / explicit_end / normal_sentence）无模型时自动 skip（同 memory-store bge-m3 本地权重惯例）。
- ➖ 开启 `SMART_TURN_ENABLED` 后须 e2e 标定阈值（默认 `probability >= 0.5`）与 barge-in 体验。
- 🔒 不接管打断（barge-in 仍由 ASR partial 触发，~200–400ms），Smart Turn 只判「说完没」。

## 验证

- 适配器单测 `services/webui/tests/test_smart_turn.py`：fail-open（无模型 → `(False,0.0)` 不崩）+ golden 定义；golden 断言在无模型时 skip。
- 接线：`jarvis_mode.py` `__init__` 实例化 `SmartTurnAdapter` + `_smart_turn_enabled` + `_recent_audio` 缓冲；新增 `_smart_turn_allows_send` 守卫，在结束判定分支前置调用（模型判「未说完」则 `return` 保留 DIALOG_ACTIVE）。
- 默认（未设 `SMART_TURN_ENABLED`）行为零变化，已通过现有 `test_*` 状态机测试。
