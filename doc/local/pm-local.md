# JoyAI-VL-Interaction 本地化 PM 文档

> 目标：Windows 11 + RTX 5060 Ti 16GB + 32GB RAM，本地轻量化部署 + 角色化（bt-7274）+ 声音克隆 + Hermes-agent + 游戏中对话。

> 配套技术文档：doc/tech-local.md（含部署、架构、代码、运维、扩展）。本文档说"做什么/为什么"，技术文档说"怎么做"。

---

## 0. 一句话总结

把原项目 JoyAI-VL-Interaction 的 5 个服务架构原样保留，**只把底层推理引擎从 vLLM/vLLM-Omni/Codex 换成 llama-server/whisper.cpp/CosyVoice3/Hermes-agent**，主交互模型换成社区 GGUF 量化版（4.79GB），16GB 显存留 6GB 给游戏，32GB 内存全本地，零云依赖。

---

## 1. 与原 PM 文档的关系

| 原 PM 文档 | 本地化版本 |
| --- | --- |
| README.zh-CN.md（产品介绍 + 快速开始） | **不变**，仍适用作产品入门 |
| doc/architecture.zh-CN.md（Linux vLLM 部署） | **新增** doc/architecture-local.md（Windows llama-server 部署） |
| doc/getting_started.zh-CN.md（Linux 安装步骤） | **新增** doc/tech-local.md 第二节"Windows 部署步骤" |
| doc/rtsp_streaming.zh-CN.md | **不变** |
| doc/troubleshooting.zh-CN.md | **新增** doc/tech-local.md 第四节"故障排查" |
| — | **新增** doc/pm-local.md（本文） |
| — | **新增** doc/gaming-mode.md（游戏中对话指南） |
| — | **新增** doc/voice-clone.md（声音克隆工作流） |

---

## 2. 为什么做这次本地化

原项目适合"3 张 Hopper GPU + Linux 工程师"，不适合"一台 Windows 游戏机 + 个人娱乐"。本版本核心动因：

- **硬件收敛**：原项目要 3 张独立 GPU（主 8B + 摘要 4B + 语音 3.4B），一般家用机塞不下
- **平台迁移**：vLLM / vLLM-Omni 在 Windows 上不友好；vLLM-Omni 至今无 Win 预编译
- **隐私**：摄像头/麦克风数据全程不上云
- **角色化**：原项目是通用助手，本地化版本要注入固定角色（bt-7274）
- **声音克隆**：原项目用 Qwen3-TTS 通用音色，本地化要支持克隆用户指定的角色声线
- **后台 agent 替换**：原项目用 OpenAI Codex CLI，要切到用户自有的 Hermes-agent
- **游戏场景**：1 fps 视频流 + 1 人对话 + 实时语音，是个新场景

## 3. 用户与场景（本地化重定义）

原 PM 列了 6 个场景，本地版本聚焦其中 3 个 + 1 个新增：

| 场景 | 本地化是否支持 | 说明 |
| --- | :-: | --- |
| 家庭看护 / 育儿 | ✅ | 摄像头 + 主对话 + 主动告警 |
| 直播 / 赛事解说 | ✅ | RTSP 输入，主对话 + 计数 + 解说 |
| 安防 / 工业 / 产线 | ⚠️ | 16GB 显存只适合 1-2 路摄像头；多路要服务器 |
| 教学 / 陪伴 | ✅ | 主对话 + 角色化 |
| 无障碍 | ⚠️ | 需要屏幕捕获，5060Ti 单游戏场景勉强 |
| **游戏中对话（新增）** | ✅ | **本地版本核心卖点**：1 fps 视频 + 语音 I/O + 角色化 + 声音克隆 |

### 3.1 游戏中对话（重点场景）

流程：

1. 用户开游戏，把麦克风 + 耳机戴上
2. WebUI 设为"仅语音"模式（不开视频）
3. 主对话模型以 0.5-1 Hz 轮询；用户问问题时主动推流视频帧（屏幕窗口捕获或摄像头）
4. 角色化（bt-7274）让助手以游戏角色口吻回应
5. 声音克隆让用户听到的是角色声线，不是 Qwen3-TTS 默认女声
6. 用户可以问"这个怪物的弱点是啥"→ 触发 </delegate> → 调 Hermes-agent 联网查攻略
7. 助手用 1-2 句中文简短回，耳机里播

关键设计：

- **不强制推流**：默认 FORCE_SILENCE_BEFORE_QUERY=false（脚本 
un-windows.ps1 -Mode gaming 会自动设），避免主对话每帧都吐字
- **声音走 WebRTC**：浏览器 <-> WebUI <-> 适配器 <-> CosyVoice
- **CPU/显存预留给游戏**：llama-server 默认 cache-type-k/v q8_0，主模型占 ~6GB，留 10GB

## 4. 核心能力（本地化版）

| 能力 | 原版评分（vs Gemini） | 本地版预期 | 实现状态 |
| --- | ---: | --- | --- |
| 监控与告警 | 100% | 100% | ✅ 主对话 + llama-server |
| 实时计数 | 100% | 100% | ✅ 主对话 |
| 实时翻译 | 100% | 95% | ⚠️ whisper.cpp 中文强项不在翻译，可能掉到 80% |
| 直播评论与引导 | 100% | 100% | ✅ 主对话 |
| 时间感知 | 50% | 50% | ✅ 摘要 + 长期记忆保留 |
| 长程视觉记忆 | 77.8% | 70% | ⚠️ 摘要用 Qwen2.5-VL-3B GGUF，可能比原版 Qwen3-VL-4B 弱 10% |
| 角色化 | — | ✅ bt-7274 prompt 注入 | ✅ system_prompts.py |
| 声音克隆 | ❌ | ✅ ~~CosyVoice3 零样本~~ → **MiniMax Rapid Clone**（已迁移）| ✅ services/voice-clone/ |
| 后台 agent | Codex | ✅ Hermes-agent | ✅ hermes_api/main.py |
| 游戏中对话 | — | ✅ voice-only 模式 | ✅ 
un-windows.ps1 -Mode gaming |
| **综合** | **87.9%** | **~83%** | — |

## 5. 范围（Scope）

### 5.1 ✅ 在范围内

- Windows 10 + RTX 5060 Ti 16GB + 32GB RAM 单机
- 主对话：社区 GGUF IQ4_NL 量化版 + 自产 mmproj
- 摘要：Qwen2.5-VL-3B-Instruct GGUF Q4_K_M
- ASR：whisper.cpp + large-v3-turbo q5_0
- TTS：CosyVoice3 0.5B（TTS 备用） + ~~零样本声音克隆~~ → **MiniMax Rapid Clone**（已迁移云端）
- 后台 agent：Hermes-agent v0.17.0（OpenAI 兼容 HTTP API）
- 角色化：prompts/bt-7274.txt 注入到 system prompt
- 4 种启动模式：minimal / default / gaming / voice-only
- 端到端 Windows PowerShell 编排（
un-windows.ps1）
- 实时重载角色 prompt（/v1/prompts/reload）

### 5.2 ❌ 不在范围内（明确放弃）

- **量化主模型到 Q2 / Q3**：官方 TODO 里挂着，本版本不做（用户已用 IQ4_NL）
- **AdaCodec 视频压缩版**：官方 TODO 里挂着，本版本不做
- **多 GPU 训练**：本版本只跑推理，不做 SFT/RL
- **统一在线 + 离线模型**：官方 TODO 里挂着，本版本不做
- **Linux 双卡 A100 集群**：原版配置，本版本不支持（Win 优先）
- **K8s / Docker Swarm 编排**：单机版，需要自建
- **云端备份 / 同步**：本地优先
- **Web 端多用户隔离**：本地单用户，多用户要改 webui
- **多语言 UI**：本版本中文优先

### 5.3 ⚠️ 灰度区（看用户需求决定）

- **屏幕捕获做视觉对话**：技术上 work（screen_capture.py），但游戏场景是否要看你需求
- **多摄像头同时输入**：webui 支持多 session，单 session 单摄像头
- **角色 prompt 多文件叠加**：默认按字典序合并（prompts/bt-7274.txt + 其他），也可禁用
- **Hermes-agent 的 subagent 深度**：默认 max_depth=1（与原 codex 一致），可调到 2
- **声音克隆的精细控制**：~~CosyVoice3 旧本地~~ → **MiniMax Rapid Clone**（10s 样本）；本版本只暴露基础（详见 `voice-clone.md`）

## 6. 角色化（bt-7274）

### 6.1 设计

bt-7274 是用户设计的固定角色 prompt。注入位置：webinfer 适配器构造 system prompt 时，前置 <character_profile> 块。

`
<character_profile>
（来自 prompts/bt-7274.txt 的全文）
</character_profile>

（原 system prompt：You are a real-time video streaming assistant...）

Stay in character at all times. Respond as bt-7274 would.
`

**不破坏原决策格式**：</silence> / </response> / </delegate> 仍由原 system prompt 教，角色 prompt 只影响"说话方式/口吻"，不影响"说话时机/内容决策"。

### 6.2 文件位置

- 默认：D:\AI\workspace\JoyAI-VL-Interaction-main\prompts\bt-7274.txt
- 多文件：把多个 <name>.txt 放到同目录，按字典序合并
- 自定义目录：$env:CHARACTER_PROMPT_PATH = "D:\my-prompts"
- 禁用：$env:ENABLE_CHARACTER_PROMPT = "0" 或 --no-character-prompt

### 6.3 热重载

编辑完 prompt 后，**不用重启 webinfer：

`powershell
curl -X POST http://127.0.0.1:8070/v1/prompts/reload
`

### 6.4 调试

`powershell
curl http://127.0.0.1:8070/v1/prompts/active
# 返回 {ok: true, enabled: true, files: ["...bt-7274.txt"], last_mtime: ...}
`

## 7. 声音克隆

### 7.1 工作流

1. **准备参考音频**：3-10 秒单声道 WAV/MP3，16kHz 或 24kHz
2. **（可选）准备转写文本**：参考音频的精确转写，CosyVoice 用它做 prompt
3. **上传并创建档案：

   `powershell
   curl -X POST http://127.0.0.1:8985/v1/voices 
     -F "name=bt-7274" 
     -F "audio=@D:\reference\bt7274_sample.wav" 
     -F "transcript=这是参考音频的中文转写文本" 
     -F "language=zh"
   # 返回 {voice_id: "v_20260706_xxxx", ...}
   `
4. **设置 webui 默认 voice_id：
   - 编辑 services\scripts\run-windows.env，设 TTS_DEFAULT_VOICE_ID=v_20260706_xxxx
   - 重启 tts_adapter
5. **测试合成：

   `powershell
   curl -X POST http://127.0.0.1:8985/v1/synthesize 
     -H "Content-Type: application/json" 
     -d '{"text":"测试一下克隆声音","voice_id":"v_20260706_xxxx","streaming":false}'
   # 返回 base64 编码的 WAV
   `

### 7.2 边界

- 一次只能传一个 voice_id（不支持多 speaker 混合）
- 克隆声线在 oices/<voice_id>/ref.wav 持久化，删档案即删
- 上传时 voice_clone_api 会先用 CosyVoice 合成一个测试样本验证声线可用
- 声音克隆质量取决于参考音频：清晰 + 单人 + 无背景音乐 = 最好

## 8. 后台 agent 切换（Codex → Hermes）

### 8.1 为什么切

- Codex 是 OpenAI 的产品，依赖 OpenAI 账号 / 付费
- Hermes-agent 是 Nous Research 的开源，200+ provider（OpenAI/Anthropic/Gemini/DeepSeek/Qwen…）
- Hermes 有 OpenAI 兼容 HTTP API，多模态原生支持
- 接入成本 90 行 FastAPI shim

### 8.2 接入点

原架构里 background-agent 是独立的 FastAPI 服务（端口 8079），把 webui 委派的任务转给 codex CLI。  
本地版本新增 hermes_api/main.py，**接口契约完全一致**（POST /v1/solve，SolveRequest/SolveResponse 字段名/顺序/类型都不变），webui 端**零修改**。

### 8.3 启动顺序

`
hermes gateway (8642) → hermes-api shim (8079) → webinfer (8070) → webui (8099)
`

任意一个挂了，/v1/solve 返回 status: failed 带 error 字段，不会让 webui 崩。

## 9. 路线图（本地化版）

| 阶段 | 时间 | 目标 | 状态 |
| --- | --- | --- | --- |
| **P0 验证** | 第 1 周 | minimal 模式跑通（主 + webui） | ⏳ |
| **P1 完整** | 第 2-3 周 | default 模式跑通（含 ASR/TTS/agent） | ⏳ |
| **P2 角色化** | 第 4 周 | bt-7274 调通，主对话"像他" | ⏳ |
| **P3 声音克隆** | 第 5 周 | 录一段参考音频，所有 TTS 都用这个声线 | ⏳ |
| **P4 游戏场景** | 第 6-7 周 | gaming 模式跑通，声音流利，零干扰游戏 | ⏳ |
| **P5 优化** | 第 8+ 周 | 显存压到 12GB，游戏能开最高画质 | 远期 |

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
| --- | --- | --- | --- |
| llama.cpp sm_120 build 不稳 | 中 | 高 | 双备份：Andgihat prebuilt + 官方 CUDA 12.4 build |
| CosyVoice3 装失败 | 中 | 中 | 备选 CosyVoice2-0.5B / F5-TTS / GPT-SoVITS V3 |
| Hermes Win beta bug | 中 | 中 | 备选：把 hermes_api 切回 codex_api（保留旧实现） |
| 显存不够 / 调度慢 | 高 | 中 | cache-type-k/v q8_0 + ctx-size 16384 + 必要时关摘要 |
| 声音克隆效果差 | 中 | 低 | 多录几段 / 换 GPT-SoVITS V3 / 接受通用音色 |
| 游戏抢显存 | 高 | 中 | main 进程常驻 6GB 显存，游戏 16GB 留 10GB；游戏降低画质到中 |
| PyTorch cu128 在 5060Ti 上不稳 | 低 | 高 | 用 llama-server 走 GGUF，不依赖 PyTorch（主对话） |

## 11. 成功指标

| 指标 | 目标 | 测量方式 |
| --- | --- | --- |
| 端到端启动 < 5 分钟 | 从 
un-windows.ps1 到对话可交互 | 计时 |
| 主对话 < 1s 响应 | llama-server streaming + q8_0 cache | 测 10 次平均 |
| 显存峰值 < 12GB | nvidia-smi 在 default 模式跑 10 分钟 | 取峰值 |
| 声音克隆相似度（主观） | 用户说"听上去像" | 用户评分 1-5 |
| Hermes 委派成功率 | 80% 任务能正常返回 <summary> | 看 events_digest |
| Webui 端到端响应 | < 2s（含 TTS 启动） | 浏览器测 |
| 游戏中无感知卡顿 | 用户玩 30 分钟不主动抱怨 | 用户主观 |

## 12. PM 决策清单（不需要 PM 写代码，但要拍板）

- [ ] bt-7274 的具体角色内容（自填 prompts/bt-7274.txt）
- [ ] 角色说话风格（直接、毒舌、温柔、机械、…）
- [ ] 角色对游戏的偏好（玩什么、讨厌什么）
- [ ] 是否启用屏幕捕获做视觉对话（增加 1-2GB 显存 + 1-2s 延迟）
- [ ] Hermes-agent 的 model provider（Nous Portal / OpenAI / Anthropic / 本地 GGUF）
- [ ] 声音克隆的参考音频来源（已有 / 现录 / 用 TTS 合成一个再克隆）
- [ ] 部署目标机（自己的 5060Ti / 其他机器）

- [ ] 数据留存策略（视频帧是否落盘 / 多久清理 / 是否加密）

## 13. 后续动作

看完 PM 文档后，PM 应当：

1. 编辑 prompts/bt-7274.txt 填入真实角色 prompt
2. 准备一段 3-10 秒的角色参考音频
3. 选 Hermes 的 model provider
4. 跑 install/install-windows.ps1 + download-gguf-models.ps1 + setup-*.ps1
5. 跑 
un-windows.ps1 -Mode gaming 验证
6. （可选）填本文档第 12 节的所有 checkbox

详细操作步骤见 doc/tech-local.md。

## 14. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| --- | --- | --- | --- |
| 2026-07-06 | v1.0 | 初版：Windows 5060Ti 16GB 轻量化本地部署 | Codex |

---

## 15. 复盘后路线图修订（追加 P1 / P2）

> 上一版路线图（§9）只列了"如何跑通"的阶段。复盘后补两个**功能深化**阶段。
> 配套设计文档：`doc/asr-streaming.md`（P1）、`doc/memory-architecture.md`（P2）。

### 15.1 P1：ASR 流式化（游戏中对话核心痛点）

**问题**：whisper.cpp 离线识别等 2-4s 才出结果，游戏喊话体验崩。

**方案**：sherpa-onnx streaming-paraformer-bilingual-zh-en（int8，100MB，CPU 跑）。

**收益**：
- 端到端延迟 1.5-7s → 0.5-1.5s（**3-5x**）
- 部分结果实时显示（每 200ms 刷新）
- 节省 500MB 显存（CPU 跑 + 模型小）
- webui 端 **0 修改**（`asr_response` 协议保持）

**代价**：中文 CER -1%（6% → 7%）。游戏闲聊完全无感。

**工作量**：~350 行 Python + 150 行 PowerShell + 1 个新 doc（`doc/asr-streaming.md`）。

**触发条件**：游戏模式跑通后、用户主观感觉"延迟明显"时启动。

### 15.2 P2：可插拔记忆库（持久化 + 知识注入）

**问题**：原项目记忆 0 持久化、0 外部接口、0 RAG。30 天对话清零，wiki/lore 不能注入。

**方案**：新增 `services/memory-store/` 服务（端口 8996），SQLite + sqlite-vec 默认，可换 Qdrant。
命名空间：`lore:*` `wiki:*` `user:preferences` `chat:summary` `web:cache`。

**收益**：
- 跨 session 共享（重启不丢）
- 预置 wiki 比 web search 快 20-50x
- 角色 lore 总是注入到 system prompt
- webinfer / hermes-api 都能查

**代价**：~500 行 Python + 100 行 PowerShell + 1 个新 doc（`doc/memory-architecture.md`）。
主对话每轮多 50-300ms（embedding + 检索）。**主对话显存无变化**（embedding 走 CPU）。

**工作量**：~500 行 Python + 100 行 PowerShell + 1 个新 doc。

**触发条件**：用户开始问"上次我们聊到哪了" / "BT7274 的过去" / 想要"游戏攻略预置"时启动。

### 15.3 完整路线图（v1.1）

| 阶段 | 时间 | 目标 | 状态 | 阻塞 |
| - | - | - | - | - |
| P0 minimal | 第 1 周 | 主 + webui 跑通 | ⏳ | — |
| P1 default | 第 2-3 周 | ASR/TTS/agent 全开 | ⏳ | — |
| P2 角色化 | 第 4 周 | bt-7274 调通 | ⏳ | — |
| P3 声音克隆 | 第 5 周 | 录一段 + TTS 走克隆声线 | ⏳ | — |
| P4 gaming | 第 6-7 周 | gaming 模式跑通 | ⏳ | — |
| **P1' ASR 流式（新增）** | 第 8 周 | sherpa-onnx 流式替换 | 📝 设计完成 | gaming 调通后 |
| P5 优化 | 第 9+ 周 | 显存压到 12GB | ⏳ | — |
| **P2' 记忆库（新增）** | 第 10+ 周 | memory-store 上线 | 📝 设计完成 | 跑通后任意时 |

---

## 16. 复盘后新增风险（追加到 §10）

> 复盘时新发现 3 个原版 PM 文档未列的风险，必须显式记录。

| 风险 | 概率 | 影响 | 缓解 |
| - | - | - | - |
| **ASR 离线延迟** | 高 | 高（gaming 体验崩） | P1' 迁 sherpa-onnx 流式 |
| **无持久化记忆** | 高 | 中（重启清零） | P2' 上 memory-store |
| **无 RAG / 知识注入** | 中 | 中（不能预置 wiki） | P2' 同步解决 |
| **声音克隆冷启动慢** | 中 | 低 | TTS 服务预热（启动后跑 1 次 dummy synth） |
| **webui 端零修改风险** | 低 | 中 | webui 升级时需要回归测试 5 个端点 + 1 个 WS |
| **多模态精度损失** | 中 | 中 | 主对话关掉 IQ4_NL 的极端温度（建议 0.3-0.7） |

---

## 17. 复盘后修正：原版 90% 可移植估计

> 复盘 `services/webinfer/live_adapter.py`（2935 行）后修正：实际 **100% 跨平台**。
>
> 详细静态扫描见 `doc/tech-local.md` §12。证据：
>
> - 0 处 `signal` / `os.kill` / `fcntl` / `termios` / `tty` / `epoll` / `uvloop` / `subprocess.Popen` / `os.fork` 调用
> - 依赖全是跨平台（aiohttp / openai / PIL / numpy / pathlib）
> - webui 端 WS 协议 Win 上与 Linux 100% 等价
>
> 唯一 Win 注意：**不要装 uvloop**（`pip install uvloop` 会在 import 时崩）。
> 部署 webinfer 等价于改 `python3` → `python` + 重新打开一个 PowerShell 窗口。

---

## 18. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 初版：Windows 5060Ti 16GB 轻量化本地部署 | Codex |
| 2026-07-07 | v1.1 | 追加 §15 P1/P2 路线图、§16 新风险、§17 webinfer 100% 跨平台修正 | Codex |

---

## 19. API 化（突破本地性能天花板）

> 详细方案见 `doc/api-optimization.md`（19.3KB，含协议、成本、3 档策略、隐私分级）。
> 触发：本地 16GB 显存吃紧到 40MB 余量，gaming 模式体验被 ASR/TTS 延迟拖垮。

### 19.1 核心观点

**不是"全上云"也不是"全本地"——按模块独立选**：

| 模块 | 推荐 | 理由 |
| - | - | - |
| **ASR 语音** | **API 化** | 5-10x 延迟降低 + 释放 0.7GB 显存 + 中文 CER SOTA |
| **TTS 语音** | **API 化** | 5-8s 冷启动 → <300ms，释放 1.1GB 显存 |
| **声音克隆** | **API 化** | 5s 样本即可（本地需 0 样本预训练模型） |
| **摘要（纯文本）** | 可选 API | DeepSeek-V3 极便宜（¥1/M tokens） |
| **主对话 VLM** | **保持本地** | 视频帧持续上云成本 ¥540/月，隐私 + 延迟都不划算 |
| **Embedding** | 小数据本地，大数据 API | 按数据量 |
| **Hermes-agent** | 不变 | 本来就远端 200+ provider |

### 19.2 3 档云端策略

| 档位 | 配置 | 月成本（1h/天） | 延迟 | 适合 |
| - | - | -: | - | - |
| 全部本地 | `ASR_BACKEND=local TTS_BACKEND=local` | 0 | 高 | 极致隐私，断网 |
| **语音上云（推荐）** | `ASR_BACKEND=aliyun TTS_BACKEND=volcano` | **¥120** | 低 | 99% 用户 |
| 全部云 | + `VLM_BACKEND=gemini` | ¥800+ | 极低 | 企业 / 性能敏感 |

### 19.3 关键收益

- ASR 1.5-7s → **0.5-1s**（5-10x）
- TTS 5-8s 冷启动 → **<300ms**（20x）
- 释放 **1.8GB 显存**（0.7 ASR + 1.1 TTS）
- 中文 CER -3%（6% → 3%）
- 声音克隆 5s 样本（本地需 0 样本预训练）

### 19.4 关键成本

- 月 ¥120-960（按使用强度）
- 隐私：对话内容 / 语音上云——但本项目摄像头/麦克风本来就是用户主动开
- 可靠性：网络断了自动切本地（fallback < 3s）

### 19.5 隐私分级（用户决策）

启动时弹窗一次性选择，写入 `~\.joyai\privacy.json`：

- 档 1 全部本地：极致隐私
- **档 2 语音上云**（推荐默认）：平衡
- 档 3 全部云：极致性能

### 19.6 路线图修订（v1.2 合并）

| 阶段 | 目标 | 优先级 | 阻塞 |
| - | - | - | - |
| P0 已完成 | 本地部署 | ✅ | — |
| **P1-API 语音上云（新增）** | ASR/TTS 切阿里云+火山 | **🔴 立即** | 用户拍档位 |
| P1-ASR 流式（之前） | 离线→本地流式 | 🟡 降级（API 优先） | P1-API 不做时启动 |
| P2 记忆库 | memory-store | 🟡 | — |
| P2-API 摘要云端（新增） | 摘要切 DeepSeek-V3 | 🟢 按需 | — |
| P3 声音克隆云端（**已升级**） | MiniMax Rapid Clone 10s 样本（唯一）| 🔴 与 P1-API 同步 | — |
| P5 优化 | 显存压到 10GB | 🟢 | P1-API 之后 |

**关键决策**：
- **P1-ASR 流式被 API 化取代**——云端流式比本地流式更好（0.5-1s vs 0.5-1.5s，3% CER vs 7% CER）
- **P3 声音克隆**已统一走 MiniMax Rapid Cloud 唯一（2026-07-09 决策）

### 19.7 决策项（PM 拍板）

- [ ] 选哪一档？默认推荐"档 2 语音上云"
- [ ] 阿里云 vs 火山 vs Azure ASR？默认推荐阿里云
- [ ] 火山 vs ElevenLabs vs OpenAI TTS？默认推荐火山
- [ ] 是否申请各家免费额度试用？阿里云每月 100 小时免费、ElevenLabs 每月 10000 字符
- [ ] 隐私弹窗文案是？（启动一次性确认）

### 19.8 不变的结论

- **主对话 VLM 永远本地**——视频帧不上云是底线
- **webui 端 0 修改**——所有 API 化都在适配器层完成
- **本地作为 fallback**——API 挂了 3s 内自动切回

---

## 20. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 初版 | Codex |
| 2026-07-07 | v1.1 | P1 ASR 流式 + P2 记忆库 + 100% 跨平台修正 | Codex |
| 2026-07-08 | v1.2 | API 化方案：3 档云策略，ASR/TTS/声音克隆 API 化 | Codex |

---

## 21. 推荐供应商与套餐（2026-07-08 调研后）

> 详细对比见 `docs/token-plan-comparison.md`（14.7KB，8 家厂商 + 5 套推荐组合）。
> 配套技术实现：`doc/api-optimization.md §13` + `doc/tech-local.md §14`。

### 21.1 核心结论

> **业界唯一真正"全包"订阅：MiniMax Token Plan**
> （LLM + Agent + 视觉 + TTS + 声音克隆 + 音乐 + 视频，跨模态共享积分）

所有其他厂商（阿里云百炼 / 火山 / 腾讯 / 智谱）都把 TTS/ASR 单独计费；OpenAI / Anthropic / Gemini / Grok 的订阅价格高 3-4 倍但仅含 LLM + 视觉 + Voice。

### 21.2 本项目推荐档

| 档 | 月费 | 组合 | 适合 |
| - | -: | - | - |
| **🟢 省钱** | **¥79** | MiniMax Plus ¥49 + 阿里云 ASR ¥30 | 个人 / 轻量 |
| **🔵 推荐** | **¥149** | MiniMax Max ¥119 + ASR ¥30 | **本项目 / 日常 / gaming** |
| 🟡 重度 | ¥600+ | MiniMax Ultra + 火山 TTS + ASR | 团队 |
| 🟣 海外 | $25 | ChatGPT Plus + ElevenLabs | 海外 |

### 21.3 MiniMax Token Plan 套餐

| 套餐 | 月费 | 资源覆盖 | Agent 用量 |
| - | -: | - | - |
| Plus | **¥49** | M2.7/M3 + 全模态 | 3-4 个 |
| **Max** | **¥119** | M2.7/M3 + 全模态 | 4-5 个 |
| Ultra | ¥469 | + 每日 5 条视频 | 6-7 个 |

**核心承诺**：
- 1,000 积分 = ¥7（与按量付费 1:1 等价）
- **跨模态共享积分**（文本/图像/语音/音乐/视频同池）
- 老用户 ¥29 Starter / ¥98 Plus-极速 档位保留
- M2.7 调用数 +10% + 赠 M3 + 多模态

### 21.4 关键决策

- **本项目主对话 VLM 永远本地**（视频帧不上云）
- **Hermes-agent 可被 MiniMax Max 替代**（中文 SOTA + 全模态）
- **本项目所有云端需求，MiniMax Max ¥119 套餐内基本全覆盖**
- **ASR 用阿里云按量**（¥30/月，比 MiniMax 套餐内便宜）
- **TTS 用 MiniMax Speech 2.8**（套餐内）

### 21.5 决策项

- [ ] 选哪档？**默认推荐 🔵 平衡档 ¥149**
- [ ] 是否完全切换 Hermes-agent → MiniMax Max？保留旧 codex 兜底
- [x] ~~声音克隆用 MiniMax Rapid Clone 还是本地 CosyVoice3？~~ → **已确定 MiniMax Rapid Clone 唯一**（2026-07-09，详见 `voice-clone.md`）
- [ ] 是否申请各家免费额度试用？MiniMax 有 7 天试用
- [ ] 预算上限：¥100 / ¥200 / ¥500？

---

## 22. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 初版 | Codex |
| 2026-07-07 | v1.1 | P1/P2 + 100% 跨平台 | Codex |
| 2026-07-08 | v1.2 | API 化 3 档云策略 | Codex |
| 2026-07-08 | v1.3 | 调研 8 家 token plan，推荐 MiniMax Max ¥119 + ASR ¥30 组合 | Codex |

---

## 23. 声音克隆 7 天保活风险（2026-07-08 补充）

> 用户反馈之前没看到声音克隆细节。详细见 `docs/token-plan-comparison.md §1.3` + `doc/voice-clone.md §1-§10`。

### 23.1 MiniMax Rapid Clone 关键约束

- **价格**：¥9.9 / 被接受的 voice（首次合成扣费，试听免费）
- **套餐内**：Token Plan Max ¥119 套餐赠额 1:1 折算积分，**基本够用**
- **7 天保活**：voice_id 7 天内未调用合成 → 系统自动删除

### 23.2 本项目应对

| 风险 | 概率 | 影响 | 缓解 |
| - | - | - | - |
| BT-7274 角色"备而不用"导致 voice_id 被清 | 中 | 中 | voice_clone_api 月度 cron 合成 1 次任意文本保活 |
| 参考音频上云隐私顾虑 | 低 | 中 | 接受（声音相似度优先 + 0 显存）；隐私敏感场景暂不支持（详见 `api-optimization.md §14.5`）|
| 声音相似度主观 4-4.5/5 不满意 | 低 | 低 | 录 10s 干净单人音频；不行换 ElevenLabs |

### 23.3 云端唯一方案（2026-07-09 决策）

**声音克隆统一走 MiniMax Rapid Clone**，本地 CosyVoice3 双轨已弃用。

```
voice_clone_api (8985) → MiniMax Rapid Clone API（10s 样本，99% 相似）
```

详细工作流见 `doc/voice-clone.md §3`，配置见 `api-optimization.md §14.7`。

### 23.4 决策项（2026-07-09 更新）

- [x] ~~是否录 10 秒 BT-7274 台词作为云端克隆样本？~~ → **是，必须录**（MiniMax 10s 样本要求）
- [x] ~~默认走本地（0 样本）还是云端（10s 样本）？~~ → **云端唯一**（本地 CosyVoice3 已弃用）
- [x] ~~是否接受 7 天保活策略？月度 cron 保活可接受？~~ → **接受**（频繁对话场景无影响；月度 cron 已实现）
- [ ] **待办**：录 10 秒 BT-7274 台词存到 `voices/bt7274/ref.wav`
- [ ] **待办**：订阅 MiniMax Max ¥119 后，云端克隆 ¥9.9/voice 是否在套餐内（应在内）

---

## 24. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 初版 | Codex |
| 2026-07-07 | v1.1 | P1/P2 + 100% 跨平台 | Codex |
| 2026-07-08 | v1.2 | API 化 3 档云策略 | Codex |
| 2026-07-08 | v1.3 | 8 家 token plan 调研 | Codex |
| 2026-07-08 | v1.4 | §23 MiniMax 声音克隆 7 天保活风险 + 双轨方案 | Codex |
| 2026-07-09 | v1.5 | **声音克隆统一云端 MiniMax Rapid Clone**：§21.5/§23.2/§23.3/§23.4 改为云端唯一，本地 CosyVoice3 双轨/hybrid 弃用 | Codex |

---

## 23. Jarvis 模式（2026-07-08 重大更新）

> 详细产品设计：`doc/subsystems/jarvis-mode.md`（26KB）
> 技术实现：`doc/asr-streaming.md`
> 使用指南：`doc/gaming-mode.md`（已升级为 Jarvis 模式）

### 23.1 核心产品定位变化

**原定位**：always-on ASR 监听 + 通用助手
**新定位**：**类钢铁侠贾维斯**——唤醒 + 全双工 + 短指令对话

### 23.2 关键决策

| 决策点 | 选择 | 理由 |
| - | - | - |
| 唤醒词 | **"bt"**（自训 KWS v4 已上线，见 `doc/subsystems/jarvis-mode.md §2.4`） | 3 字 + 强中文特征 + 避开"bt"单字误识别 |
| KWS 引擎 | **sherpa-onnx KWS** | 开源免费、0 网络、1MB 轻量 |
| 对话期 ASR | **sherpa-onnx 流式** | 0 成本 + 0 网络 + 流式首字 200-400ms |
| 结束词 | **"行/明白/了解/ok/好的"** | 5 个明确、互不冲突、与肯定结束语义对应 |
| 退出方式 | **EXIT_WORDS 立即退出** | 静默超时仅作兜底（5s） |
| 打断 | **Barge-in** | ASR partial → TTS pause |
| 事件响应 | **预录 + TTS 生成混合** | wake/goodbye TTS 生成（统一声线），error 复制原文件 |
| 声音克隆源 | `D:\AI\workspace\bt-voice\ref_audio\1.BT-7274\diag_sp_pilotLink_WD141_43_01_mcor_bt.wav` | 用户提供 |
| MiniMax 整合 | **先写程序预留 API** | 激活时再订阅，避免浪费 |

### 23.3 预录事件响应（3 个 wav）

| 文件 | 来源 | 内容 |
| - | - | - |
| `prompts/bt/events/wake.wav` | TTS 生成（BT-7274 声线） | "铁御，我在" |
| `prompts/bt/events/goodbye.wav` | TTS 生成（BT-7274 声线） | "任务完成，断开神经链接" |
| `prompts/bt/events/error.wav` | 复制重命名 | "铁御，必须先建立神经链接才能继续" |

### 23.4 状态机

```
KWS_LISTENING → WAKE_DETECTED → DIALOG_ACTIVE ⇄ TTS_PAUSED
       ↑                                        │
       └────────── EXIT_DETECTED ───────────────┘

(5s 静默兜底：DIALOG_ACTIVE / TTS_PAUSED → 直接归位 KWS_LISTENING，不读出)
```

### 23.5 路线图修订（v1.4）

| 阶段 | 目标 | 优先级 | 状态 |
| - | - | - | - |
| **P0 Jarvis 模式（新增）** | 唤醒 KWS + 流式 ASR + EXIT_WORDS | **🔴 立即** | 设计完成，待实施 |
| P0 之前已规划 | 本地部署 | ✅ | 完成 |
| P1-API 语音上云 | ASR/TTS 切云 | 🟡 降级 | Jarvis 模式优先本地 |
| P2 记忆库 | memory-store | 🟡 | 设计完成 |
| P3 声音克隆云端（**已升级**） | MiniMax Rapid Clone 10s 样本（唯一）| 🟢 按需 | 预留 |

**关键修订**：
- **P0 新增 Jarvis 模式**（KWS 唤醒 + 流式 ASR）
- P1-API 语音上云 **降级**（Jarvis 模式优先本地 0 成本）
- 静默兜底保留（5s 自动退出，不读出）
- **不再"先唤醒再 ASR"**——这是 Jarvis 模式核心

### 23.6 决策项（已拍板）

- [x] 唤醒词 = "bt"（自训 v4 上线 2026-07-10）
- [x] KWS 引擎 = sherpa-onnx
- [x] 对话期 ASR = sherpa-onnx 流式
- [x] EXIT_WORDS = {"行", "明白", "了解", "ok", "好的"}
- [x] wake.wav TTS 生成（统一声线）
- [x] error.wav 复制重命名到 prompts/bt/events/
- [x] 保留静默兜底（5s）
- [x] MiniMax API 预留，先写程序

### 23.7 新增代码 / 文档

**新增**：
- `doc/subsystems/jarvis-mode.md`（26KB，产品设计）
- `services/asr/jarvis/kws.py`（KWS 引擎）
- `services/asr/jarvis/asr.py`（流式 ASR 引擎）
- `services/common/log_with_timestamp.py`（时间戳日志）
- `services/scripts/generate_event_audio.py`（事件音频生成）
- `prompts/bt/events/wake.wav`（生成）
- `prompts/bt/events/goodbye.wav`（生成）
- `prompts/bt/events/error.wav`（复制）

**改写**：
- `doc/asr-streaming.md`（与 jarvis-mode 协同）
- `doc/gaming-mode.md`（升级为 Jarvis 模式）
- `doc/api-optimization.md §15`（ASR 选型修订）

**实施工作量**：~700 行 Python + 150 行 PowerShell + 3 个 wav 生成

---

## 24. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 初版 | Codex |
| 2026-07-07 | v1.1 | P1/P2 + 100% 跨平台 | Codex |
| 2026-07-08 | v1.2 | API 化 3 档云策略 | Codex |
| 2026-07-08 | v1.3 | 8 家 token plan 调研 | Codex |
| 2026-07-08 | v1.4 | **Jarvis 模式（重大更新）**：唤醒 KWS + 流式 ASR + EXIT_WORDS | Codex |

## 25. P2 记忆持久化（2026-07-09 决策落地）

### 25.1 目标

- 会话结束不丢记忆（mid_term 摘要）
- 外部知识库可注入（obsidian wiki / 角色 lore）
- 不破坏进程内 dict 的速度

### 25.2 关键决策

| 项 | 决定 | 理由 |
|---|---|---|
| 架构 | **B 方案**：中间件 memory-store（:8996），进程内 dict 不动 | A 太轻，C 太重；B 兼容现有架构 |
| namespace 字段 | **彻底删除**（YAGNI） | 后续要加 = 15 行代码（半天），现在付复杂度不值 |
| 协作方式 | **A 推/拉对称**：kill 时 push，启动首轮 pull | 崩溃窗口丢失可接受（jsonl 兜底） |
| Embedding | 本地 bge-m3（RTX 5060 Ti 16GB 富余） | 与 OpenAI text-embedding-3-large 中文基本打平 |
| 排期 | P2-1 → P2-3 → P2-2 | 持久化最痛优先；embedding 是 RAG 前置 |
| 持久时机 | 会话结束（kill hook）整批 push | 不阻塞 30s 内完成 |
| 召回时机 | 启动首轮（pull hook）按 query 拉 | 空 dict 启动，按需加载 |

### 25.3 排期

| 阶段 | 工作量 | 依赖 | 验收 |
|---|---|---|---|
| **P2-1** memory-store 骨架 + psql backend | 2-3 天 | 0 | 推/拉接口能跑通 |
| **P2-1.1** live_adapter kill hook + push | 0.5 天 | P2-1 | kill 后 psql 能查到块 |
| **P2-1.2** live_adapter start hook + pull | 0.5 天 | P2-1 | 启动时空 dict，首轮 query 后自动召回 |
| **P2-3** bge-m3 本地服务（FastAPI :8997） | 1 天 | 0 | 30ms/查询 |
| **P2-2** 向量检索集成 + obsidian 同步 | 2-3 天 | P2-1, P2-3 | recall 接口能搜到 obsidian 内容 |

**总工作量：~10 天**，分两周迭代。

### 25.4 旧设计 v1 → 新设计 v3.1 主要变更

| 章节 | v1 | v3.1 |
|---|---|---|
| §1.1 记忆现状 | "0 记忆" | "3 层进程内记忆 + 无持久化"（修正事实） |
| §2.1 架构 | 单一 memory-store | 推/拉对称 + 3 backend（psql/sqlite/obsidian） |
| §2.2 隔离 | namespace 字段 | 删除（YAGNI） |
| §3 API | /v1/memory/search | /v1/blocks/push + /v1/blocks/recall |
| §5.1 后端 | sqlite-vec 优先 | psql 优先（复用 hermes） |
| §5.2 备选 | Qdrant | 删除（不需要） |
| §5.4 embedding | bge-small-zh-v1.5 | **bge-m3**（多语种 + 8192 token） |

### 25.5 关联文档

- `doc/memory-architecture.md`（v3.1 完整设计）
- `doc/tech-local.md` §18（P2 技术实现）
- `services/background-agent/hermes_api/main.py`（psql 复用点）

### 25.6 风险

- bge-m3 下载失败 → 备选 bge-large-zh-v1.5
- 检索不准 → 调 min_score 阈值
- 注入太多稀释决策 → 限制 top_k=8、token 上限 2000
- psql 不可用 → 自动降级 sqlite
- 异常崩溃丢 push → 接受（jsonl 兜底）

---

## 26. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-09 | v1.5 | **§25 P2 记忆持久化决策落地**：B 方案 + 推/拉对称 + bge-m3 + 删 namespace + psql 优先 | Codex |

---

## 25. 屏幕捕获 + Hermes 隔离（2026-07-09）

> 详细方案：
> - `doc/screen-capture.md`（9.3KB）
> - `doc/hermes-integration.md`（10.5KB）

### 25.1 屏幕捕获（getDisplayMedia）

| 决策 | 选择 | 理由 |
| - | - | - |
| 方案 | **浏览器 getDisplayMedia** | 0 后端改动 + 与 webui 完美集成 + 延迟 <100ms |
| `displaySurface` | **"window"** | 只让用户选窗口，不要整屏（隐私） |
| `frameRate` | **1 fps** | 与 VLM 1 fps 视频流对齐 |
| `audio` | **false** | 不要系统音频（避免 TTS 反馈到 mic） |

**实施工作量**：~2 小时（前端 ~50 行 + Python ~20 行）。

### 25.2 Hermes 严格隔离

**核心原则**：Hermes 是"工具层"，不是"角色层"。

| 维度 | 隔离方式 |
| - | - |
| 人格 | shim 不传 system 字段给 hermes（让 hermes 用自己的 SOUL.md） |
| 记忆 | Hermes 自己的 MEMORY.md / USER.md vs BT-7274 自己的 memory-store（命名空间隔离） |
| Skills | 独立命名空间，不共享 |
| Provider | shim 不维护，委托给 hermes gateway，用户用 `hermes model` 切换 |

**好处**：
- 调用更快（不解析 BT-7274 人格/记忆）
- 故障隔离（Hermes 挂了 BT-7274 仍能工作）
- 升级独立（Hermes 升级不影响 BT-7274）
- 人格纯粹

### 25.3 路线图修订（v1.5）

| 阶段 | 目标 | 优先级 | 状态 |
| - | - | - | - |
| P0 Jarvis 模式 | 唤醒 KWS + 流式 ASR | 🔴 立即 | 设计完成 |
| **P1 屏幕捕获（新增）** | getDisplayMedia | 🟡 | 设计完成 |
| **P1 Hermes 隔离（新增）** | 严格隔离 shim | 🟡 | 设计完成 |
| P2 记忆库 | memory-store | 🟡 | 设计完成 |
| P3 声音克隆云端（**已升级**） | MiniMax Rapid Clone 10s 样本（唯一）| 🟢 按需 | 预留 |

### 25.4 决策项（已拍板）

- [x] 屏幕捕获 = getDisplayMedia
- [x] Hermes 严格隔离（人格/记忆/Skills/Provider 全部独立）
- [x] shim 不传 system 字段
- [x] shim 不维护 provider（用户用 `hermes model` 切换）
- [x] webui 端 `/v1/solve` 契约不变

---

## 26. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 初版 | Codex |
| 2026-07-07 | v1.1 | P1/P2 + 100% 跨平台 | Codex |
| 2026-07-08 | v1.2 | API 化 3 档云策略 | Codex |
| 2026-07-08 | v1.3 | 8 家 token plan 调研 | Codex |
| 2026-07-08 | v1.4 | Jarvis 模式（重大更新） | Codex |
| 2026-07-09 | v1.5 | 屏幕捕获 + Hermes 严格隔离 | Codex |
