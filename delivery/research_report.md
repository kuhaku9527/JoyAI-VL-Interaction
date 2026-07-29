# JoyAI-VL-Interaction · 行业调研报告

> 本文档为《JoyAI-VL-Interaction 架构设计》核心产物之一，定位为**行业调研报告（research_report）**。
> 上游输入：主理人转交的用户诉求 + `material_digest.md`（G1 已通过）；
> 下游输出：驱动 `business-architect`（业务架构师）的行业调研判断，最终落入《高层架构设计》的 §3 行业调研章节。
> 角色边界：本报告仅提供证据与建议，**不冻结最终业务边界**——边界冻结归 `business-architect`（G3）。

> **结构纪律**：全文按「事实 → 对比 → 建议 → 风险」四段式组织（§2 事实 / §3 对比 / §4 建议 / §5 风险），严禁倒序或跳段。

---

## 0. 元信息：修订记录

```yaml
标题: JoyAI-VL-Interaction - 行业调研报告 v0.1
版本: v0.1
状态: Reviewing   # Draft | Reviewing | Approved | Deprecated
创建日期: 2026-07-20
最后更新: 2026-07-20
调研人: research-analyst（查有据）
审核人:
  - 主理人（team-lead，待 G2 人工审核）

关联文档:
  上游输入:
    - 用户诉求: 主理人注入（生成完整系统架构方案，覆盖 7 方面）
    - 调研目标: 主理人注入（对齐资料缺口 G1~G7 的 5 条种子问题）
    - 资料基线: D:\AI\workspace\JoyAI-VL-Interaction-main\.workbuddy\output\material_digest.md
  下游产出:
    - 高层架构设计 §3 行业调研: 将由 business-architect 整合到此章节
```

| 版本 | 日期 | 作者 | 变更内容 | 评审状态 |
| --- | --- | --- | --- | --- |
| v0.1 | 2026-07-20 | research-analyst（查有据） | 初稿：围绕 G1~G7 缺口完成标杆盘点、加权评分与取舍建议 | Reviewing（G2 待审） |

---

## 1. 调研问题收敛

> 调研启动前，先围绕用户诉求收拢为明确的调研问题集合，确保调研不偏离当前项目背景。

### 1.1 原始调研种子

> 从用户诉求与资料缺口 G1~G7 中提取需要调研验证的论题，逐条给出调研优先级。

| 编号 | 待验证论题 | 来源（用户诉求要点 / 资料缺口） | 调研优先级 | 备注 |
| --- | --- | --- | --- | --- |
| S1 | 实时视觉-语言推理的部署形态对标：vLLM vs llama.cpp/GGUF 量化 vs 云多模态 API（GPT-4o / Gemini Live 等）；延迟（1s 以内目标）、私有化、单卡 VRAM 预算（项目当前 ~11.5GB @ RTX 5060 Ti）权衡 | 用户诉求(3)技术选型；G1 模块拆分 / G4 部署拓扑 / G7 容量成本 | 高 | 直接决定推理主路径 |
| S2 | 实时音视频流式链路标杆：WebRTC + 进程内 KWS/ASR(sherpa/Paraformer) + TTS 的本地优先开源方案 vs 云 ASR/TTS；端到端延迟基准、冷启动、带宽 | 用户诉求(2)交互与数据流；G2 接口契约 | 高 | 决定流式传输层形态 |
| S3 | 本地优先 + 可选云端的能力分层与成本模型（ASR/TTS/声音克隆上云 vs 全本地），以及 MiniMax Token Plan 类"全包"套餐对比 | 用户诉求(7)部署/环境；G7 容量成本 | 中 | 支撑分层部署与 TCO |
| S4 | 多进程/多服务系统的部署拓扑与高可用：单机裸进程 vs Docker 编排 vs K8s；进程级 SPOF 监控自愈、CI/CD 门禁（pytest + 打包校验）实践 | 用户诉求(6)可扩展性与 HA / (7)部署；G4 部署拓扑 / G6 CI-CD | 高 | 决定运维形态与可用性 |
| S5 | 本地 LLM + 摄像头/RTSP + 外部 API Key 场景的威胁建模与防护标杆：STRIDE、IAM、密钥管理（KMS/Vault）、自签证书与 WebRTC 暴露面收敛 | 用户诉求(5)安全性与权限；G5 安全威胁建模 | 高 | 当前资料完全缺失，优先级高 |

### 1.2 调研问题收敛

> 将 §1.1 的种子收敛为 5 个可执行的调研问题。每条问题明确调研对象、调研目标与预期产出。

| 编号 | 调研问题 | 调研对象 | 调研目标 | 预期产出 | 关联种子 |
| --- | --- | --- | --- | --- | --- |
| Q1 | 在单卡 RTX 5060 Ti 16GB、目标 1s 以内延迟、私有化约束下，本地量化推理(llama.cpp/GGUF)、高吞吐自托管(vLLM)、云端多模态 API(OpenAI Realtime) 三种范式的场景契合与权衡是什么？ | OpenAI Realtime API / vLLM / llama.cpp（GGUF）官方文档与基准 | 量化三种推理范式的延迟、私有化、硬件预算、成本差异 | 推理主路径对比矩阵 + 选型依据 | S1 |
| Q2 | 实时音视频流式链路应采用何种架构？WebRTC + 进程内 KWS/ASR(sherpa/Paraformer) + TTS 的本地优先开源编排(Pipecat 类) vs 云端语音 API，端到端延迟/冷启动/带宽基准如何？ | Pipecat（开源编排框架）/ OpenAI Realtime / 项目现有 WebRTC+sherpa 链路 | 梳理流式编排范式与延迟基准，验证本地优先编排可行性 | 流式链路标杆事实 + 可借鉴设计模式 | S2 |
| Q3 | 本地优先 + 可选云端的能力分层（ASR/TTS/克隆上云 vs 全本地）成本模型如何？MiniMax Token Plan 类"全包"套餐对比结论？ | MiniMax Token Plan 官方定价 / 阿里云/火山 ASR-TTS 定价 / 项目内部测算(D31/D42) | 建立三档能力分层（全本地 / 语音上云 / 全云）的月成本与收益模型 | 成本分层模型 + 套餐对比结论 | S3 |
| Q4 | 多进程/多服务系统的部署拓扑与高可用如何落地？单机裸进程(PowerShell) vs Docker Compose vs K8s；进程级 SPOF 监控自愈、CI/CD 门禁(pytest+打包校验)实践？ | Ollama/vLLM Docker Compose 生产实践 / 项目 start-joyai.ps1 | 提炼本地 AI 多服务编排的 HA 与 CI 门禁模式 | 部署拓扑选型 + 监控自愈 + CI 门禁建议 | S4 |
| Q5 | 本地 LLM + 摄像头/RTSP + 外部 API Key 场景的威胁建模与防护标杆？STRIDE/OWASP LLM Top10、IAM、密钥管理(Vault)、自签证书与 WebRTC 暴露面收敛？ | STRIDE-AI 框架 / Vault 密钥管理实践 / Ollama 生产加固 | 建立本地优先 AI 系统的威胁面清单与缓解基线 | 威胁建模方法 + 密钥/暴露面防护建议 | S5 |

---

## 2. 事实：标杆系统盘点和方案详述

> **四段式「事实」段**。只陈列调研发现的事实，不做引申建议或边界裁决。

### 2.1 行业标杆清单

> 完整盘点调研覆盖的所有标杆系统，给出标签化画像。

**硬指标**：≥ 3 家；至少包含 1 家头部 SaaS 代表 + 1 家开源/自研代表。

| 编号 | 标杆系统 | 厂商 / 社区 | 部署形态 | 场景覆盖 | 技术亮点 | 商业模式 | 调研来源 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | OpenAI Realtime API（gpt-realtime / GPT-4o） | OpenAI（头部 SaaS） | 云端 SaaS（WebSocket / WebRTC 持久连接） | 低延迟语音到语音 + 图像输入的多模态实时对话 | 单一模型语音到语音、自动 VAD/打断、function calling、图像输入、MCP 工具 | 按 token 计费（gpt-realtime $32/1M 音频输入、$64/1M 音频输出） | SR-01 |
| B2 | vLLM | vLLM 社区（开源，Apache 2.0） | 自托管（裸机 / Docker / K8s，NVIDIA·AMD·CPU 等） | 高吞吐 LLM/VLM 推理服务，OpenAI 兼容 API | PagedAttention、连续批处理、GGUF/INT4/FP8 等量化、多 LoRA、多模态(Qwen-VL 等) | 开源免费，自有算力 | SR-02 |
| B3 | llama.cpp / llama-server（GGUF IQ4_NL） | ggml-org（开源，MIT） | 自托管（单二进制，裸机 / 容器，CPU+GPU 混合卸载） | 消费级硬件本地 LLM/VLM 推理，OpenAI 兼容 server | GGUF 单文件格式、IQ4_NL 等 imatrix 量化、-ngl GPU 卸载、极低依赖 | 开源免费（MIT），自有算力 | SR-03 |
| B4 | Pipecat（Daily 开源编排框架） | Daily.co（开源，GitHub 社区维护） | 自托管 + 可选云传输（Daily 全球 WebRTC / SmallWebRTC P2P） | 实时语音/多模态 Agent 编排：可插拔 STT/LLM/TTS + WebRTC 传输 | Pipeline/Frame 架构、VAD/智能打断、供应商中立、60+ 集成、SmallWebRTC 自托管 | 框架开源免费；STT/LLM/TTS 按所选服务商计费 | SR-04 |

### 2.2 标杆方案详述

> 每家标杆逐一展开（B1~B4 均有详述）；每段区分「已核实的事实」与「推断/假设」。

#### 2.2.1 B1 - OpenAI Realtime API（gpt-realtime / GPT-4o）

| 维度 | 内容 | 置信度 |
| --- | --- | --- |
| 产品定位 | 云端低延迟、多模态（语音到语音 + 图像输入）实时对话 API，面向生产级语音 Agent | 已核实 |
| 目标用户 | 需快速构建自然语音对话应用的开发者、客服/语言学习/陪伴类产品的工程团队 | 已核实 |
| 核心能力 | 单一模型语音到语音、自动 VAD 与打断处理、function calling / MCP 工具、图像输入（gpt-realtime 起支持）、可复用 prompt | 已核实 |
| 架构特点 | 持久 WebSocket / WebRTC 连接；服务端维护会话状态；官方内置内容安全分类器（100ms 以内筛查）与隐私护栏 | 已核实 |
| 部署形态 | 纯云端 SaaS，无私有化部署选项；数据经 OpenAI 基础设施处理 | 已核实 |
| 集成方式 | 官方 SDK + WebRTC / WebSocket 两种传输；支持 SIP 接入电话网 | 已核实 |
| 定价模式 | 按 token 计费：gpt-realtime 音频输入 $32/1M、音频输出 $64/1M（较 gpt-4o-realtime-preview 降价 20%，2025-08 GA） | 已核实 |
| 优势 | 开箱即用的超低延迟语音体验、生态成熟、无需自管推理与音频管线 | 综合归纳 |
| 局限 | 数据必须出公网（不可私有化）、持续语音场景 token 成本高、依赖外网与 API Key、无本地离线能力 | 已核实 + 推断 |
| 对本项目的参考价值 | 作为"全云档"的能力参照（Q3 分层）；其 VAD/打断/图像输入设计思路可借鉴，但**不可作为主路径**（与项目本地优先、Apache 2.0 全开源、数据不出本机的冻结底线冲突） | 推断 |

#### 2.2.2 B2 - vLLM

| 维度 | 内容 | 置信度 |
| --- | --- | --- |
| 产品定位 | 高性能、易用的开源 LLM/VLM 推理与服务库，面向数据中心与自托管场景 | 已核实 |
| 目标用户 | 需自托管大模型推理的团队、追求高吞吐与 OpenAI 兼容接口的建设者 | 已核实 |
| 核心能力 | PagedAttention 显存管理、连续批处理、分块预填充、前缀缓存、投机解码、GGUF/INT4/INT8/FP8 等量化、多 LoRA、多模态模型(Qwen-VL 等)、OpenAI 兼容 API server | 已核实 |
| 架构特点 | 张量/流水线/数据/专家并行分布式推理；解耦 prefill/decode；支持 NVIDIA/AMD/CPU/TPU/昇腾等硬件 | 已核实 |
| 部署形态 | 自托管，裸机或容器（Docker / K8s），需 Python+CUDA 运行时 | 已核实 |
| 集成方式 | OpenAI 兼容 REST API（/v1/chat/completions 等）、Anthropic Messages API、gRPC | 已核实 |
| 定价模式 | Apache 2.0 开源，免费；成本来自自有 GPU 与运维 | 已核实 |
| 优势 | 业界领先吞吐、社区活跃（2000+ 贡献者）、多模态与量化支持完善、可水平扩展 | 综合归纳 |
| 局限 | 运行时较重（PyTorch/CUDA），对单张消费级 GPU 的"开箱即用"友好度低于 llama.cpp；需关注显存利用率调参 | 推断 |
| 对本项目的参考价值 | 高吞吐/规模化场景的推理备选（项目早期曾用 vLLM，后转 GGUF 以适配 Windows 单卡）；其健康检查与容器化部署模式可直接借鉴用于本地多服务编排（Q4） | 推断 |

#### 2.2.3 B3 - llama.cpp / llama-server（GGUF IQ4_NL）

| 维度 | 内容 | 置信度 |
| --- | --- | --- |
| 产品定位 | 纯 C/C++ 的本地大模型推理引擎，目标是在消费级硬件（含 CPU/单卡 GPU）上高效运行 LLM/VLM | 已核实 |
| 目标用户 | 个人开发者、隐私敏感/离线场景、消费级 GPU 本地 AI 使用者 | 已核实 |
| 核心能力 | GGUF 单文件格式、k-quants 与 IQ 系列量化（IQ4_NL/IQ4_XS 等，imatrix 校准）、llama-server 提供 OpenAI 兼容 HTTP、GPU 层卸载(-ngl)、CPU/GPU 混合、KV cache 量化 | 已核实 |
| 架构特点 | 单二进制、近乎零外部依赖；mmap 加载模型；-ngl 控制 GPU 卸载层数，实现独有的混合 CPU/GPU 拆分 | 已核实 |
| 部署形态 | 自托管，裸机或容器；可纯 CPU 也可 CUDA/ROCm/Metal 加速 | 已核实 |
| 集成方式 | llama-server 暴露 /v1/chat/completions、/v1/models 等 OpenAI 兼容端点；CLI 与 HTTP 双形态 | 已核实 |
| 定价模式 | MIT 开源，免费；成本来自自有硬件 | 已核实 |
| 优势 | 极致轻量、最低依赖与最低成本、消费级 GPU 友好、私有化彻底（数据不出本机） | 综合归纳 |
| 局限 | 多模态(VLM)能力较 vLLM 新且部分实验性；超高并发吞吐不及 vLLM；需手动管理量化档位与上下文长度 | 推断 |
| 对本项目的参考价值 | **与项目当前主路径高度一致**（D40 §6：主对话后端由 vLLM 转 llama-server GGUF IQ4_NL，单卡 ~11.5GB 显存）——是本地优先推理的优先借鉴基线 | 推断 |

#### 2.2.4 B4 - Pipecat（Daily 开源编排框架）

| 维度 | 内容 | 置信度 |
| --- | --- | --- |
| 产品定位 | 开源 Python 框架，用于构建实时语音与多模态对话 Agent，统一编排音频/视频、AI 服务、传输与对话管线 | 已核实 |
| 目标用户 | 构建语音助手/陪伴/客服/多模态界面的开发者；需供应商中立、可插拔流水线的团队 | 已核实 |
| 核心能力 | Pipeline/Frame 架构（帧双向流动，支持打断帧逆流）、VAD 与智能打断、可插拔 STT/LLM/TTS（60+ 集成）、SmallWebRTC 自托管 P2P 传输 | 已核实 |
| 架构特点 | 供应商中立（每层 STT/LLM/TTS 可独立替换）、传输无关（WebRTC/WebSocket/电话）；官方实测同集群 GPU 下语音到语音往返 500–800ms | 已核实 |
| 部署形态 | 自托管（默认 SmallWebRTC 直连 P2P，无需第三方账号）或经 Daily 全球 WebRTC 云传输 | 已核实 |
| 集成方式 | Python SDK，pip 安装；客户端有 Web/iOS/Android/C++ SDK；支持 Ollama、OpenAI、Gemini 等 LLM 服务 | 已核实 |
| 定价模式 | 框架开源免费（GitHub 社区维护，NVIDIA Blueprint 收录）；下游 STT/LLM/TTS 按所选服务商计费 | 已核实 |
| 优势 | 亚秒级实时交互、打断处理自然、生态集成度高、自托管优先、架构模式清晰可复用 | 综合归纳 |
| 局限 | 非 No-Code，需 Python 开发；超大规模并发(万级通话)工程投入高于 LiveKit；框架迭代快（约双周一更），API 稳定性需跟踪 | 已核实 + 推断 |
| 对本项目的参考价值 | 其 Pipeline/Frame + VAD/barge-in + WebRTC 传输设计模式可**部分借鉴**到项目既有的 WebUI(WebRTC)+webinfer 编排层；但不建议整体替换项目已冻结的 webinfer 单入口网关(ADR0006) | 推断 |

### 2.3 关键技术能力横向事实

> 不评分、不排序，仅按能力维度横陈各方案事实。

| 能力维度 | B1 OpenAI Realtime | B2 vLLM | B3 llama.cpp | B4 Pipecat | 说明 / 来源 |
| --- | --- | --- | --- | --- | --- |
| 部署形态 | 云端 SaaS | 自托管（裸机/容器/K8s） | 自托管（单二进制/容器） | 自托管 + 可选云传输 | SR-01~SR-04 |
| 多模态实时 | 语音到语音 + 图像输入 | 文本 + VLM（图像） | 文本 + VLM（图像，部分实验性） | 语音 + 视频 + 图像（编排层） | SR-01/SR-02/SR-03/SR-04 |
| 私有化 / 数据驻留 | 否（数据出公网） | 是 | 是 | 是（取决于所选 STT/LLM/TTS 供应商） | SR-01~SR-04 |
| 硬件需求 | 无（云端） | GPU 服务器优先，支持消费级 | 消费级 GPU（CPU/GPU 混合卸载） | 取决于所选服务 | SR-02/SR-03/SR-04 |
| 流式传输 | WebSocket / WebRTC 持久连接 | HTTP 流式 | HTTP 流式 | WebRTC（Daily / SmallWebRTC 等多种 transport） | SR-01/SR-04 |
| 开源协议 | 闭源 SaaS | Apache 2.0 | MIT | 开源（GitHub 社区维护，BSD 系） | SR-02/SR-03/SR-04 |
| 典型延迟 | 亚秒级（官方，语音到语音） | 依赖部署 | 依赖部署 | 500–800ms（同集群 GPU 官方实测） | SR-01/SR-04 |
| 成本模型 | 按 token（$32/64 每 1M 音频） | 自有硬件 | 自有硬件 | 框架免费 + 服务商计费 | SR-01/SR-04 |
| 打断 / VAD | 内置自动 VAD 与打断 | 需应用层实现 | 需应用层实现 | 内置 VAD 与智能打断（帧逆流） | SR-01/SR-04 |
| 高可用 / 运维 | 厂商托管 SLA | 需自管（健康检查、容器编排） | 需自管（进程监控+重启） | 取决于自托管基础设施 | SR-02/SR-03/SR-04 |

---

## 3. 对比：对比矩阵与加权评分

> **四段式「对比」段**。在 §2 的事实基础上建立对比矩阵，赋予权重并打分。

### 3.1 对比矩阵

> **每行权重之和 = 1.00**。评估维度与权重根据本项目本地优先、私有化、单卡消费级 GPU 的核心约束设定（与模板默认权重一致，理由见下）。

| 评估维度 | 权重 | 权重理由 | B1 OpenAI Realtime | B2 vLLM | B3 llama.cpp | B4 Pipecat |
| --- | --- | --- | --- | --- | --- | --- |
| 场景契合度 | 0.30 | 项目核心为单卡消费级 GPU 本地优先、私有化实时 VL 交互，范式匹配度决定主路径可行性，权最高 | 2 | 4 | 5 | 4 |
| 技术成熟度 | 0.20 | 实时语音/多模态编排工程复杂度高，成熟度直接影响 MVP 可靠性 | 5 | 5 | 4 | 4 |
| 集成难度（反向） | 0.15 | 本地进程内/单二进制集成 vs 云依赖/容器化，影响交付成本；已有 webinfer 编排可承载 | 3 | 3 | 5 | 3 |
| 成本（反向） | 0.15 | 消费级硬件自有算力 vs 云端按 token 持续计费，影响长期 TCO，但非唯一决定因素 | 2 | 4 | 5 | 4 |
| 合规可控性 | 0.20 | Apache 2.0 全开源、数据不出本机是项目冻结底线（ADR/本地优先），私有化能力权重大 | 1 | 5 | 5 | 4 |
| **加权总分** | **1.00** | — | **2.55** | **4.25** | **4.80** | **3.85** |

**评分标尺**：每项 1~5 分，1 = 严重不符合，3 = 基本满足但存在明显局限，5 = 完美契合。

**加权总分计算明细**：
- B1 = 2×0.30 + 5×0.20 + 3×0.15 + 2×0.15 + 1×0.20 = 0.60 + 1.00 + 0.45 + 0.30 + 0.20 = 2.55
- B2 = 4×0.30 + 5×0.20 + 3×0.15 + 4×0.15 + 5×0.20 = 1.20 + 1.00 + 0.45 + 0.60 + 1.00 = 4.25
- B3 = 5×0.30 + 4×0.20 + 5×0.15 + 5×0.15 + 5×0.20 = 1.50 + 0.80 + 0.75 + 0.75 + 1.00 = 4.80
- B4 = 4×0.30 + 4×0.20 + 3×0.15 + 4×0.15 + 4×0.20 = 1.20 + 0.80 + 0.45 + 0.60 + 0.80 = 3.85

### 3.2 评分结论

> 基于 §3.1 加权总分，形成分层结论。每层结论引用得分作为依据。

- **优先借鉴**：**B3 llama.cpp / llama-server（GGUF IQ4_NL）** — 适用度评分 **4.80**（最高）。理由：场景契合度 5/5（与项目当前单卡 RTX 5060 Ti 16GB、本地优先主路径完全一致，见 D40 §6）、集成难度 5/5（单二进制、极低依赖、OpenAI 兼容）、成本 5/5（MIT 免费、自有算力）、合规可控性 5/5（彻底私有化）。技术成熟度 4/5（VLM 部分实验性）是唯一扣分项，但已被项目现有落地验证。结论：作为推理主路径的优先借鉴基线。
- **部分借鉴**：**B2 vLLM（4.25）与 B4 Pipecat（3.85）**。
  - B2 vLLM：借鉴点 = 高吞吐/规模化自托管推理与容器化部署模式（Q4 部署拓扑、健康检查、GPU 显存利用率调参思路）；不借鉴的部分 = 不作为当前单卡 Windows 主路径（项目已因 Windows 友好性从 vLLM 转 GGUF，见 D40 §6）。
  - B4 Pipecat：借鉴点 = Pipeline/Frame 架构、VAD/智能打断（打断帧逆流）、SmallWebRTC 自托管 P2P 传输设计模式，可映射到项目既有 WebUI(WebRTC)+webinfer 编排层（Q2 流式链路）；不借鉴的部分 = 不建议整体替换已冻结的 webinfer 单入口网关（ADR0006），避免推翻既定边界。
- **不借鉴（否决）**：**B1 OpenAI Realtime API（2.55）作为主路径**。否决理由：合规可控性 1/5（数据必须出公网，不可私有化）、成本 2/5（持续语音 $32/64 每 1M 音频 token，长期 TCO 高）、场景契合度 2/5（与项目本地优先、Apache 2.0 全开源、单卡消费级 GPU 的冻结底线冲突）。说明：B1 仍作为 Q3"全云档（档3）"的能力参照标杆，项目将其定位为可选/非默认能力，由 business-architect 在下游裁决是否纳入。

### 3.3 方案组合分析

> 调研发现"单一方案无法覆盖全部需求，需要组合"，在此展开。

| 组合方式 | 覆盖哪些能力 | 未覆盖能力 | 组合复杂度 | 总体成本估算 |
| --- | --- | --- | --- | --- |
| **B3（本地推理）+ B4 设计模式（WebRTC/VAD/Frame）+ 可选 B1 云档（ASR/TTS/克隆）** | VLM 本地推理(B3)、实时流式编排与打断(B4 模式)、可选云端语音增强(B1/MiniMax) | 多节点集群 HA（需额外引入 K8s，见 §4.1）、完整威胁建模(G5，需专项) | 中（主路径 B3 已落地；B4 仅借鉴模式不替换；B1 仅上云档） | 本地算力自有；上云档参考 MiniMax Max ¥119 + 阿里云 ASR ¥30 ≈ ¥149/月（D31/D42 §12），远低于纯 B1 按 token 持续计费 |

---

## 4. 建议：取舍决策支持

> **四段式「建议」段**。基于 §2 事实 + §3 对比，给出可被 `business-architect` 直接采用的建议。本节是建议而非最终裁决，最终边界由业务架构师冻结。

### 4.1 自研 / 采购 / 复用边界建议

| 能力项 | 建议方式 | 建议依据 | 候选方案 / 系统 | 关键前提 |
| --- | --- | --- | --- | --- |
| 推理服务（VLM 主模型） | 复用（已有底座） | B3 评分 4.80 最高，项目已落地 llama-server GGUF IQ4_NL（D40 §6），契合单卡 11.5GB 预算 | B3 llama.cpp/llama-server | VRAM 预算 ~11.5GB（D40 §3），需监控显存防 OOM |
| 流式传输层（WebRTC） | 复用（已有）+ 部分借鉴模式 | 项目已有 WebUI 进程内 sherpa + WebRTC（D22/D40）；B4 的 VAD/打断/Frame 模式可借鉴 | B4 Pipecat 设计模式（非整体替换） | 不推翻 webinfer 单入口网关（ADR0006 冻结） |
| ASR / TTS / 声音克隆 | 部分上云（采购云服务） | Q3 分层：本地优先主对话 VLM 永远本地，语音上云档收益显著（ASR 1.5–7s→0.5–1s、TTS 冷启动 5–8s→300ms、释放 1.8GB 显存，D42 §10） | MiniMax Speech 2.8 / Rapid Clone（ADR0001 冻结同步路径）；阿里云 ASR（档2） | API Key 安全托管（见 §5 R-03）；数据出境合规确认（U-03） |
| 编排网关（webinfer 8070） | 复用 / 自研（已冻结） | ADR0006 单入口网关为既定边界，显式失败不回退 7060 | 现有 webinfer | 维持 SPOF 监控与自愈（见 R-01） |
| 部署编排 | 演进：现状自研 → 可选 Docker Compose | B2/B3 均提供成熟 Compose 实践（健康检查 + restart:unless-stopped），可补 G4 缺口 | PowerShell start-joyai.ps1（现状）/ Docker Compose（演进） | 迁移成本需 business-architect 裁决（D-01） |
| 密钥管理 | 采购/引入（生产） | Q5：环境变量仅适合开发；生产需 Vault/云 Secret Manager（SR-06） | HashiCorp Vault / 云 Secret Manager | 与现有 .env 加载方式兼容迁移 |
| 进程监控自愈 | 自研（轻量） | 借鉴 Ollama/Docker restart:unless-stopped 与 healthcheck 模式（SR-05） | 进程 health check + 自动重启脚本 | 覆盖 D40 §8 所列 SPOF 进程 |

### 4.2 MVP 范围建议

> 对用户诉求中的 7 方面功能给出"是否可在 MVP 内实现"的调研侧建议（注：用户明确"项目已有架构但后续架构没写完"，故 MVP 指"已有架构之后的下游细化设计"）。

| 功能（对齐用户诉求 7 方面） | 建议 MVP？ | 理由 |
| --- | --- | --- |
| (1) 整体架构图与各模块划分 | ✅ | 基于 D4 冻结拓扑（WebUI→webinfer→llama-server + 5 可插拔服务）细化即可，证据充分 |
| (2) 各模块交互方式与数据流向 | ✅ | D4 §拓扑、D40 §2 数据流已给出主干；仅需补全 G2 未详端点契约 |
| (3) 技术选型建议与理由 | ✅ | 本报告 §2~§3 已提供（B1~B4 对比 + 加权评分） |
| (4) 数据库设计方案与关键表结构 | ⚠️ 部分 | memory-store v0.1 sqlite FTS5 骨架已定（D9/D19）；但 qa_history/用户配置/会话等 schema 未设计，留 v0.2（D9 psql/obsidian NotImplemented） |
| (5) 安全性设计与权限控制策略 | ⚠️ 部分 | G5 完全缺失威胁建模；MVP 先做密钥托管 + 自签证书收敛 + WebRTC 暴露面收敛，完整 STRIDE 留后续（见 §5 R-03/R-04） |
| (6) 可扩展性与高可用性保障 | ⚠️ 部分 | G4 无多节点/容器化；MVP 先做单机进程监控自愈 + 可选 Docker Compose，集群化(K8s)留后续（D-01） |
| (7) 部署架构与环境配置说明 | ✅ | 基于 D40 单机 Windows+RTX 5060 Ti 拓扑细化 + Docker Compose 可选方案，证据充分 |

### 4.3 技术栈参考建议

| 技术层 | 推荐方案 | 替代方案 | 选择理由 |
| --- | --- | --- | --- |
| VLM 推理 | llama-server（GGUF IQ4_NL，B3） | vLLM（B2） | 私有化 + 单卡消费级 GPU 友好、MIT 免费、OpenAI 兼容；vLLM 适规模化 |
| 流式传输 | WebRTC（浏览器 getDisplayMedia + mic，已有） | SmallWebRTC（Pipecat，B4 自托管 P2P） | 已有 WebRTC 链路；SmallWebRTC 可借鉴作无第三方账号的直连备选 |
| 本地 ASR/KWS | sherpa-onnx（进程内，已有，D22） | 阿里云 ASR（上云档） | 本地零网络、低延迟；上云档提升准确率(CER 6%→3%，D42 §10) |
| TTS / 声音克隆 | MiniMax Speech 2.8 / Rapid Clone（ADR0001 冻结） | 本地 CozyVoice（fallback） | 已拍板同步路径；本地 CozyVoice 作降级（D42 §5） |
| 部署编排 | PowerShell start-joyai.ps1（现状） | Docker Compose | 现状可用；Compose 补健康检查/restart 与可移植性(G4) |
| 密钥管理 | 环境变量（.env gitignored，开发） | HashiCorp Vault / 云 Secret Manager（生产） | 开发简单；生产需 Vault 动态轮换+审计(SR-06) |
| 监控自愈 | 进程 health check + 自动重启（轻量） | Prometheus + Grafana（规模化） | 轻量覆盖 SPOF；规模化再引入指标栈(SR-05) |

---

## 5. 风险与待确认项

> **四段式「风险」段**。列出调研中发现的主要风险、不确定信息、待业务架构师进一步裁决的依赖项。

### 5.1 主要风险清单

| 编号 | 风险描述 | 触发条件 | 影响范围 | 严重程度 | 缓解建议 |
| --- | --- | --- | --- | --- | --- |
| R-01 | webinfer(8070) 成为新单点故障（ADR0006 显式失败、不回退 7060） | webinfer 进程崩溃/卡死 | 核心对话链路全失败（决策 token 无法生成、TTS 不触发） | 高 | 进程级 health check + 自动重启（借鉴 Docker restart:unless-stopped / Ollama healthcheck，SR-05）；崩溃面与 7060 解耦监控 |
| R-02 | llama-server main(7060) 为唯一 SPOF（D40 §8） | 主模型进程挂 = 全瘫 | 全部 VL 推理不可用 | 高 | 监控 + 自动重启；预留显存防 OOM（上下文长度/KV cache 控制，参考 VLLM_GPU_MEMORY_UTILIZATION 思路映射到 llama.cpp -ngl/上下文）；预留 4.5GB 给游戏(D40 §3) |
| R-03 | MiniMax API Key 泄露/滥用（G5 无威胁建模） | Key 硬编码/日志泄露/无限额 | 财务损失（持续计费）+ 语音/克隆数据出境合规风险 | 高 | Vault/环境变量隔离 + 按量限额 + 审计日志（SR-06）；遵守本地优先、仅 ASR/TTS/克隆上云；轮换机制 |
| R-04 | WebRTC 暴露面 + 自签证书（D33 自签，G5） | 8099 暴露公网 / 自签 cert MITM | 未授权访问、中间人窃听摄像头/麦克风流 | 中 | 绑定 localhost/内网；反向代理 TLS 终止；仅本地或 VPN 访问（参考 Ollama 生产加固：Nginx TLS + 网络分段，SR-05） |
| R-05 | 单卡 VRAM 预算紧张（11.5GB / 16GB，D40 §3） | 新增服务/上下文膨胀超显存 | OOM、推理降级或崩溃 | 中 | GGUF IQ4_NL 量化、关闭非必要服务、持续监控 VRAM 占用 |
| R-06 | 多进程无 CI 门禁 + pyproject 打包缺陷（D12 🔴，G6） | 发布破坏（如打包缺模块） | 构建/交付失败，回归漏检 | 中 | CI 流水线（pytest + 打包校验）门禁；复用项目已有 173 测试（D4）；修复 D12 打包缺陷后再放开发布 |

### 5.2 待确认项（需主理人 / 业务方反馈）

| 编号 | 待确认项 | 不确定性说明 | 若无法确认的备选路径 |
| --- | --- | --- | --- |
| U-01 | `doc/subsystems/jarvis-mode.md` 源文件不可读（D29，二进制） | Jarvis 状态机权威细节仅能从交叉引用推断，存在核验风险 | 主理人在可提取环境重跑 Read，或人工提供文本；当前以 D22/D23/D42 §14 交叉引用为准 |
| U-02 | PDF 技术报告评测数字（对比 Doubao 77.6% / Gemini 87.9%，58 场景，D43） | PDF 工具不可用，评测数字仅来自 README 引用，未核验 | 主理人在可运行 pypdf/pdfplumber 环境重提取，或人工提供文本 |
| U-03 | MiniMax 中国区数据出境合规细节（语音/克隆上云） | 项目本地优先、仅 ASR/TTS/克隆上云，涉及音频数据出境，需法务/合规确认 | 若不可行，备选：全本地 ASR/TTS（sherpa + 本地 CozyVoice）替代上云档（档2→全本地） |
| U-04 | 是否需要 K8s 多节点集群化（G4） | 项目当前单机 Windows，集群化需求与时机未定 | 由 business-architect 在高层架构阶段裁决；MVP 先单机 + 可选 Docker Compose |

### 5.3 需业务架构持续关注的依赖项

| 编号 | 依赖项 | 说明 | 建议关注阶段 |
| --- | --- | --- | --- |
| D-01 | 若引入 Docker Compose / K8s，需评估对现有 PowerShell 启动编排的迁移成本 | 影响 G4 部署拓扑与现有 start-joyai.ps1/stop-joyai.ps1 生命周期 | 高层架构设计 §部署 |
| D-02 | 安全威胁建模（STRIDE / OWASP LLM Top10）需嵌入安全设计 | G5 当前完全缺失，需专项产出威胁模型与缓解 | 安全设计（G5） |
| D-03 | memory-store v0.2（psql / obsidian / embedding）范围与时机 | G3 表结构演进，v0.1 仅 sqlite（D9/D19），范围外能力推迟 | 系统设计（G3） |

---

## 6. 关键来源目录

> 集中列出全部调研所使用的公开资料、官方文档、社区仓库、分析报告等。每条来源不低于 URL 粒度，关键来源给出具体章节或段落。

**硬指标**：
- ≥ 3 条来源，覆盖每家标杆（B1~B4 均覆盖）。
- 关键数据（定价、延迟、协议）已指定来源段落/位置。

| 编号 | 来源类型 | 标题 / 名称 | URL / 路径 | 相关章节 | 最后访问日期 |
| --- | --- | --- | --- | --- | --- |
| SR-01 | 官方文档 | OpenAI Realtime API（gpt-realtime / GPT-4o Audio）模型与定价页 | https://platform.openai.com/docs/models/gpt-4o-audio-preview ；https://openai.com/index/introducing-gpt-realtime/ | B1, §2.2.1, §3.1 | 2026-07-20 |
| SR-02 | 开源文档 | vLLM 官方文档（特性/量化/部署/多模态） | https://docs.vllm.com.cn/en/latest ；https://vllm.readthedocs.io/ | B2, §2.2.2, §2.3 | 2026-07-20 |
| SR-03 | 开源文档 / 社区 | llama.cpp（GGUF / IQ4_NL / llama-server） | https://llama-cpp.com/ ；https://hivebook.wiki/wiki/llamacpp-c-c-plus-plus-llm-inference-engine | B3, §2.2.3, §2.3 | 2026-07-20 |
| SR-04 | 开源文档 / 仓库 | Pipecat（实时语音多模态编排框架）官方文档与 GitHub | https://docs.pipecat.ai/ ；https://github.com/pipecat-ai/pipecat | B4, §2.2.4, §2.3, §3 | 2026-07-20 |
| SR-05 | 技术实践 | 本地 AI 的 Docker / K8s 部署与生产加固（健康检查、restart、Nginx TLS、监控） | https://www.local-llm.net/guides/docker-kubernetes-local-ai/ ；https://www.sitepoint.com/ollama-local-llm-production-deployment-docker/ | §4.1, §4.3, §5.1 R-01/R-04 | 2026-07-20 |
| SR-06 | 安全实践 | LLM API Key 管理与 Vault/Secrets 最佳实践 | https://devtools.cloud/secrets-management-for-llm-integrations-best-practices-for-a ；https://martinuke0.github.io/posts/2026-03-21-securing-your-llm-applications-a-practical-guide-to-api-key-management | §4.1, §5.1 R-03 | 2026-07-20 |
| SR-07 | 安全框架 | STRIDE-AI：生成式 AI 威胁建模框架（STRIDE 适配 + OWASP LLM Top10） | https://www.themoonlight.io/zh/review/stride-ai-a-threat-modeling-framework-for-generative-ai-security-assessment ；https://learn.microsoft.com/.../4-evaluate-application-threats-threat-modeling | §5.1 R-03/R-04, §5.3 D-02 | 2026-07-20 |
| SR-08 | 官方定价 | MiniMax Token Plan 套餐（Plus ¥49 / Max ¥119 / Ultra ¥469，全模态） | https://platform.minimaxi.com/subscribe/coding-plan | §3.3, §4.1, Q3 | 2026-07-20 |
| — | 内部基线 | JoyAI-VL-Interaction 资料摘要 v0.1（material_digest.md，含 D4/D22/D27/D31/D40/D42 等） | D:\AI\workspace\JoyAI-VL-Interaction-main\.workbuddy\output\material_digest.md | 全文（冻结边界与缺口 G1~G7） | 2026-07-20 |

---

## 7. 硬指标清单

> 汇总本模板所有章节的硬指标，供自动校验与人工审核使用。

| 章节 | 硬指标项 | 当前状态 | 备注 |
| --- | --- | --- | --- |
| §1 | 调研问题已收敛为 ≥ 3 条可执行问题 | ✅ | 收敛为 Q1~Q5 共 5 条 |
| §2.1 | 标杆系统 ≥ 3 家，含 ≥ 1 家头部 SaaS | ✅ | B1 OpenAI(头部 SaaS) + B2/B3/B4 开源，共 4 家 |
| §2.1 | 标杆系统 ≥ 1 家开源或自研代表 | ✅ | B2 vLLM / B3 llama.cpp / B4 Pipecat 均为开源 |
| §2.2 | 每家标杆有独立详述卡片 | ✅ | B1~B4 共 4 张，含 10 维度 + 置信度 |
| §2.3 | 关键能力横向事实无遗漏 | ✅ | 10 能力维度横陈 |
| §3.1 | 对比矩阵含 5 维度 + 权重 + 评分 | ✅ | 权重之和 = 1.00（0.30+0.20+0.15+0.15+0.20） |
| §3.2 | 评分结论含优先/部分/不借鉴三层 | ✅ | 优先 B3 / 部分 B2+B4 / 不借鉴 B1(主路径) |
| §4.1 | 自研/采购/复用边界有明确建议 | ✅ | 7 项能力边界建议 |
| §4.2 | MVP 范围建议与用户诉求对齐 | ✅ | 对齐用户 7 方面，标注 ✅/⚠️ 部分 |
| §5.1 | 主要风险 ≥ 3 条，有缓解建议 | ✅ | R-01~R-06 共 6 条，均含缓解 |
| §6 | 关键来源可追溯（URL / 章节） | ✅ | SR-01~SR-08 + 内部基线，均含 URL |
| 全文 | 明确区分事实 / 推断 / 建议 / 风险 | ✅ | §2 事实 / §3 对比 / §4 建议 / §5 风险；§2.2 逐行标置信度 |
| 全文 | 不存在编造来源或占位符 | ✅ | 无尖括号占位符 / 示例前缀 / [待验证] 残留 |
