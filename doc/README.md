# JoyAI-VL-Interaction 文档库

> **版本**: v3.37 配套 | **最近更新**: 2026-07-13 | **状态**: ✅ 与代码同步
>
> **如何读这页**：新人先按 👇 入口路径走（35 分钟入门）。需要查特定子系统的设计/规格/决策时，按"分类索引"找。历史文档 `deprecated/` 不进常规阅读路径。
>
> **关键文档（最常被读到）**：
> - 📌 [`specs/2026-07-13-current-state.md`](specs/2026-07-13-current-state.md) — **项目现状唯一权威**（端口、模块流程、风险表）
> - 📌 [`specs/2026-07-13-llm-path-consolidation.md`](specs/2026-07-13-llm-path-consolidation.md) — LLM 网关单入口（B 选项实施合同，已 ✅ 实施）
> - 📌 [`adr/0006-llm-gateway-single-entrypoint.md`](adr/0006-llm-gateway-single-entrypoint.md) — v3.37 设计决策

---

## 🎯 入口路径（新人在此起步）

1. **[`main/00-main-direction.md`](main/00-main-direction.md)** — 主方向 + v3.37 路线图（**先读这个**）
2. **[`specs/2026-07-13-current-state.md`](specs/2026-07-13-current-state.md)** — 项目现状快照（端口、模块、风险）
3. **[`glossary.md`](glossary.md)** — BT 语音交互栈术语表
4. 按需要展开到子系统 / ADR / Spec —— 见下方分类索引

---

## 📚 分类索引

### 主方向（1 份）

| 文档 | 用途 |
| --- | --- |
| [`main/00-main-direction.md`](main/00-main-direction.md) | 项目主方向 + 路线图 |

### API 化主路径（2 份）

| 文档 | 用途 |
| --- | --- |
| [`api/api-optimization.md`](api/api-optimization.md) | API 化方案（主路径核心，~40 KB） |
| [`api/token-plan-comparison.md`](api/token-plan-comparison.md) | 8 家厂商 Token Plan 调研（MiniMax 推荐） |

### 本地化降级方案（3 份）

> **降级方案**：API 路径不可用时的本地兜底。**默认走 API 路径**，看这三个时确认自己真的在本地化部署。

| 文档 | 用途 |
| --- | --- |
| [`local/pm-local.md`](local/pm-local.md) | PM 视角的本地化方案 |
| [`local/tech-local.md`](local/tech-local.md) | 技术实现细节 |
| [`local/architecture-local.md`](local/architecture-local.md) | 11 进程拓扑 + 显存分配 |

### 调研 / 选型（2 份）

| 文档 | 用途 |
| --- | --- |
| [`research/memory-store-research.md`](research/memory-store-research.md) | 持久化层选型 |
| [`research/lightweight-replacement.md`](research/lightweight-replacement.md) | 硬件选型（GGUF / 摘要 / ASR / TTS） |

### 子系统设计（8 份）

> 按模块拆分的设计文档。改某个模块前先读对应文件。

| 文档 | 模块 |
| --- | --- |
| [`subsystems/jarvis-mode.md`](subsystems/jarvis-mode.md) | **Jarvis 模式**（状态机 + 唤醒 + 事件响应，~60 KB 最大文件） |
| [`subsystems/asr-streaming.md`](subsystems/asr-streaming.md) | KWS + 流式 ASR（sherpa-onnx） |
| [`subsystems/screen-capture.md`](subsystems/screen-capture.md) | getDisplayMedia 屏幕捕获 |
| [`subsystems/hermes-integration.md`](subsystems/hermes-integration.md) | Hermes-agent 严格隔离集成 |
| [`subsystems/voice-clone.md`](subsystems/voice-clone.md) | CosyVoice3 零样本克隆 |
| [`subsystems/voice-ui.md`](subsystems/voice-ui.md) | 浏览器语音交互界面 |
| [`subsystems/memory-architecture.md`](subsystems/memory-architecture.md) | 可插拔记忆架构（embedding API 化见 api/api-optimization.md §3.5） |
| [`subsystems/gaming-mode.md`](subsystems/gaming-mode.md) | 旧名"游戏模式"使用指南 |

### 专题 Spec（`specs/`）

> **活跃 spec**：每次变更/上线都要新建/更新对应专题。命名规范 `YYYY-MM-DD-{topic}.md`。

| Spec | 状态 | 用途 |
| --- | --- | --- |
| [`specs/2026-07-13-current-state.md`](specs/2026-07-13-current-state.md) | ✅ 唯一现状权威 | 端口 / 模块流程 / 风险表 |
| [`specs/2026-07-13-llm-path-consolidation.md`](specs/2026-07-13-llm-path-consolidation.md) | ✅ 已实施 | B 选项实施合同 |
| [`specs/hybrid-wake-confirm.md`](specs/hybrid-wake-confirm.md) | ✅ 已实施 | 混合唤醒确认窗口 |
| [`specs/kws-recall-optimization.md`](specs/kws-recall-optimization.md) | ✅ 已实施 | KWS 召回优化 |
| [`specs/memory-store-skeleton-spec.md`](specs/memory-store-skeleton-spec.md) | ✅ 已实施 | 持久化层骨架 |
| [`specs/webui-asr-input-state.md`](specs/webui-asr-input-state.md) | ✅ 已实施 | WebUI ASR 状态机 |
| [`specs/webui-kws-listening-chain.md`](specs/webui-kws-listening-chain.md) | ✅ 已实施 | WebUI KWS 监听链 |

### 架构决策记录（`adr/`）

> "为什么这么改"——决策历史。

| ADR | 主题 |
| --- | --- |
| [`adr/0001-voice-clone-sync.md`](adr/0001-voice-clone-sync.md) | Rapid Clone 同步路径 vs `/v1/t2a_async_v2` |
| [`adr/0002-kws-config-env.md`](adr/0002-kws-config-env.md) | KWS 调参改 env 化 |
| [`adr/0003-llm-reply-panel.md`](adr/0003-llm-reply-panel.md) | LLM 回复面板可见性 |
| [`adr/0004-service-lifecycle.md`](adr/0004-service-lifecycle.md) | 服务停止方案 |
| [`adr/0005-memory-store-start.md`](adr/0005-memory-store-start.md) | 持久化层启动策略 |
| [`adr/0006-llm-gateway-single-entrypoint.md`](adr/0006-llm-gateway-single-entrypoint.md) | LLM 网关单入口（v3.37） |

### 工具书

| 文档 | 用途 |
| --- | --- |
| [`glossary.md`](glossary.md) | BT 语音交互栈术语表 |

### 维护工具（跨目录引用）

- [`../services/scripts/README.md`](../services/scripts/README.md) — 改代码后必跑 [`sync-docs.py`](../services/scripts/sync-docs.py)
- [`../stop-joyai.ps1`](../stop-joyai.ps1) — 一键停全部服务
- [`../start-joyai.ps1`](../start-joyai.ps1) — 薄包装 `run-windows.ps1`
- [`../DELIVERY.md`](../DELIVERY.md) — 变更记录 + 复盘决策

### 已弃用（不进常规阅读路径）

| 目录 | 说明 |
| --- | --- |
| [`deprecated/`](deprecated/) | 历史文档快照（详见 `deprecated/README.md` 的处置规则；不要据此实施） |

---

## 🔗 项目根目录结构

```
JoyAI-VL-Interaction-main/
├── README.md
├── DELIVERY.md
├── doc/                 # 本目录
├── services/            # webinfer / asr / tts / voice-clone / webui / background-agent / common
├── install/             # 安装脚本
├── prompts/             # 角色 prompt 模板
├── voices/              # 声音档案（运行时生成）
├── datasets/            # 训练数据转换工具（运行时不需要）
└── img/                 # README 资源
```

---

## 📋 文档维护规则

1. **改代码 → 改 spec**：`specs/2026-07-13-current-state.md` 是基线，端口/模块变更必须同步。
2. **新增专题 → 新建 spec**：写 `specs/YYYY-MM-DD-{topic}.md`，状态用 `✅ 已实施 / 🟡 进行中 / ⚪ 观察项 / ⚫ 弃用`。
3. **设计决策 → 新建 ADR**：顺序编号 `adr/NNNN-{title}.md`，状态 `Accepted / Superseded / Deprecated`。
4. **过 6 个月无引用 → 候选弃用**：先 `deprecated/`，6 个月再未引用 → 删除。
5. **`doc/README.md`（本文件）必须反映最新分类布局**——加新文件时同步更新。
