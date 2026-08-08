# D-2026-08-06-001  HF speech-to-speech 调研姿态（学/不学矩阵）

- **事实**: 我们（JoyAI-VL-Interaction）是 VLM 主动看/说/决策的实时多模态代理；huggingface/speech-to-speech 是通用语音对话框架（VAD→STT→LLM→TTS + OpenAI Realtime 兼容）。两家不同赛道。经审查组逐条对照真实代码验证，确立以下逐维决策：可借鉴其工程纪律（Design Tokens / voice prompt / Smart Turn barge-in），不借鉴其协议与产品形态（决策 token 是核心 IP）。
- **来源**: 桌面 `huggingface-speech-to-speech-调研与对比.md` §8 + `-补充.md` §9 VAD 分析 + §12；逐条代码核验见 `.workbuddy/tmp/wayfinder-map-spec-standard-voice.md` 工单段（T-HF-A..I / T-VAD-1..4 / T-HF-POSTURE）。用户 2026-08-06 授权「验证并按 codex 方向采纳」。
- **校验**:
  - 决策 token 单入口：`grep -n "决策 token" doc/adr/0006-llm-gateway-single-entrypoint.md`（应命中）
  - WebRTC 已做：`grep -rln "WebRTC" services/webui/src`（应非空）
  - 无语音 prompt 约束：`grep -rn "no markdown\|laughs" services/webinfer`（应为空，即 A 待补）
  - VAD 已覆盖：`ls services/asr/jarvis/kws.py && grep -n "enable_endpoint_detection" services/asr/jarvis/asr.py`（应存在）
- **预期**: 上述 grep 断言与本矩阵一致；新采纳项（A/B/C/E/F + Smart Turn）开 spec/ADR 时须引用本决策为上游依据。
- **Drift**: 无（本决策为新增，暂无运行态背离）。
- **Owner**: 架构 / 审查组。
- **锁定**: 🔓 软锁（待采纳项 A/B/C/E/F + Smart Turn 落 spec/ADR + 实现后，由 AI 提议关闭）。

## 决策矩阵（采纳 / 不做）
| 维度 | 决策 | 代码核验依据 |
|---|---|---|
| 协议层 | **不学** OpenAI Realtime 兼容 | 决策 token(silence/response/delegate) 是核心 IP；ADR0006 LLM 网关单入口，折进通用协议会逆转它（T-HF-G 不做）|
| 流水线 | **不强改** 队列+线程架构 | FastAPI 异步+进程编排够用；ADR0007 已拆 live_adapter 保门面契约（T-HF-H 不做）|
| UI 纪律 | **学** Design Tokens | voice-ui.md 无设计语言章节（T-HF-C 采纳）|
| Prompt 模板 | **学** voice_prompt 拼接 | system_prompts.py 无语音约束（T-HF-A 采纳）|
| barge-in | **学** Smart Turn v3.2 | 语义级 end-of-turn；ASR endpoint 只声学（T-HF-E / T-VAD-2 采纳）|
| TTS 多备选 | **不学** | 单点 MiniMax 云端(Rapid Clone) 是产品决策，质量+0 显存 |
| STT 多备选 | **不学** | sherpa-onnx KWS + Paraformer 流式已足够 |
| 决策 token | **不学**（保持自研）| 核心 IP，HF 做不到 |
| 本地化部署 | **不学**（已更专）| Windows 单机 + PowerShell 编排已比 s2s 更专 |
| OpenAI 兼容 | **不学**（主动拒绝）| 产品决策 |
| VAD 本体(Silero) | **不做** | KWS + ASR endpoint detection + EXIT_WORDS 已覆盖「有/没人说话」（T-VAD-1）|
| Smart Turn | **做** | 语义端点检测，~150 行 + ONNX，DIALOG_ACTIVE 内生效（T-VAD-2）|

## G/H 不做依据（ADR 冲突钉死，防重议）

把矩阵「协议层 / 流水线」两行的「不做」结论钉死为硬性约束——两项的拒绝理由不是「优先级低」，而是「与已 Accepted 的 ADR 直接冲突」，任何端点不得私自重开。

### G. 协议层：不兼容 OpenAI Realtime（冲突 ADR0006）
- HF 建议：把 webinfer 决策 token 折进 OpenAI Realtime GA 兼容协议作可选层（如接 GPT-4o-realtime 时在 `response.create` 伪装 `tool_choice`）。
- 冲突点：ADR0006《LLM 网关单入口》核心=所有 LLM 调用走 webinfer :8070 自有协议、决策 token 解析在 webinfer 内完成；立 ADR 的根本理由正是「决策 token 是核心 IP，通用协议表达不了它」才保自有协议。折进 Realtime = 逆转 ADR0006。
- 结论：**锁死不做**。G ≠ I（I=WebRTC 传输层，已做）；G 指应用层 Realtime 事件协议，与现有传输无关。
- 重议条件：仅当用户显式要求「对外暴露 OpenAI Realtime 兼容」且接受决策 token 降级。

### H. 流水线：不强改队列+线程（冲突 ADR0007）
- HF 建议：把决策 token 主路径改造成带类型 Python Queue + 强类型状态载体（silence/response/delegate），走队列+线程事件驱动。
- 冲突点：ADR0007《拆分 live_adapter.py》刚把 3531 行单体机械安全拆成 9 子模块+门面（外部契约不变，66 测试绿，里程碑 1 完成）；H 要重写 `live_adapter.py` 核心 = 冲掉 ADR0007 拆分成果、重开敏感区。现状 FastAPI 异步+进程编排够用。
- 结论：**锁死不做**。除非用户显式要求「彻底事件驱动重构」并承担重开 live_adapter 的风险。
- 注：HF 调研文档 §4.3 自身结论即「保持 FastAPI 异步+进程编排」。

- modified: 2026-08-07｜by AI（审查组）｜approved: 用户

## D 项约定（待触发、非不做）

把矩阵「派生工单」里"D 搁置"的语义钉清：D **不是"不做"**，而是"待触发的前瞻目录约定"。

### D. `archive/` / 实验路径隔离约定
- HF 建议（桌面调研 §4.1）：将来若实验 Pocket TTS / Qwen3-TTS 等后端，**先丢 `services/tts/experimental/`** 隔离目录，别直接塞 `services/tts/` 触发 Lint 门禁；现状 `doc/deprecated/` 存在但代码几乎无 `archive/`，缺"明确隔开实验路径"的物理边界。
- 性质：**非架构否决，是前瞻性目录约定**。HF 文档自身标注"等用户主动要做 TTS 后端切换再说，本调研不触发"。
- 结论：**待触发（非不做）**。当前不创建目录、不开 ticket；仅当真正要做 TTS 后端切换时，由执行端按此约定隔离实验代码并补对应 spec。
- 与 G/H 区别：G/H 因冲突 ADR 锁死不做；D 仅"此刻不触发"，无 ADR 冲突，保留未来采纳空间。

- modified: 2026-08-08｜by AI（审查组）｜approved: 用户

## 派生工单（采纳项的 spec-first 路由）
- A voice prompt → `doc/specs/voice-prompt-template-spec.md`
- B partial transcript → `doc/specs/live-transcript-ui-spec.md`
- C Design Tokens → `doc/specs/voice-ui-design-tokens-spec.md`
- E Smart Turn → `doc/specs/smart-turn-end-of-turn-spec.md`（架构级，须 ADR `0018+`）
- F README -Mode → `doc/specs/readme-mode-matrix-spec.md`
- D（待触发，见上「D 项约定」）/ VAD-3 / I → 搁置或已做，不开工单。

- modified: 2026-08-06｜by AI（审查组）｜approved: 用户
