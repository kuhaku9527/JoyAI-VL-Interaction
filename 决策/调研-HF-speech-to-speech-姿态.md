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

## 派生工单（采纳项的 spec-first 路由）
- A voice prompt → `doc/specs/voice-prompt-template-spec.md`
- B partial transcript → `doc/specs/live-transcript-ui-spec.md`
- C Design Tokens → `doc/specs/voice-ui-design-tokens-spec.md`
- E Smart Turn → `doc/specs/smart-turn-end-of-turn-spec.md`（架构级，须 ADR `0018+`）
- F README -Mode → `doc/specs/readme-mode-matrix-spec.md`
- D / VAD-3 / I → 搁置或已做，不开工单。

- modified: 2026-08-06｜by AI（审查组）｜approved: 用户
