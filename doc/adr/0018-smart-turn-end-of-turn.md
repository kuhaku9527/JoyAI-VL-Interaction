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

## 澄清（2026-08-08，审查组）

**Smart Turn 与 ASR 后端（云 vLLM/SiliconFlow ↔ 本地 sherpa-onnx）是正交关系，非耦合。**

- `is_end_of_turn()` 纯音频原生（16k mono int16 → Whisper log-mel → ONNX），忽略 transcript，只判「说完了没」；门禁仅 `SMART_TURN_ENABLED=1` + 模型资产就绪（jarvis_mode.py:429/546），全代码无 ASR 后端判断。
- 它补在「声学端点触发 → 调 LLM 之前」（决策点 4/7），与 ASR 用哪家用无关。
- 用云 ASR 时 Smart Turn 仍有用且更值（云端按量计费，前置语义端点可少发截断音频省成本/延迟）；本地 ASR ≠ 一定带 Smart Turn（后者独立可选开关，默认关）。

**子代理误判根因**（曾得出「本地 ASR 启用时一定是 sherpa-onnx + Smart Turn」）：

1. `smart_turn_adapter.py:3` docstring「on top of sherpa-onnx acoustic endpoint detection」被读成"功能依赖 sherpa-onnx ASR 引擎"，实则指"声学端点（沉默检测，后端无关）"这一底层真相源；
2. 二者均位于 `D:/AI/models` 下本地 CPU ONNX（sherpa-onnx/ + smart-turn/），被模式匹配成"本地栈捆绑"（云端 ASR 走 `services/asr/asr_adapter.py` 的 vLLM/SiliconFlow 上游，不在 webui ONNX 内）；
3. 决策点 5「onnxruntime 随 sherpa-onnx 已在运行时可用」被过度读成功能耦合（实为依赖可用性，且 `import onnxruntime` 失败也 fail-open）。

**后续动作**：修正 `smart_turn_adapter.py:3` docstring 措辞（改为「on top of the backend-agnostic acoustic endpoint (silence) detection」），消除未来误判源（见代码 PR）。
