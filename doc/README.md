# 文档索引

> 完整项目文档库。所有文档按"**主方向 → 调研 → 本地化部署（降级）→ 子系统 → 交付与历史**"组织。
> **API 化是主方向，本地化是降级方案**。详见 [`00-main-direction.md`](00-main-direction.md)。

---

## 📌 入门必读（按顺序）

1. **[`00-main-direction.md`](00-main-direction.md)** — 主方向 + 阅读优先级 + v3.2 路线图（**先读这个**）
2. **[`api-optimization.md`](api-optimization.md)** — API 化方案（主路径核心）
3. **[`token-plan-comparison.md`](token-plan-comparison.md)** — 8 家厂商 Token Plan 调研

## 🔍 调研 / 选型

- **[`token-plan-comparison.md`](token-plan-comparison.md)** — 8 家厂商 Token Plan 对比 + MiniMax 推荐
- **[`lightweight-replacement.md`](lightweight-replacement.md)** — 硬件选型（GGUF / 摘要模型 / ASR / TTS）

## 🖥️ 本地化部署（**降级方案**）

- **[`pm-local.md`](pm-local.md)** — PM 视角的本地化方案
- **[`tech-local.md`](tech-local.md)** — 技术实现细节
- **[`architecture-local.md`](architecture-local.md)** — 11 进程拓扑 + 显存分配

## 🔧 子系统

- **[`jarvis-mode.md`](jarvis-mode.md)** — Jarvis 模式产品设计（状态机 + 唤醒 + 事件响应）
- **[`asr-streaming.md`](asr-streaming.md)** — KWS + 流式 ASR 实现（sherpa-onnx）
- **[`screen-capture.md`](screen-capture.md)** — getDisplayMedia 屏幕捕获
- **[`hermes-integration.md`](hermes-integration.md)** — Hermes-agent 严格隔离集成
- **[`voice-clone.md`](voice-clone.md)** — CosyVoice3 零样本克隆
- **[`memory-architecture.md`](memory-architecture.md)** — 可插拔记忆架构（**embedding API 化见 api-optimization.md §3.5**）

## 🛠 维护工具

- **[`../services/scripts/README.md`](../services/scripts/README.md)** — 改代码后必跑 [`sync-docs.py`](../services/scripts/sync-docs.py)（自动追加 DELIVERY + 路线图状态）；其他 helper 见子目录列表
- **[`../stop-joyai.ps1`](../stop-joyai.ps1)** — 一键停全部 12 服务，替代任务管理器
- **[`../start-joyai.ps1`](../start-joyai.ps1)** — 薄包装 run-windows.ps1

## 📦 交付与历史


## 📐 架构决策记录（ADR）

- **[`adr/0001-voice-clone-sync.md`](adr/0001-voice-clone-sync.md)** — Rapid Clone 同步路径 vs `/v1/t2a_async_v2`（结论：保持同步）
- **[`adr/0002-kws-config-env.md`](adr/0002-kws-config-env.md)** — KWS 调参改 env 化
- **[`adr/0003-llm-reply-panel.md`](adr/0003-llm-reply-panel.md)** — LLM 回复面板可见性
- **[`adr/0004-service-lifecycle.md`](adr/0004-service-lifecycle.md)** — 服务停止方案
- **[`glossary.md`](glossary.md)** — BT 语音交互栈术语表
- **[`../DELIVERY.md`](../DELIVERY.md)** — 变更记录 + 复盘决策
- **[`gaming-mode.md`](gaming-mode.md)** — 旧名"游戏模式"使用指南
- **[`deprecated/`](deprecated/)** — 上游残留（已弃用，勿读）

## 🗂️ 文档清单

| 路径 | 大小 | 类型 | 状态 |
|---|---:|---|---|
| `README.md` | 本文件 | 索引 | ✅ |
| `00-main-direction.md` | ~5 KB | 主方向 | ✅ |
| `api-optimization.md` | ~25 KB | 主路径核心 | ✅ 升级中 |
| `token-plan-comparison.md` | ~19 KB | 调研 | ✅ |
| `lightweight-replacement.md` | ~28 KB | 调研 | ✅ |
| `pm-local.md` | ~36 KB | 本地化 | ⚠️ 顶部加降级说明 |
| `tech-local.md` | ~45 KB | 本地化 | ⚠️ 顶部加降级说明 |
| `architecture-local.md` | ~8 KB | 本地化 | ⚠️ 顶部加降级说明 |
| `jarvis-mode.md` | ~28 KB | 子系统 | ✅ |
| `asr-streaming.md` | ~13 KB | 子系统 | ✅ |
| `screen-capture.md` | ~9 KB | 子系统 | ✅ |
| `hermes-integration.md` | ~10 KB | 子系统 | ✅ |
| `voice-clone.md` | ~9 KB | 子系统 | ⚠️ 抽出 §9 |
| `memory-architecture.md` | ~12 KB | 子系统 | ⚠️ 抽出 §4 部分 |
| `gaming-mode.md` | ~6 KB | 使用指南 | ✅ |
| `../DELIVERY.md` | ~23 KB | 变更记录 | ✅ |
| `deprecated/*` | ~30 KB | 已弃用 | ⚠️ 顶部加弃用说明 |

---

## 🔗 项目根目录结构

```
JoyAI-VL-Interaction-main/
├── README.md
├── DELIVERY.md
├── doc/                 # 本目录
├── services/            # 7 个微服务（webinfer / asr / tts / voice-clone / webui / background-agent / common）
├── install/             # 安装脚本（install-windows.ps1 / setup-*.ps1）
├── prompts/             # 角色 prompt 模板
├── voices/              # 声音档案（运行时生成）
├── datasets/            # 训练数据转换工具（运行时不需要）
└── img/                 # README 资源
```

---

> 文档版本：v3.2 配套  |  最近更新：2026-07-09  |  作者：Codex