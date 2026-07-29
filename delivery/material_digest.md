# JoyAI-VL-Interaction - 资料摘要 v0.1

> 本文档做一件事：**精读主理人转交的全部原始资料，逐份、逐章节做出摘要**——后面任何人拿到这份摘要，都能通过章节号快速定位回原始文件的对应位置。

> 上游输入：主理人转交的全部原始资料（需求文档 + 已有架构文档，含 md 与 1 份 pdf）；
> 产出者：`knowledge-ingest-engineer`（知识摄入工程师 - 闻资料），经 G1 校验与人工审核通过后交付。
> 角色边界：本摘要**仅做资料归一化**，不做任何业务/技术判断、不下架构结论、不裁决冲突。冲突一律并列保留（见 §3）。

---

## 0. 元信息

```yaml
标题: JoyAI-VL-Interaction - 资料摘要 v0.1
版本: v0.1
状态: Draft
创建日期: 2026-07-20
整理人: knowledge-ingest-engineer (闻资料)
审核人:
  - 主理人 (待 G1 人工审核)

原始资料清单:
  - README.md: 项目根需求/概览（英文）
  - README.zh-CN.md: 项目根需求/概览（中文，含 Windows 本地部署）
  - doc/main/00-main-direction.md: 主方向 v3.2 路线图
  - doc/local/architecture-current.md: 当前运行架构基线 (HEAD=021f429)
  - doc/adr/0001~0007: 7 份已拍板决策记录
  - doc/review-20260720-live-adapter-split.md: live_adapter 拆分评审
  - doc/specs/*: 9 份规格/快照/评审
  - doc/subsystems/*: 8 份子系统设计（jarvis-mode.md 解析失败）
  - doc/api/*: 2 份 API 化调研
  - services/*/README.md: 8 份服务 README（5 份空文档）
  - doc/local/architecture-local.md: Windows 本地化架构
  - doc/deprecated/architecture.md: 本地化前上游架构（弃用）
  - DELIVERY.md: 本地化交付清单
  - JoyAI-VL-Interaction-Reportv1.pdf: 技术报告（解析失败）
```

| 版本 | 日期 | 作者 | 变更内容 |
| --- | --- | --- | --- |
| v0.1 | 2026-07-20 | knowledge-ingest-engineer | 初稿：归一并摘要全部 43 份资料，标记冻结边界、后续架构缺口、架构完成度盘点 |

---

## 1. 资料清单

> 列出全部 43 份原始资料，每份标注解析状态。解析失败或跳过的必须注明原因。

| 编号 | 文件名 | 类型 | 来源 | 解析状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| D1 | `README.md` | md | 项目根（主理人转交） | 已解析 | 英文概览/需求 |
| D2 | `README.zh-CN.md` | md | 项目根（主理人转交） | 已解析 | 中文概览，含 Windows 本地部署入口 |
| D3 | `doc/main/00-main-direction.md` | md | 项目 doc/main（主理人转交） | 已解析 | 主方向 v3.2 路线图（P0） |
| D4 | `doc/local/architecture-current.md` | md | 项目 doc/local（主理人转交） | 已解析 | ★ 当前运行架构基线 (HEAD=021f429) |
| D5 | `doc/adr/0001-voice-clone-sync.md` | md | ADR 记录（主理人转交） | 已解析 | Accepted 2026-07-11，语音克隆同步路径，冻结 |
| D6 | `doc/adr/0002-kws-config-env.md` | md | ADR 记录（主理人转交） | 已解析 | KWS 参数→环境变量，冻结 |
| D7 | `doc/adr/0003-llm-reply-panel.md` | md | ADR 记录（主理人转交） | 已解析 | LLM 回复面板可见性，冻结 |
| D8 | `doc/adr/0004-service-lifecycle.md` | md | ADR 记录（主理人转交） | 已解析 | 服务生命周期/端口，冻结 |
| D9 | `doc/adr/0005-memory-store-start.md` | md | ADR 记录（主理人转交） | 已解析 | 记忆库边界决策，冻结 |
| D10 | `doc/adr/0006-llm-gateway-single-entrypoint.md` | md | ADR 记录（主理人转交） | 已解析 | LLM 单入口网关，冻结 |
| D11 | `doc/adr/0007-split-live-adapter.md` | md | ADR 记录（主理人转交） | 已解析 | live_adapter 模块拆分，Accepted 2026-07-20，冻结 |
| D12 | `doc/review-20260720-live-adapter-split.md` | md | 项目评审（主理人转交） | 已解析 | live_adapter 拆分评审，含 🔴 阻断级打包缺陷 |
| D13 | `doc/specs/2026-07-13-current-state.md` | md | 项目 specs（主理人转交） | 已解析 | v3.37 权威快照 |
| D14 | `doc/specs/2026-07-13-llm-path-consolidation.md` | md | 项目 specs（主理人转交） | 已解析 | LLM 路径收敛（Option B，已落地 v3.37） |
| D15 | `doc/specs/2026-07-14-loose-coupling-services.md` | md | 项目 specs（主理人转交） | 已解析 | 松耦合服务/4-API 配置/11 用户故事 |
| D16 | `doc/specs/2026-07-14-project-audit.md` | md | 项目 specs（主理人转交） | 已解析 | 代码事实审计 (HEAD=021f429)，10 项风险 |
| D17 | `doc/specs/hybrid-wake-confirm.md` | md | 项目 specs（主理人转交） | 已解析 | 混合唤醒确认状态机 |
| D18 | `doc/specs/kws-recall-optimization.md` | md | 项目 specs（主理人转交） | 已解析 | KWS 召回优化（v4 recall 49.06%） |
| D19 | `doc/specs/memory-store-skeleton-spec.md` | md | 项目 specs（主理人转交） | 已解析 | 记忆库骨架 v0.1 规格 |
| D20 | `doc/specs/webui-asr-input-state.md` | md | 项目 specs（主理人转交） | 已解析 | WebUI ASR 输入态修正 |
| D21 | `doc/specs/webui-kws-listening-chain.md` | md | 项目 specs（主理人转交） | 已解析 | WebUI KWS 常驻监听链路 |
| D22 | `doc/subsystems/asr-streaming.md` | md | 项目 subsystems（主理人转交） | 已解析 | 流式 ASR / KWS 子系统设计 |
| D23 | `doc/subsystems/gaming-mode.md` | md | 项目 subsystems（主理人转交） | 已解析 | Jarvis 游戏模式使用指南 |
| D24 | `doc/subsystems/hermes-integration.md` | md | 项目 subsystems（主理人转交） | 已解析 | Hermes 严格隔离集成 |
| D25 | `doc/subsystems/memory-architecture.md` | md | 项目 subsystems（主理人转交） | 已解析 | 三层进程内记忆架构 |
| D26 | `doc/subsystems/screen-capture.md` | md | 项目 subsystems（主理人转交） | 已解析 | 屏幕捕获 (getDisplayMedia) |
| D27 | `doc/subsystems/voice-clone.md` | md | 项目 subsystems（主理人转交） | 已解析 | MiniMax Rapid Clone 声音克隆 |
| D28 | `doc/subsystems/voice-ui.md` | md | 项目 subsystems（主理人转交） | 已解析 | WebUI 语音 HUD / 交互 |
| D29 | `doc/subsystems/jarvis-mode.md` | md | 项目 subsystems（主理人转交） | 解析失败 | Read 工具判定为二进制无法显示；内容仅能从交叉引用推断（见 §2 D29 与 §3 X6） |
| D30 | `doc/api/api-optimization.md` | md | 项目 api（主理人转交） | 已解析 | API 化主路径调研 |
| D31 | `doc/api/token-plan-comparison.md` | md | 项目 api（主理人转交） | 已解析 | 8 家套餐对比 |
| D32 | `services/webinfer/README.md` | md | 服务 README（主理人转交） | 已解析 | webinfer 适配器说明 |
| D33 | `services/webui/README.md` | md | 服务 README（主理人转交） | 已解析 | WebUI 说明 |
| D34 | `services/asr/README.md` | md | 服务 README（主理人转交） | 已解析 | ASR 适配器说明 |
| D35 | `services/tts/README.md` | md | 服务 README（主理人转交） | 已解析（空） | 文件当前无内容（空白文档），需下游补全 |
| D36 | `services/background-agent/README.md` | md | 服务 README（主理人转交） | 已解析（空） | 文件当前无内容（空白文档），需下游补全 |
| D37 | `services/voice-clone/README.md` | md | 服务 README（主理人转交） | 已解析（空） | 文件当前无内容（空白文档），需下游补全 |
| D38 | `services/kws-training/README.md` | md | 服务 README（主理人转交） | 已解析（空） | 文件当前无内容（空白文档），需下游补全 |
| D39 | `services/memory-store/README.md` | md | 服务 README（主理人转交） | 已解析（空） | 文件当前无内容（空白文档），需下游补全 |
| D40 | `doc/local/architecture-local.md` | md | 项目 doc/local（主理人转交） | 已解析 | Windows + RTX 5060 Ti 16GB 本地化架构 |
| D41 | `doc/deprecated/architecture.md` | md | 项目 doc/deprecated（主理人转交） | 已解析 | 本地化前上游架构（弃用，标注不符当前目标）；其引用的 `architecture.zh-CN.md` 不在本次转交清单内 |
| D42 | `DELIVERY.md` | md | 项目根（主理人转交） | 已解析 | 本地化交付清单（含 v1.0~v3.13 变更记录） |
| D43 | `JoyAI-VL-Interaction-Reportv1.pdf` | pdf | 主理人转交 | 解析失败 | 沙箱无法运行 PDF 提取工具（Bash/Python 执行不可用），Read 将该文件识别为二进制无法显示文本；建议主理人在可运行 pypdf/pdfplumber 的环境重新提取，或由人工提供文本 |

**类型枚举**：`docx` / `pdf` / `pptx` / `xlsx` / `md`（本项目资料以 md 为主，含 1 份 pdf）

---

## 2. 资料内容摘要

> 逐份文档按自身章节结构做摘要。每条摘要标注章节号（`D编号，§章节`）与引用方式（直接引用 / 数据提取 / 综合归纳 / 推断），后面任何人想核实某个点，直接定位回原文对应位置即可。

> **冻结 / 已拍板边界说明（按主理人注入要求标记）**：以下文档代表当前项目已冻结或已拍板的设计基线，下游不得自行更改：
> - `doc/local/architecture-current.md`（D4，HEAD=021f429 当前运行架构，★基线）
> - `doc/adr/0001` ~ `doc/adr/0007`（D5~D11，全部 Accepted 决策记录）
>
> 其余 specs / subsystems / api / service README / architecture-local / DELIVERY 为设计稿、快照或交付记录，可能随版本演进，下游引用时需核对版本号。

### D1：`README.md`

> 8B 开源实时视觉语言交互系统概览与需求 — 来源：项目根

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D1，§Overview | 8B 规模、全开源的实时视觉语言交互系统；核心模型 JoyAI-VL-8B 每秒自主决策 speak / stay silent / delegate；外围 5 个可插拔服务：inference(vLLM)、WebUI(WebRTC 流式)、ASR(Qwen3-ASR)、TTS(Qwen3-TTS)、background agent | 综合归纳 |
| D1，§Eval | 评测对比 Doubao（77.6%）/ Gemini（87.9%），覆盖 58 个场景 | 数据提取 |
| D1，§Dataset | 训练数据 4M 时间对齐片段，编码采用 AdaCodec | 数据提取 |
| D1，§Services | 五服务可插拔架构，每项可独立替换 | 综合归纳 |

### D2：`README.zh-CN.md`

> 中文概览，补充 Windows 本地轻量部署入口 — 来源：项目根

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D2，§Windows 部署 | 支持 Windows 本地轻量部署，目标 RTX 5060 Ti 16GB | 数据提取 |
| D2，§sync-docs | 提供 `sync-docs.py` 工作流同步文档 | 数据提取 |
| D2，其余 | 与 D1 英文版内容一致（概览/评测/服务） | 综合归纳 |

### D3：`doc/main/00-main-direction.md`

> 主方向 v3.2 路线图（P0 方向文档）— 来源：项目 doc/main

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D3，§1 方向 | 混合架构为主路径：本地 LLM/VLM + 本地 sherpa KWS/ASR + MiniMax TTS/克隆 | 综合归纳 |
| D3，§3 v3.2 路线图 | 6 项：(#1) API 化 P0 设计完成；(#2) MiniMax Token Plan 半落地；(#3) P2 记忆持久化 落地 v0.2；(#4) Jarvis 状态机 P1 设计完成；(#5) KWS 自训 已落地 v4；(#6) Codex fallback P2 文档完成 | 数据提取 |
| D3，§4.0 变更日志 | 详细变更日志至 v3.35a | 数据提取 |

### D4：`doc/local/architecture-current.md` ★

> **【冻结·当前架构基线 HEAD=021f429】** 当前运行架构 — 来源：项目 doc/local

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D4，§拓扑 | WebUI(8099) → webinfer(8070，单一主路径编排器) → llama-server(7060，JoyAI-VL-8B IQ4_NL + mmproj)。两条 LLM HTTP 入口：`POST /v1/text/chat`（纯文本，累积 qa_history，拒绝图像）与 `POST /v1/chat/completions`（多模态）；外加 `POST /v1/summarizer/route` 用于热切换 | 数据提取 |
| D4，§决策 token | 决策 token silence / response / delegate（精确字面量见 D4 源文件）由 webinfer 在送 TTS 前剥离；delegate 触发 BackgroundModelService → hermes(8079 shim → 8642 gateway) 委派 | 数据提取 |
| D4，§模块行数 | live_adapter.py 3179 行（后续按 ADR0007 拆分）、jarvis_mode.py 1126、background_model.py 1177、server.py 652、vlm_service.py 688、asr.py 455 等；约 24.9k Python + 约 9k JS | 数据提取 |
| D4，§Phase 2A/B/C | Phase 2A/B/C 提交清单（服务配置/采集模块/摘要路由） | 数据提取 |
| D4，§测试 | webui 107 + webinfer 66 = 173 测试全绿 | 数据提取 |

### D5：`doc/adr/0001-voice-clone-sync.md`

> **【冻结·Accepted 2026-07-11】** 语音克隆同步路径 — 来源：ADR 记录

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D5，§决策 | MiniMax Rapid Clone 走同步路径 `/v1/voice_clone`，**非**异步 `/v2/t2a_async_v2` | 数据提取 |
| D5，§凭证修正 | 凭证修正：`sk-cp-*` 可鉴权 get_voice / t2a_v2 | 数据提取 |

### D6：`doc/adr/0002-kws-config-env.md`

> **【冻结】** KWS 参数→环境变量 — 来源：ADR 记录

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D6，§映射 | KWS 4 参数→环境变量：JARVIS_KWS_SCORE(10.0)、JARVIS_KWS_THRESHOLD(0.25)、JARVIS_KWS_TRAILING_BLANKS(1)、JARVIS_KWS_MAX_ACTIVE_PATHS(10) | 数据提取 |
| D6，§模型目录 | 模型目录 bt-zai-ma → bt-en | 数据提取 |

### D7：`doc/adr/0003-llm-reply-panel.md`

> **【冻结】** LLM 回复面板可见性 — 来源：ADR 记录

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D7，§可见性 | LLM 回复面板可见：A CSS display:block ✅；B `/api/llm/status` ✅；C streaming delta ⚠️ 部分实现 | 数据提取 |

### D8：`doc/adr/0004-service-lifecycle.md`

> **【冻结】** 服务生命周期/端口 — 来源：ADR 记录

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D8，§stop 脚本 | stop-joyai.ps1 覆盖 12 个端口；默认启动计划现仅 7060/8070/8099/8985 | 数据提取 |
| D8，§进程内组件 | KWS/Paraformer 进程内；TTS 直连 MiniMax | 数据提取 |

### D9：`doc/adr/0005-memory-store-start.md`

> **【冻结】** 记忆库边界决策 — 来源：ADR 记录

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D9，§5 边界 | 5 项边界：A score/last_hit_at/hit_count 不计算；B 不引入 common/ httpx；C 不写 webinfer/background-agent 测试；D 三段 hooks 形状；E 端口 8996 + MEMORY_BACKEND 环境变量 | 数据提取 |
| D9，§后端 | v0.1 仅 sqlite；psql/obsidian 为 NotImplemented | 数据提取 |

### D10：`doc/adr/0006-llm-gateway-single-entrypoint.md`

> **【冻结】** LLM 单入口网关 — 来源：ADR 记录

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D10，§单入口 | v3.37 起所有 LLM 经由 webinfer 8070；webui 不直接连 7060。端点 `/v1/text/chat`（文本）+ `/v1/chat/completions`（多模态） | 数据提取 |
| D10，§SPOF | webinfer 成为新的单点故障；显式失败，不回退 7060 | 数据提取 |

### D11：`doc/adr/0007-split-live-adapter.md`

> **【冻结·Accepted 2026-07-20】** live_adapter 模块拆分 — 来源：ADR 记录

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D11，§拆分 | 将 3531 行 live_adapter.py 拆分为 9 个模块 + facade（53 行，纯 AST 机械拆分） | 数据提取 |
| D11，§目标布局 | adapter_types.py(195)、config.py(113)、prompt_building.py(238)、time_ranges.py(228)、response_format.py(296)、io_utils.py(239)、request_parsing.py(237)、adapter_core.py(1992)、app.py(608) | 数据提取 |
| D11，§里程碑 | Milestone 1 完成（66 通过）；Milestone 2/3 待办 | 数据提取 |

### D12：`doc/review-20260720-live-adapter-split.md`

> live_adapter 拆分评审（含阻断级缺陷）— 来源：项目评审

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D12，§阻断缺陷 | 🔴 BLOCKING：pyproject.toml:58 `py-modules` 仅列出 13 个模块中的 3 个（缺失 adapter_core、adapter_types、app、config、io_utils、live_adapter、memory_store_client、prompt_building、request_parsing、response_format、time_ranges）；修复=补齐全部 13 个或删除该键 | 数据提取 |
| D12，§评审摘要 | 5 角色评审摘要；Milestone 2 优先级：P0(#2 决策解析统一、#4 并发竞态、#3 常量收敛) | 数据提取 |

### D13：`doc/specs/2026-07-13-current-state.md`

> v3.37 权威快照 — 来源：项目 specs

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D13，§拓扑 | WebUI 8099 → webinfer 8070 → llama 7060 单物理主干，HTTP 路由分叉 | 数据提取 |
| D13，§6 风险 | 风险：e2e 测试挂起(3)、文档漂移、webinfer 新 SPOF、静默回归风险、`_background_service` 惰性绑定、VLMService.api_base 全局、qa_history 非对称写入、配置双路径、stream 未实现 | 数据提取 |

### D14：`doc/specs/2026-07-13-llm-path-consolidation.md`

> LLM 路径收敛（Option B，已落地 v3.37）— 来源：项目 specs

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D14，§实现 | ✅ 已落地 v3.37（Option B） | 数据提取 |
| D14，§端点契约 | `/v1/text/chat` 契约：收到 image_url 返回 400；streamingharness.decision 取值 | 数据提取 |
| D14，§失败回退 | webinfer 不可达 = 显式失败，无 7060 回退 | 数据提取 |

### D15：`doc/specs/2026-07-14-loose-coupling-services.md`

> 松耦合服务/4-API 配置/11 用户故事 — 来源：项目 specs

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D15，§主路径 | 单一 webinfer 主路径；4-API 配置；3 个独立采集模块 | 数据提取 |
| D15，§Phase 2B | Phase 2B 摘要路由 | 数据提取 |
| D15，§用户故事 | 11 个用户故事 | 数据提取 |
| D15，§ADR 决策 | 列出值得记为 ADR 的决策 | 数据提取 |

### D16：`doc/specs/2026-07-14-project-audit.md`

> 代码事实审计 (HEAD=021f429) — 来源：项目 specs

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D16，§3 风险表 | 10 项风险：#1 4-API 配置传播不一致；#2 webinfer 绑定 llama-server URL 不可热切换；#5 `/api/rtsp/start` 501 桩；等 | 数据提取 |
| D16，§4 三版本对比 | v3.26 → v3.37 → v3.38 三版本对比 | 数据提取 |

### D17：`doc/specs/hybrid-wake-confirm.md`

> 混合唤醒确认状态机 — 来源：项目 specs

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D17，§状态 | WAIT_ASR_CONFIRM 状态；asr_confirm_timeout_s(1.2) | 数据提取 |
| D17，§演进 | v3.18 预热引擎；v3.19 内联 ASR 抽头 | 数据提取 |

### D18：`doc/specs/kws-recall-optimization.md`

> KWS 召回优化 — 来源：项目 specs

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D18，§召回 | KWS v4 recall 49.06% | 数据提取 |
| D18，§方法 | 滚动 PCM 采集；ASR 影子诊断；sweep 结果表 | 数据提取 |

### D19：`doc/specs/memory-store-skeleton-spec.md`

> 记忆库骨架 v0.1 规格 — 来源：项目 specs

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D19，§D-1~D-9 | 服务、路由、数据模型 MemoryBlock、Backend Protocol、SqliteBackend FTS5、占位实现、测试、配置、hook 接口 | 数据提取 |
| D19，§范围外 | 超出范围：embedding / psql / obsidian / webui | 数据提取 |

### D20：`doc/specs/webui-asr-input-state.md`

> WebUI ASR 输入态修正 — 来源：项目 specs

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D20，§入口 | 麦克风 ASR 测试入口；纸飞机单一发送 | 数据提取 |
| D20，§清洗 | 清洗控制 token；延迟 HUD 扩展 | 数据提取 |

### D21：`doc/specs/webui-kws-listening-chain.md`

> WebUI KWS 常驻监听链路 — 来源：项目 specs

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D21，§监听按钮 | 专用 BT 监听按钮；WebRTC audio-only `/offer` | 数据提取 |
| D21，§徽章 | KWS_LISTENING / WAKE_DETECTED / DIALOG_ACTIVE 徽章 | 数据提取 |

### D22：`doc/subsystems/asr-streaming.md`

> 流式 ASR / KWS 子系统设计 — 来源：项目 subsystems

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D22，§KWS | KWS sherpa-onnx（56MB 编码器，FAR 2% / recall 49%） | 数据提取 |
| D22，§Paraformer | Paraformer int8（首 token 200-400ms）；EXIT_WORDS | 数据提取 |
| D22，§调参 | 调参参数 rule1_min_trailing_silence=2.0、chunk_size_ms=30 | 数据提取 |
| D22，§性能 | 性能表：e2e 0.8-1.5s | 数据提取 |

### D23：`doc/subsystems/gaming-mode.md`

> Jarvis 游戏模式使用指南 — 来源：项目 subsystems

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D23，§指南 | Jarvis 用法指南；BT-7274 人格 | 数据提取 |
| D23，§性能 | KWS/ASR/TTS 性能 | 数据提取 |
| D23，§模式 | 3 种模式：Jarvis / Always-on / Push-to-talk | 数据提取 |

### D24：`doc/subsystems/hermes-integration.md`

> Hermes 严格隔离集成 — 来源：项目 subsystems

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D24，§隔离 | Hermes 严格隔离工具层；shim 仅做 `/v1/solve` 协议转换 | 数据提取 |
| D24，§独立性 | 人格/记忆/Skills/Provider 独立 | 数据提取 |
| D24，§闭环 | v3.28 闭环委派 | 数据提取 |

### D25：`doc/subsystems/memory-architecture.md`

> 三层进程内记忆架构 — 来源：项目 subsystems

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D25，§三层 | L0 短期 20 / L1 中期 / L2 长期；无持久化 | 数据提取 |
| D25，§memory-store | memory-store 端口 8996；push/pull 对称 | 数据提取 |
| D25，§后端 | bge-m3 embedding 规划中；psql/sqlite/obsidian 后端 | 数据提取 |

### D26：`doc/subsystems/screen-capture.md`

> 屏幕捕获 (getDisplayMedia) — 来源：项目 subsystems

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D26，§方案 | getDisplayMedia（window，1fps，无音频） | 数据提取 |
| D26，§演进 | v3.27 端到端；v3.33 本地预览；v3.33.1 修复；v3.34 502 修复（ctx 4096→16384 + prompt guard） | 数据提取 |

### D27：`doc/subsystems/voice-clone.md`

> MiniMax Rapid Clone 声音克隆 — 来源：项目 subsystems

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D27，§方案 | 仅 MiniMax Rapid Clone（speech-2.8-hd）；10s 参考音频；¥9.9/voice；7 天过期；prompt_audio 可选 | 数据提取 |
| D27，§15.9 当前配置 | GROUP_ID=<your_minimax_group_id>，voice_id minimax_man_33333 | 数据提取 |
| D27，§删除 | CosyVoice3 于 2026-07-12 删除 | 数据提取 |

### D28：`doc/subsystems/voice-ui.md`

> WebUI 语音 HUD / 交互 — 来源：项目 subsystems

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D28，§HUD | WebUI HUD 徽章（jarvisStatus/llmBadge/ttsBadge/kwsBadge/jarvisExtra）、主题 | 数据提取 |
| D28，§演进 | Screen Capture tab 行为 v3.33；Paper-Plane 多模态 v3.35 | 数据提取 |

### D29：`doc/subsystems/jarvis-mode.md`

> **【解析失败】** Jarvis 模式设计（权威源文件不可读）— 来源：项目 subsystems

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D29，§（文件不可读） | 该文件被 Read 工具判定为二进制无法显示，无法逐章节解析其真实内容。多处文档将其作为 Jarvis 设计权威来源引用（gaming-mode/asr-streaming/00-main-direction/hermes-integration/specs 引用 §2.4、§6、§13、§14、§14.2、§14.11）。以下为从交叉引用**推断**的内容（风险：未经源文件核验）：BT-7274 人格；唤醒词 "bt 在吗"；KWS sherpa-onnx v4（FAR 2% / recall 49%）；EXIT_WORDS {行,明白,了解,ok,好的}；WAIT_ASR_CONFIRM 混合确认；Jarvis 状态机 | 推断（风险：源文件不可读，内容仅交叉引用重构） |

### D30：`doc/api/api-optimization.md`

> API 化主路径调研 — 来源：项目 api

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D30，§主路径 | API 化主路径；逐模块选型 | 数据提取 |
| D30，§三档 | 3 档（全本地 / TTS+克隆上云 / 全云）；推荐 MiniMax Token Plan | 数据提取 |
| D30，§端点表 | API 端点表 | 数据提取 |

### D31：`doc/api/token-plan-comparison.md`

> 8 家套餐对比 — 来源：项目 api

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D31，§对比 | 8 家厂商对比；MiniMax Token Plan 唯一"全包"（LLM+Agent+TTS+ASR+视觉+克隆+音乐+视频） | 数据提取 |
| D31，§档位 | 档位 Plus ¥49 / Max ¥119 / Ultra ¥469 | 数据提取 |

### D32：`services/webinfer/README.md`

> webinfer 适配器说明 — 来源：服务 README

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D32，§端点 | 适配器 8070，OpenAI 兼容，无 WS/音频；端点 /health、/v1/models、/v1/chat/completions、/v1/streaming/reset、/v1/prompts/active\|reload | 数据提取 |
| D32，§端口 | 端口 7060 主 / 8065 摘要 | 数据提取 |
| D32，§角色 | character_profile 角色 prompt 块 + 决策 token；关键参数 CHUNK=100、COMPRESS_EVERY_N_CHUNKS=5 | 数据提取 |

### D33：`services/webui/README.md`

> WebUI 说明 — 来源：服务 README

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D33，§说明 | WebUI 8099，后端 8070/v1，Python 3.12，证书自签 | 数据提取 |

### D34：`services/asr/README.md`

> ASR 适配器说明 — 来源：服务 README

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D34，§链路 | ASR 适配器接收 pcm16 → WAV → vLLM `/v1/audio/transcriptions` | 数据提取 |
| D34，§端口 | Qwen3-ASR-1.7B 端口 8993/8994；ws://127.0.0.1:8994/ws/asr | 数据提取 |

### D35~D39：services 空白 README

> 5 份服务 README 当前为空白文档 — 来源：服务 README

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D35，services/tts/README.md | 文件当前无内容（空白），需下游补全 | 数据提取 |
| D36，services/background-agent/README.md | 文件当前无内容（空白），需下游补全 | 数据提取 |
| D37，services/voice-clone/README.md | 文件当前无内容（空白），需下游补全 | 数据提取 |
| D38，services/kws-training/README.md | 文件当前无内容（空白），需下游补全 | 数据提取 |
| D39，services/memory-store/README.md | 文件当前无内容（空白），需下游补全 | 数据提取 |

### D40：`doc/local/architecture-local.md`

> Windows + RTX 5060 Ti 16GB 本地化架构 — 来源：项目 doc/local

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D40，§0 现行拓扑 | 现行运行拓扑（2026-07-12）：7060 社区量化 JoyAI llama-server + 8070 webinfer + 8099 WebUI + 8985 MiniMax voice-clone/TTS；WebUI 视频/VLM 经 webinfer；Jarvis 文本/语音为降延迟直接调同一 7060；KWS/ASR 在 WebUI 进程内用 sherpa-onnx。11 进程/CosyVoice 8991/TTS adapter 8992/whisper 8993/ASR adapter 8994 为早期本地化历史设计，**非**当前启动计划。唯一启动入口 `start-joyai.ps1 -Mode default` | 数据提取 |
| D40，§1 系统拓扑 | mermaid 拓扑：Windows 11 + RTX 5060 Ti 16GB，进程组1(编排层 WebUI/webinfer/tts_adapter/asr_adapter)、进程组2(推理层 llama main/summary/whisper/Cosy)、进程组3(新增 voice_clone/hermes gateway/shim)、Hermes 200+ providers | 数据提取 |
| D40，§2 数据流 | 一帧视频完整路径：WebRTC → WebUI → POST /v1/chat/completions → webinfer 注入角色 prompt → llama main 返回决策 token；response 走 voice_clone/Cosy TTS；delegate 走 hermes shim→gateway→provider；每 100 帧中期摘要 | 数据提取 |
| D40，§3 进程组 | 11 进程表（llama main 5.8GB / summary 2.9GB / whisper 0.7GB / Cosy 1.1GB / voice_clone 0.2GB / hermes gw 0.2GB / shim 0.15GB / webinfer 0.1GB / tts_adapter 0.08GB / asr_adapter 0.08GB / WebUI 0.15GB），合计 ~11.5GB，留 4.5GB 给游戏 | 数据提取 |
| D40，§4 启动顺序 | 依赖链：voice_clone_api→CosyVoice3；tts_adapter→voice_clone_api 或 Cosy；webinfer→llama main+summary；hermes shim→gateway；WebUI→webinfer+tts+asr+shim | 数据提取 |
| D40，§5 文件分布 | D:\AI\ 下 workspace/models/bin/tools 分布 | 数据提取 |
| D40，§6 差异 | 与原架构差异：主对话后端 vLLM→llama-server；摘要 vLLM→llama-server；ASR vLLM→whisper.cpp；TTS vLLM-Omni→CosyVoice3；Agent Codex→Hermes HTTP；新增角色 prompt 注入；声音固定→零样本克隆；总进程 8→11；GPU 3 张→1 张；显存峰值 ~70GB→~11.5GB | 数据提取 |
| D40，§7 不变性 | 接口契约不变：webui 端零修改；OpenAI 兼容；Pydantic 字段一致（SolveRequest/Response/FrameInput） | 数据提取 |
| D40，§8 故障域 | llama-server main 挂=全瘫（唯一 SPOF，监控+自动重启）；hermes 挂=委派失败主对话正常；CosyVoice 挂=TTS 失败可显文字；whisper 挂=无语音输入可文字；summary 挂=无长期记忆主对话正常；webui 挂=用户看不到 | 数据提取 |

### D41：`doc/deprecated/architecture.md`

> **【弃用·本地化前上游架构】** 与当前 Windows+RTX 5060 Ti 目标不符 — 来源：项目 doc/deprecated

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D41，§Overview | 实时视频语言交互系统，围绕视觉语言交互模型；五服务以 WebUI 为中心 hub-and-spoke | 数据提取 |
| D41，§组件职责 | 服务表：webinfer(必需,实时视频推理 OpenAI 兼容 HTTP)、webui(必需)、asr(可选,接收 pcm16 经 vLLM Qwen3-ASR 转写)、tts(可选,经 vLLM-Omni Qwen3-TTS)、background-agent(可选,代码执行 LLM agent) | 数据提取 |
| D41，§数据流 | 6 步：视频输入(webcam/RTSP ~1fps)→推理→决策输出(silence/response/delegate)→记忆(chunk→summary→长期)→语音 I/O(可选)→委派(可选) | 数据提取 |
| D41，§端口表 | 8070 webinfer / 7060 main vLLM / 8065 summary vLLM / 8099 webui / 8994 asr adapter / 8993 asr vLLM / 8992 tts adapter / 8991 tts vLLM-Omni / 8079 background-agent | 数据提取 |
| D41，§GPU 分配 | 默认 3 GPU：GPU0 主模型 0.9 / GPU1 摘要 0.9 / GPU2 ASR 0.3 + TTS 0.6；ASR_GPU=2、TTS_GPU=2 | 数据提取 |
| D41，§入口 | run.sh/stop.sh（Linux，多卡）；各服务 scripts/run.sh | 数据提取 |

### D42：`DELIVERY.md`

> 本地化交付清单（含 v1.0~v3.13 变更记录）— 来源：项目根

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D42，§0 历史快照 | 本文主体记录 2026-07-06 初版 11 进程/CosyVoice 方案，**非**当前启动规范；当前链路（2026-07-12）：7060 本地社区量化 LLM/VLM + 8070 webinfer + 8099 WebUI + 8985 MiniMax TTS/声音克隆；KWS/ASR 在 WebUI 内本地运行 | 数据提取 |
| D42，§1 完成项 | 15 项完成（GGUF 调研、声音克隆、Hermes 接入、角色 prompt 注入、shim、声音克隆服务、ASR/TTS 适配器、Windows 部署脚本、PM/技术/架构/游戏/声音克隆文档、README 引导） | 数据提取 |
| D42，§2 文件清单 | 新增（prompts/、webinfer/system_prompts.py、hermes_api/main.py、voice_clone_api/、install/*.ps1、services/scripts/*.ps1、doc/*）；修改（README.zh-CN、live_adapter.py +200 行、tts_adapter.py 428→564、asr_adapter.py）；不变（webui 零修改、codex_api 保留、*.sh 保留、决策 token 解析逻辑） | 数据提取 |
| D42，§3 启动序列 | 从零到对话：winget 装依赖→clone→install-windows.ps1→download-gguf-models→setup-*.ps1→填 env→填角色 prompt→run-windows.ps1 -Mode gaming→浏览器 8099 | 数据提取 |
| D42，§4 验收 | 用户原始需求逐项满足（Windows 5060Ti、GGUF 主模型、可替换模型、角色 prompt、声音克隆、Hermes、轻量本地、游戏对话、保留一体化结构、PM/技术文档） | 数据提取 |
| D42，§5 风险回退 | llama.cpp sm_120 不稳→官方 bin；CosyVoice3 装失败→CosyVoice2/F5/GPT-SoVITS；Hermes beta bug→切 codex_api；显存爆→关服务；PyTorch cu128 失败→仅 llama-server+whisper.cpp；克隆差→多录/换模型 | 数据提取 |
| D42，§7 变更记录 | v1.0(2026-07-06 本地化首发)；v3.3(2026-07-12 MiniMax Token Plan 半落地，声音克隆 speech-2.8-hd+voice_id minimax_man_33333 跑通，jarvis_mode.py 结构修复；未消除：un-windows.env 凭证未沉淀/v3.2#2 收尾未做/v3.2#4 全链路 e2e ⚠️)；v3.4(放弃 voice-ui 薄壳，改 webui 索引，删重复块，新增 /api/tts/synthesize 代理，17/17 测试绿)；v3.24(Jarvis 短期上下文+MiniMax-only+7060/8070/8099/8985 统一启动)；v3.25(memory-store v0.1 skeleton 落地，16/16 测试，JOYAI_ENABLE_MEMORY_STORE=1 默认 false；前端 vlm-history CSS 修复；webui 测试 79/79)；v3.27(屏幕捕获接入+hermes 端到端，79/79 webui 测试，模拟帧 ~5.5s 拿回复；gateway 8642+shim 8079 接入，smoke /v1/solve 返回中文) | 数据提取 |
| D42，§8 复盘补充 | P1 ASR 流式化（未实现，已设计，doc/asr-streaming.md，~350 行 Python+150 行 PS）；P2 可插拔记忆库（未实现，已设计，doc/memory-architecture.md，~500 行 Python+100 行 PS）；webinfer 可移植性复盘 90%→100% 跨平台修正；新增风险（ASR 离线延迟、无持久化记忆、无 RAG）；决策项总清单（PM 自填） | 数据提取 |
| D42，§10 API 化 | v2.0：档2 语音上云（ASR 阿里云 ¥86+TTS 火山 ¥45+克隆 ¥0-20+本地 VLM 0=¥120-150/月）；收益 ASR 1.5-7s→0.5-1s、TTS 冷启动 5-8s→300ms 以内、释放 1.8GB 显存、CER 6%→3%；不变：webui 零修改、本地作 fallback、主对话 VLM 永远本地；~3 人天；路线图 P1-API 语音上云(设计完成待实施)、P2 记忆库、P2-API 摘要云端、P3 声音克隆云端 | 数据提取 |
| D42，§12 套餐调研 | MiniMax Token Plan 唯一全包，推荐 Max ¥119+阿里云 ASR ¥30=¥149/月；8 家对比（阿里百炼/火山方舟/腾讯云/智谱/ ChatGPT/Claude/Gemini/Grok 均无全包或缺失 TTS/ASR） | 数据提取 |
| D42，§14 Jarvis 模式 | v3.0：触发由持续 ASR→唤醒词 "bt 在吗"；ASR whisper.cpp→sherpa-onnx 流式 0.5-1.5s；退出 EXIT_WORDS 立即；打断 Barge-in；预录 wake/goodbye/error wav；BT-7274 声线(MiniMax Speech 2.8/本地 Cosy)；已拍板：唤醒词/KWS sherpa-onnx/对话期 ASR sherpa-onnx/EXIT_WORDS/静默兜底 5s/MiniMax 预留/错误日志仅后台/每次新 logs | 数据提取 |
| D42，§16 屏幕捕获+Hermes 隔离 | v3.1：屏幕捕获 getDisplayMedia（displaySurface window, 1fps, audio false, 0 后端改动, 100ms 以内, ~200KB/s, 强制只选窗口）；Hermes 严格隔离（人格/记忆/Skills/Provider 独立，shim 不传 system，调用更快/故障隔离/升级独立/人格纯粹） | 数据提取 |
| D42，§18~§25 WebUI 修正 | v3.6(WebUI 链路测试修正，20/20 测试)；v3.7(对话可观测性，jarvis_dialog 历史类型，24/24)；v3.8(ASR 输入缓存修正，25/25)；v3.9(单一发送入口纸飞机，26/26)；v3.10(ASR 独立录音，28/28)；v3.11(ASR 发送态收口，30/30，新增 sanitizeAsrTranscriptText 去 EOS 结束符)；v3.12(BT 延迟 HUD+ASR 启动优化，默认 ASR_URL="" 直连 in-process sherpa，35/35)；v3.13(独立 KWS 监听链路 btListenBtn，audio-only WebRTC，KWS_LISTENING/WAKE_DETECTED/DIALOG_ACTIVE) | 数据提取 |

### D43：`JoyAI-VL-Interaction-Reportv1.pdf`

> **【解析失败】** 技术报告 — 来源：主理人转交

| 章节 | 内容摘要 | 引用方式 |
| --- | --- | --- |
| D43，§（解析失败） | 沙箱无法运行 PDF 提取工具（Bash/Python 执行不可用），Read 将该文件识别为二进制无法显示文本，故无法提取章节内容。README(D1/D2) 引用其评测数字（对比 Doubao 77.6% / Gemini 87.9%，58 场景），但 PDF 原文未核验 | 推断（风险：源文件不可读，评测数字仅来自 README 引用） |

---

### 后续架构缺口（下游设计缺口，按主理人注入要求显式列出）

> 以下为当前资料中**尚未形成可落地设计**的"后续架构缺口"，需由下游（高层架构 / 系统设计 / UserStory / 部署 / 安全 各职责方）补齐。本表仅罗列缺口，不做裁决。

| 编号 | 缺口类别 | 当前资料中的表征 | 缺口归属文档职责 |
| --- | --- | --- | --- |
| G1 | 模块级拆分 | live_adapter 拆分仅 Milestone 1 完成（D11/D12），M2/M3 待办且存在 🔴 打包阻断缺陷；webinfer/background-agent/webui 未见完整模块边界设计 | 系统设计 |
| G2 | 接口契约 | 多处端点契约仅部分明确：`/v1/summarizer/route` 热切换契约未详（D4）；memory-store `/v1/blocks/*` 仅骨架（D9/D19）；hermes shim `/v1/solve` 全字段契约未单列（D24/D41）；voice_clone `/v1/voice_clone` vs `/v2` 已定但客户端契约未展开（D5/D27）；ASR `ws://.../ws/asr` 契约未单列（D34） | 系统设计 |
| G3 | 关键表结构 | memory-store 仅 sqlite FTS5 骨架，score/last_hit_at/hit_count 字段保留未计算（D9/D19）；无会话/qa_history/用户配置等 DB schema 设计 | 系统设计 |
| G4 | 部署拓扑 | 当前仅单 Windows 单机部署（D40/D42），无多节点、无容器化/编排（Docker/K8s）、无 HA（仅重启，D40 §8） | 部署 |
| G5 | 安全威胁建模 | 全资料无威胁建模：MiniMax API key 处理（D8/D42）、自签证书（D33）、WebRTC 暴露面、委派链路鉴权均未建模 | 安全 |
| G6 | CI/CD | webui 107 + webinfer 66 测试绿（D4），但无 CI 流水线描述；pyproject 打包缺陷（D12）暗示缺 CI 门禁 | 部署 |
| G7 | 容量与成本 | 单卡 VRAM 预算 11.5GB（D40 §3）；云端成本 MiniMax ¥119+ASR ¥30（D31/D42）；无容量模型/扩缩容/成本监控设计 | 部署 |

### Dx：架构完成度盘点

> 按主理人注入要求，用「已完成 / 进行中 / 未开始」三态标注各项设计的进度，并明确指出缺口落在哪些文档职责范围内（高层架构 / 系统设计 / UserStory / 部署 / 安全）。

| 设计项 | 三态 | 证据出处 | 缺口归属文档职责 |
| --- | --- | --- | --- |
| 主对话链路 (WebUI→webinfer→llama-server) | 已完成 | D4 §拓扑；D40 §0/§2；D14 | 高层架构 / 系统设计 |
| 决策 token 机制 (speak/silence/delegate) | 已完成 | D4 §决策 token；D41 §数据流 | 高层架构 / 系统设计 |
| LLM 单入口网关 (ADR0006) | 已完成 | D10；D14 | 高层架构 / 系统设计 |
| 角色 prompt 注入 (bt-7274) | 已完成 | D40 §6；D42 §1/#5 | 系统设计 |
| 语音克隆 MiniMax Rapid Clone (ADR0001) | 已完成 | D5；D27 §15.9 | 系统设计 |
| Hermes 严格隔离 | 已完成 | D24；D42 §16 | 系统设计 |
| 屏幕捕获 getDisplayMedia | 已完成 | D26；D42 §16 | 系统设计 |
| KWS 自训 v4 | 已完成 | D6；D18；D42 §14 | 系统设计 |
| Jarvis 状态机 (KWS+ASR+EXIT_WORDS) | 已完成 | D3 §3 #4；D22；D23；D42 §14（代码集成 v3.3） | 系统设计 |
| memory-store v0.1 骨架 | 已完成 | D9；D19；D42 §7 v3.25（16/16 测试） | 系统设计 |
| 4-API 服务配置 (Phase 2A) | 进行中 | D3 §3 #1 设计完成；D15；D42 §10 | 系统设计 / UserStory |
| 3 独立采集模块 (Phase 2B) | 进行中 | D15；D26；D21 | 系统设计 / UserStory |
| Summarizer 热切换 (/v1/summarizer/route) | 进行中 | D4（端点存在，契约未详）；D15 §Phase 2B | 系统设计 |
| live_adapter 模块拆分 (ADR0007) | 进行中 | D11（M1 完成）；D12（🔴 打包缺陷，M2/M3 待办） | 系统设计 |
| API 化 (ASR/TTS 上云) | 进行中 | D3 §3 #2 半落地；D30；D31；D42 §10/§12 | 系统设计 / 部署 |
| 11 用户故事 (松耦合服务) | 进行中 | D15（列出，未见验收落地） | UserStory |
| WebUI 链路测试修正 (v3.6~v3.13) | 已完成 | D20；D21；D28；D42 §18~§25（回归 17→35 条） | 系统设计 / UserStory |
| memory-store v0.2 (embedding/psql/obsidian) | 未开始 | D9（psql/obsidian NotImplemented）；D25（规划）；D19（范围外） | 系统设计 |
| 后续架构缺口项 (G1~G7：模块拆分/接口契约/表结构/部署拓扑/安全威胁/CI-CD/容量成本) | 未开始 | 见「后续架构缺口」表 | 系统设计 / 部署 / 安全 |

---

## 3. 冲突记录

> 不同资料对同一事实描述矛盾时，**并列保留两个版本**，不做裁决。

| 编号 | 冲突主题 | 版本 A | 出处 A | 版本 B | 出处 B | 差异说明 |
| --- | --- | --- | --- | --- | --- | --- |
| X1 | GPU 数量 | 3 张 GPU（GPU0 主 0.9 / GPU1 摘要 0.9 / GPU2 ASR 0.3+TTS 0.6） | D41，§GPU 分配 | 1 张 RTX 5060 Ti 16GB（单卡） | D40，§3/§6 | 上游原架构（多卡服务器）vs 本地化目标（单卡 Windows），属平台演化 |
| X2 | TTS 后端 | CosyVoice3 / vLLM-Omni（本地零样本） | D41，§组件职责/§端口表 | MiniMax Rapid Clone（speech-2.8-hd，云端） | D27，§15.9；D5 | 演化：CosyVoice3 于 2026-07-12 删除（D27） |
| X3 | ASR 后端 | whisper.cpp（端口 8993，本地） | D41，§端口表 | sherpa-onnx 流式（WebUI 进程内，0 网络） | D22；D40，§0 | 演化：本地化后改为进程内 sherpa-onnx |
| X4 | 主 VLM 后端 | vLLM | D41，§Overview | llama-server（GGUF IQ4_NL） | D40，§6；D4，§拓扑 | 演化/本地化：Win 友好 GGUF 量化 |
| X5 | live_adapter.py 行数 | 3179 行 | D4，§模块行数 | 3531 行 | D11；D12 | 口径不同：当前架构快照时点 vs 拆分前（D12 亦记为 3531） |
| X6 | jarvis-mode.md 可解析性 | 多文档将其作为 Jarvis 设计权威来源引用（gaming-mode/asr-streaming/00-main-direction/hermes-integration/specs 引用 §2.4/§6/§13/§14/§14.2/§14.11） | D23/D22/D3/D24/D17/D20/D21 | 该文件本身被 Read 判定为二进制无法显示，无法解析真实内容，仅能从交叉引用推断 | D29 | 引用为权威但源文件不可读，内容存在核验风险（见 §2 D29 标注） |
| X7 | SPOF 表征 | webinfer(8070) 为新的单点故障，显式失败不回退 7060 | D10 | llama-server main(7060) 为唯一 SPOF，需监控+自动重启 | D40，§8；D4，§拓扑 | 不同层级 SPOF（编排层 vs 推理层），并列保留 |
| X8 | 启动脚本/端口计划 | run.sh/stop.sh（Linux，多卡，9 端口） | D41，§入口/§端口表 | start-joyai.ps1/stop-joyai.ps1（Windows，default 仅 7060/8070/8099/8985） | D40，§0；D8 | 平台演化：本地化后改为 PowerShell 编排、精简端口 |
| X9 | 记忆后端范围 | psql/sqlite/obsidian 后端规划中 | D25，§后端 | v0.1 仅 sqlite，psql/obsidian 为 NotImplemented，embedding 超出范围 | D9；D19 | 设计演进：v0.1 收窄范围，psql/obsidian/embedding 推迟 |

---

## 4. 硬指标清单

| 章节 | 硬指标 | 状态 |
| --- | --- | --- |
| §1 | 每份资料有解析状态，失败/跳过注明原因 | ✅ |
| §2 | 每份文档按章节逐条摘要，每条标注了 `D编号，§章节` | ✅ |
| §3 | 冲突信息并列保留，不做裁决 | ✅ |
| §2 | 已标记冻结/已拍板边界（architecture-current + ADR/*） | ✅ |
| §2 | 已显式列出后续架构缺口（G1~G7） | ✅ |
| §2 | 已给出架构完成度盘点（三态：已完成/进行中/未开始） | ✅ |
| §0~§4 + 附录A/B | 章节齐全，无残留占位符（尖括号占位符 / 示例前缀 / 待填日期 / 待补充标记均已替换） | ✅ |

---

## 附录 A：生成流程

### 流程总览

| 步骤 | 动作 | 落入章节 |
| --- | --- | --- |
| Step0 | 读取模板 + 全部原始资料（43 份） | — |
| Step1 | 盘点资料清单，标注解析状态（2 份解析失败：D29 jarvis-mode.md 二进制、D43 pdf 工具不可用；5 份空白 README） | §1 |
| Step2 | 逐份打开资料，按自身章节结构逐条摘要，标注 `D编号，§章节` 与引用方式 | §2 |
| Step3 | 交叉比对不同资料，发现并记录矛盾（X1~X9 并列保留） | §3 |
| Step4 | 逐项核验硬指标 | §4 |
| Step5 | 按主理人注入要求补充：冻结边界标记、后续架构缺口、架构完成度盘点 | §2 |

```mermaid
flowchart LR
    S0[读取模板与资料] --> S1[盘点资料清单]
    S1 --> S2[逐份精读逐章节摘要]
    S2 --> S3[交叉比对记录冲突]
    S3 --> S4[硬指标自检]
    S4 --> S5[冻结标记+缺口+完成度盘点]
```

### 整理原则

1. **逐份精读，不跨文档归并**：摘要按文档自身章节结构组织，不做跨文档的主题重组（那是下游的事）
2. **出处即章节号**：每条摘要标注 `D编号，§章节`，直接映射回原文位置
3. **冲突保留**：矛盾信息并列保留两个版本，不擅自裁决
4. **事实驱动**：以原始资料中的事实为准，不添加主观推断
5. **边界显式**：冻结/已拍板文档（D4、D5~D11）明确标注，下游不得自行更改
6. **缺口与进度外显**：按主理人要求显式列出后续架构缺口与架构完成度三态

### 解析状态备注（§1 失败/空白原因）

- **D29 `doc/subsystems/jarvis-mode.md`**：Read 工具返回"Cannot display content of binary file"，重试仍失败；内容仅能从交叉引用（D22/D23/D3/D24/D17/D20/D21）推断，已在 §2/§3 标注风险。
- **D43 `JoyAI-VL-Interaction-Reportv1.pdf`**：沙箱 Bash/Python 执行不可用，无法运行 pypdf/pdfplumber；Read 识别为二进制不可显示；建议主理人在可提取环境重跑或由人工提供文本。
- **D35~D39 空白 README**：文件当前无实质内容（空白文档），已解析但提示下游补全。

---

## 附录 B：解析 Skill

- `docx`：Word 类产品/业务文档
- `pdf`：PDF 类规范、手册、报告
- `pptx`：PPT 类方案/汇报
- `xlsx`：Excel 类数据清单、指标表
- `md`：本项目主体资料类型（需求/架构/ADR/specs/subsystems/api/服务 README/交付清单）
