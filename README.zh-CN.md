<p align="center">
  <img src="img/readme-hero.gif" alt="JoyAI-VL-Interaction 横幅" width="100%">
</p>

<div align="center">

<h1>JoyAI-VL-Interaction</h1>

<p><strong>⚡ 开放的实时视频语言交互系统</strong></p>

<p>一个 8B 规模、完全开放的视觉语言交互模型，以及完整可部署系统。模型、训练配方、时间对齐交互数据和实时流式技术栈都集中在这个仓库中。</p>

<p>
  <a href="https://arxiv.org/pdf/2606.14777"><b>📄 arXiv</b></a> |
  <a href="https://joyai-vl-video-future-academy-jd.github.io/JoyAI-VL-Interaction/"><b>🚀 博客</b></a> |
  <a href="https://github.com/jd-opensource/JoyAI-VL-Interaction"><b>💻 代码</b></a> |
  <a href="https://huggingface.co/jdopensource/JoyAI-VL-Interaction-Preview"><b>🤗 模型</b></a> |
  <a href="https://huggingface.co/datasets/jdopensource/JoyAI-VL-Interaction"><b>📦 数据集</b></a>
</p>

<p>
  <a href="#-快速开始"><b>🚀 快速开始</b></a> |
  <a href="#-能力"><b>🧩 能力</b></a> |
  <a href="#-评测"><b>📊 评测</b></a> |
  <a href="#-引用"><b>📝 引用</b></a>
</p>

<p>
  <img src="https://img.shields.io/badge/模型-8B-blue?style=flat-square" alt="8B 模型">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/vLLM-推理-orange?style=flat-square" alt="vLLM">
  <img src="https://img.shields.io/badge/CUDA-12.x-76B900?style=flat-square&logo=nvidia&logoColor=white" alt="CUDA 12.x">
  <img src="https://img.shields.io/badge/许可证-Apache_2.0-green?style=flat-square" alt="Apache 2.0">
  <img src="https://img.shields.io/badge/延迟-<1s-d61f2c?style=flat-square" alt="亚秒级延迟">
</p>

</div>

> 原文档: [README.md](README.md)



## 🛑 如何停止服务（2026-07-11 必读）

不需要任务管理器。仓库根目录有 `stop-joyai.ps1`：当前默认链路是 `7060/8070/8099/8985` 四个服务；停止脚本还会扫描历史端口，用于清理旧进程：

```powershell
# 默认：停止当前服务，并清理历史端口（PID 文件 + 端口监听双管齐下）
powershell -ExecutionPolicy Bypass -File stop-joyai.ps1

# 只杀疯掉的那个（不杀其他的）
powershell -ExecutionPolicy Bypass -File stop-joyai.ps1 -Only 8985

# 不真杀，先列出哪些会被杀
powershell -ExecutionPolicy Bypass -File stop-joyai.ps1 -DryRun
```

也能通过 `start-joyai.ps1` 转发：

```powershell
powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Stop
```

详见 [doc/jarvis-mode.md §14](doc/jarvis-mode.md) 与 [doc/adr/0004-service-lifecycle.md](doc/adr/0004-service-lifecycle.md)。

## 🔥 最新动态

- **[2026-06-20]** 🎉 完整开源发布，模型权重、可部署系统和技术报告现已开放。
- **[2026-06-20]** 🚀 [vLLM-Omni](https://github.com/vllm-project/vllm-omni) 提供 day-0 部署支持（[部署指南](https://github.com/vllm-project/vllm-omni/blob/main/recipes/JD/JoyAI-VL-Interaction.md)）。
- **[2026-06-20]** 🎉 发布对齐交互训练数据。

[https://github.com/user-attachments/assets/2853fc95-ad21-4972-8206-5f3d19798b14](https://github.com/user-attachments/assets/2853fc95-ad21-4972-8206-5f3d19798b14)

## ✨ 简介

![JoyAI-VL-Interaction overview](img/overview.png)

最重要的时刻往往不会等你开口提问。锅里的水在你双手忙碌时溢出，孩子走向炉灶，比赛中最精彩的一瞬在你反应前已经过去。今天的 AI 很难在这些时刻帮上忙，因为这些模型从设计上就是回合制的：它们安静地等待你召唤，然后回答你刚刚提出的问题。

我们认为下一步应该是一个**像人一样在场**的模型：它会持续观察当下发生的事情，自主判断什么时候值得说一句，重要时主动开口，不重要时保持安静，并在问题较难时把任务交给更强的模型处理。

**JoyAI-VL-Interaction** 是一个 8B 规模、以视觉为核心的交互模型，并随模型一同发布训练配方、数据和完整可部署系统，且全部开放。只要把摄像头或直播流接入它，它就能立刻进入场景，实时观察并响应。

### 🌟 关键特性


|     | 特性           | 说明                                    |
| --- | ------------ | ------------------------------------- |
| ⚡   | **实时在场**     | 持续观察，并在需要时于一秒内响应。                     |
| 👁️ | **视觉触发的主动性** | 根据看到的内容开口，同时在没有重要事件时保持安静。             |
| 🤖  | **Agent 委托** | 在继续观察视频流的同时，把困难子任务交给后台模型、API 或 agent。 |
| 🔓  | **完全开放的技术栈** | 模型、数据、训练配方和可部署系统全部开放，便于完整复现。          |


## 📝 如何同步文档（2026-07-12 必读，改完代码必跑）

改完代码 → 跑 `services/scripts/sync-docs.py`，避免下次接手的人对不上：

```powershell
# 改完 jarvis_mode.py 之类的代码后：
python D:\AI\envs\joyai-main\python.exe services\scripts\sync-docs.py `
  --version v3.4 `
  --change "一句话描述这次改了什么" `
  --delivered services\webui\src\joy_interaction_webui\jarvis_mode.py `
  --affected doc\jarvis-mode.md `
  --affected doc\adr\0003-llm-reply-panel.md
```

脚本自动干：
1. 追加 `DELIVERY.md §7` 一行（含日期 + version + 改动摘要）
2. 追加 `doc/00-main-direction.md §4.0` 一项（v3.2 路线图状态）
3. 打印"人工复核清单"——列出 `--affected` 的所有 doc，由你打开编辑器手动加章节

详细用法 + 维护节奏见 [`services/scripts/README.md`](services/scripts/README.md)。

## 🚀 快速开始

```bash
git clone https://github.com/jd-opensource/JoyAI-VL-Interaction.git
cd JoyAI-VL-Interaction

# 安装依赖
./install/install.sh --with-all

# 下载所有模型权重
./install/download-models.sh --all

# 启动核心服务
./services/scripts/run.sh minimal
```

然后在浏览器中打开 `https://127.0.0.1:8099`。

👉 如需完整部署 ASR、TTS、后台 agent 以及更多配置细节，请参阅[入门指南](doc/deprecated/getting_started.md.zh-CN.md)。

🚑 如果遇到部署问题，请参阅[故障排查指南](doc/deprecated/troubleshooting.zh-CN.md)。

## 🛠️ 系统架构

![JoyAI-VL-Interaction system architecture](img/joyvl-system-architecture.png)

JoyAI-VL-Interaction 的核心，是模型每秒自主做出的一个决策：**说话**、保持**静默**，或进行**委托**。系统基于 JoyAI-VL-8B 构建，并将语音作为可插拔的输入输出，因此模型的唯一职责就是观察并判断合适的行动时机。预测式视频编码器 AdaCodec 会对可预测帧只消耗少量 token，并在场景真正变化时保留完整细节，从而让长视频流的 token 预算保持可控。模型行为来自超过四百万条时间对齐片段的学习，并通过强化学习进一步优化。

围绕模型，我们构建了一套完整可部署系统：


| 组件        | 概述                                                   |
| --------- | ---------------------------------------------------- |
| 🧠 **模型** | JoyAI-VL-Interaction：首个开放的视觉语言交互模型。                  |
| 📊 **数据** | 400 万条时间对齐交互样本，并显示出继续扩展数据规模会带来明确收益。                  |
| ⚙️ **系统** | 五个可插拔服务：推理、WebUI、ASR、TTS、后台 agent，运行在标准 vLLM 基础设施之上。 |


📐 完整架构图和组件细节请参阅[架构指南](doc/deprecated/architecture.zh-CN.md)。

## 🧩 能力

一旦交互能力被训练进模型本身，而不是通过外部框架外挂上去，一整类能力就会自然出现：在场感、在正确时机行动、感知时间，以及在长视频流中保持记忆。

![JoyAI-VL-Interaction capability grid](img/capability-grid.svg)

除了上图中的九项能力，JoyAI-VL-Interaction 还可以在游戏直播中实时解说，在你做饭时一步步指导菜谱，或者在直播流上自主生成弹幕式评论。更多视频演示请查看[博客中的能力章节](https://joyai-vl-video-future-academy-jd.github.io/JoyAI-VL-Interaction/#capabilities)。

## 📊 评测

我们在 **58 个真实的事件驱动视觉交互场景**中评测 JoyAI-VL-Interaction，并由人工评审从响应质量和响应时机两方面进行成对比较。

### JoyAI-VL-Interaction vs Doubao


| 维度      | JoyAI-VL-Interaction | 平局        | Doubao   |
| ------- | -------------------- | --------- | -------- |
| 监控与告警   | 100.0%               | 0.0%      | 0.0%     |
| 实时计数    | 70.0%                | 30.0%     | 0.0%     |
| 实时翻译    | 80.0%                | 20.0%     | 0.0%     |
| 时间感知    | 80.0%                | 10.0%     | 10.0%    |
| 直播评论与引导 | 55.6%                | 22.2%     | 22.2%    |
| 长程视觉记忆  | 77.8%                | 22.2%     | 0.0%     |
| **总体**  | **77.6%**            | **17.2%** | **5.2%** |


### JoyAI-VL-Interaction vs Gemini


| 维度      | JoyAI-VL-Interaction | 平局        | Gemini   |
| ------- | -------------------- | --------- | -------- |
| 监控与告警   | 100.0%               | 0.0%      | 0.0%     |
| 实时计数    | 100.0%               | 0.0%      | 0.0%     |
| 实时翻译    | 100.0%               | 0.0%      | 0.0%     |
| 时间感知    | 50.0%                | 40.0%     | 10.0%    |
| 直播评论与引导 | 100.0%               | 0.0%      | 0.0%     |
| 长程视觉记忆  | 77.8%                | 22.2%     | 0.0%     |
| **总体**  | **87.9%**            | **10.3%** | **1.7%** |


## 🚧 局限与未来工作

**局限。** 我们希望坦诚说明规模上的差异。我们对比的视频通话助手 Doubao 和 Gemini 背后都有更大规模的模型，并经过多年面向真实用户的产品迭代打磨；它们能力全面、知识广泛，在开放式聊天、个性化风格和日常请求长尾上都很强，难以轻易超越。JoyAI-VL-Interaction 是一个紧凑的 8B 模型，我们并不声称它在所有方面都能匹敌这些产品。我们所做的是推开一扇门：在视觉语言交互模型的优势区域，也就是实时在场、视觉触发主动性以及跨视频流的时间感中，一个小得多的开放模型已经能够取得领先。一个紧凑开放模型可以在这些方面对抗大型、深度优化的产品，这正是我们兴奋地把这项工作带给社区的原因。

**下一步。** 我们相信这还只是开始。我们训练使用的交互数据规模仍然不大，但即便如此，模型也已经涌现出一些从未显式教授的能力，例如在不断变化的应用界面中引导购物者完成操作；我们相信上限仍然很高，继续扩展这类时间对齐数据，并配合训练配方和系统，将让模型走得更远。我们追求的是一个日常瞬间：你结束漫长的一天疲惫回家，还没开口，一个安静的声音就注意到你，并说：“我能看出你很累，今天一定很辛苦。” 这种未经请求的在场感，正是交互模型能够带来的东西，而等待被点名的回合制模型永远无法做到。我们已经开放整套技术栈，包括 8B 模型、时间对齐数据、训练配方和可部署系统，希望降低所有在这个方向上探索的人的门槛。我们期待和大家一起探索，一个真正身处世界之中的模型，最终会成为什么。

## 📂 仓库结构

```text
.
├── services/
│   ├── scripts/           # 服务编排入口（run/stop）
│   ├── webinfer/          # 实时视频推理（OpenAI 兼容 API）
│   ├── webui/             # 浏览器前端 + WebRTC 流
│   ├── asr/               # 语音识别适配器（Qwen3-ASR）
│   ├── tts/               # 语音合成适配器（Qwen3-TTS）
│   └── background-agent/  # 后台任务委托 agent
├── install/               # 安装脚本、依赖设置、模型下载
├── doc/
│   ├── architecture.md          # 系统架构与数据流
│   ├── getting_started.md       # 完整部署指南
│   ├── rtsp_streaming.md        # 本地 RTSP 推流测试指南
│   └── *.zh-CN.md               # 中文文档镜像
├── img/                   # 图表和图片
├── README.md
├── README.zh-CN.md
├── LICENSE
└── JoyAI-VL-Interaction-Reportv1.pdf
```

## 📋 TODO

- [x] 发布交互模型博客
- [x] 发布可部署系统代码
- [x] 发布技术报告
- [x] 发布时间对齐交互训练数据
- [x] 发布 HuggingFace 模型
- [ ] **在线 + 离线统一模型** —— 单一全能模型，同时擅长实时在线（流式）交互与离线视频理解
- [ ] **Codec 版本** —— 搭载预测式视频编解码器（AdaCodec）的模型变体，降低长流场景下的 token 开销
- [ ] **量化版本** —— 实现更轻量、更低成本的部署
- [ ] **最优推理配置** —— 针对 RTX 3090 / 5090 调优的配置方案

## 🙏 致谢

* 基于 [LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory) 和 [EasyVideoR1](https://github.com/cyuQ1n/EasyVideoR1) 构建 —— 分别用于 SFT 和 RL 训练
* 网页界面基于 [Live VLM WebUI](https://github.com/nvidia-ai-iot/live-vlm-webui) 开发 —— NVIDIA 开源的实时 VLM 网页界面
* 兼容 [vLLM](https://github.com/vllm-project/vllm)

## 📝 引用

如果 JoyAI-VL-Interaction 对你的研究或产品有帮助，请引用：

```bibtex
@techreport{joyai2026vlinteraction,
  title        = {JoyAI-VL-Interaction: Real-Time Vision-Language Interaction Intelligence},
  author       = {{Video Understanding Team of JoyAI-VL @ Joy Future Academy, JD}},
  institution  = {Joy Future Academy, JD},
  year         = {2026},
  month        = {June}
}
```

## 📄 许可证

本项目基于 Apache License 2.0 授权。详情请参阅 [LICENSE](LICENSE)。


---

## 🪟 Windows 本地轻量化部署（RTX 5060 Ti 16GB）

> 部署目标：Windows 11 + RTX 5060 Ti 16GB + 32GB RAM，单机本地版。
> 配套文档：
> - **产品 / PM 视角**：[`doc/pm-local.md`](doc/pm-local.md)
> - **技术实现**：[`doc/tech-local.md`](doc/tech-local.md)
> - **架构图**：[`doc/architecture-local.md`](doc/architecture-local.md)
> - **游戏中对话**：[`doc/gaming-mode.md`](doc/gaming-mode.md)
> - **声音克隆**：[`doc/voice-clone.md`](doc/voice-clone.md)
> - **选型调研**：[`doc/lightweight-replacement.md`](doc/lightweight-replacement.md)

### 一键安装

```powershell
git clone https://github.com/jd-opensource/JoyAI-VL-Interaction.git
cd JoyAI-VL-Interaction
.\install\install-windows.ps1           # 装 Python 3.12 / uv / PyTorch cu128 / conda env / venv
.\install\download-gguf-models.ps1 -Component all   # 下 GGUF 模型 ~7GB
.\install\setup-llama-cpp.ps1           # sm_120 llama.cpp prebuilt
.\install\setup-whisper-cpp.ps1         # whisper.cpp cublas
.\install\setup-cosyvoice.ps1           # CosyVoice3 (conda)
.\install\setup-hermes.ps1              # Hermes-agent + 配 .env
```

### 启动

```powershell
cd services
.\scripts\run-windows.ps1 -Mode gaming   # 游戏中对话（推荐）
# 或 .\scripts\run-windows.ps1              # 全套
# 或 .\scripts\run-windows.ps1 -Mode minimal # 最小验证
```

浏览器打开 `https://127.0.0.1:8099`，接受自签证书警告。

### 关键变化

| 组件 | 原版 | 本地版 |
| - | - | - |
| 主对话 | vLLM 8B FP16 | llama-server 8B **IQ4_NL GGUF** (4.79GB) |
| 摘要 | vLLM Qwen3-VL-4B | llama-server Qwen2.5-VL-3B Q4_K_M |
| ASR | vLLM Qwen3-ASR-1.7B | **whisper.cpp** + large-v3-turbo |
| TTS | vLLM-Omni Qwen3-TTS | **CosyVoice3 0.5B** + 零样本声音克隆 |
| 后台 agent | Codex CLI | **Hermes-agent** HTTP API |
| 角色化 | 无 | `prompts/bt-7274.txt` 注入 + 热重载 |
| 显存峰值 | ~70GB（3 张 H100） | **~11.5GB**（1 张 5060Ti） |
| 留游戏 | 0GB | **4.5GB** |