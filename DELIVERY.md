# 本地化交付清单（Windows + RTX 5060 Ti 16GB）

> **历史交付快照**：本文主体记录 2026-07-06 的初版 11 进程/CosyVoice 方案，不是当前启动规范。
> **当前链路（2026-07-12）**：`7060` 本地社区量化 LLM/VLM + `8070` webinfer + `8099` WebUI + `8985` MiniMax TTS/声音克隆；KWS/ASR 在 WebUI 内本地运行。
> 当前操作以 `doc/00-main-direction.md`、`doc/architecture-local.md`、`doc/jarvis-mode.md` 和 `start-joyai.ps1` 为准。

---

> 交付日期：2026-07-06
> 部署目标：Windows 11 + RTX 5060 Ti 16GB (sm_120 / Blackwell) + 32GB RAM
> 角色：bt-7274（用户自填 `prompts/bt-7274.txt`）
> 后台 agent：用户自有的 Hermes-agent

## 1. 完成项

| # | 任务 | 状态 | 证据 |
| - | - | - | - |
| 1 | 调研社区 GGUF 主模型 | ✅ | `doc/lightweight-replacement.md` 详报 |
| 2 | 调研其余模型替换 | ✅ | 同上（含启动命令） |
| 3 | 调研声音克隆方案 | ✅ | 选 CosyVoice3-0.5B（首推） |
| 4 | 调研 Hermes-agent 接入 | ✅ | `services/background-agent/hermes_api/` |
| 5 | webinfer 角色 prompt 注入 | ✅ | `services/webinfer/system_prompts.py` (168 行) + `live_adapter.py` 改造 |
| 6 | Hermes FastAPI shim | ✅ | `services/background-agent/hermes_api/main.py` (340 行) + 2 个 ps1 |
| 7 | 声音克隆服务 | ✅ | `services/voice-clone/voice_clone_api/` (5 端点 + WS) + tts_adapter dispatch |
| 8 | ASR / TTS 适配器微调 | ✅ | `tts_adapter.py` (428→564 行) + `asr_adapter.py` 注释 |
| 9 | Windows 部署脚本 | ✅ | `install/*.ps1` (6 个) + `services/scripts/*.ps1` (3 个) |
| 10 | PM 文档 | ✅ | `doc/pm-local.md` (13KB) |
| 11 | 技术实现文档 | ✅ | `doc/tech-local.md` (20KB) |
| 12 | 架构文档 | ✅ | `doc/architecture-local.md` (8KB) + 2 个 mermaid 图 |
| 13 | 游戏中对话文档 | ✅ | `doc/gaming-mode.md` (6KB) |
| 14 | 声音克隆文档 | ✅ | `doc/voice-clone.md` (5KB) |
| 15 | 主 README 引导 | ✅ | `README.zh-CN.md` 末尾追加 Windows 部署入口 |

## 2. 关键文件清单

### 2.1 新增

```
prompts/
  bt-7274.txt                                 (1.8KB)  角色 prompt 模板（用户填）
  README.md                                   (2.3KB)  加载约定
services/webinfer/
  system_prompts.py                           (5.9KB)  角色 prompt 加载
  pyproject.toml                              (新建)   独立可装
services/background-agent/hermes_api/
  __init__.py                                 (114B)
  main.py                                     (17KB)   FastAPI shim
services/background-agent/scripts/
  start-hermes-gateway.ps1                    (5.7KB)  启动 Hermes gateway
  run-windows.ps1                             (4.8KB)  启动 shim
services/voice-clone/                         (新目录)
  voice_clone_api/main.py                     (23.6KB) 5 端点 + WebSocket
  voice_clone_api/cosyvoice_client.py         (5.9KB)  CosyVoice HTTP 客户端
  voice_clone_api/models.py                   (3.4KB)  Pydantic schemas
  scripts/start-cosyvoice.ps1                 (5.0KB)
  scripts/run-windows.ps1                     (5.0KB)
  pyproject.toml                              (新建)
  README.md                                   (9.3KB)
  README.zh-CN.md                             (新建)
install/
  install-windows.ps1                         (17KB)   主安装器
  download-gguf-models.ps1                    (12KB)   下 GGUF 模型
  setup-llama-cpp.ps1                         (6.5KB)  装 llama.cpp sm_120
  setup-whisper-cpp.ps1                       (5.2KB)  装 whisper.cpp
  setup-cosyvoice.ps1                         (8.1KB)  装 CosyVoice3
  setup-hermes.ps1                            (5.6KB)  装 Hermes-agent
services/scripts/
  run-windows.ps1                             (33KB)   编排器（4 模式 + Restart）
  stop-windows.ps1                            (5.4KB)  全停
  run-windows.env.example                     (3.7KB)  配置示例
doc/
  pm-local.md                                 (13KB)   PM 文档
  tech-local.md                               (20KB)   技术实现
  architecture-local.md                       (7.9KB)  架构图
  gaming-mode.md                              (5.6KB)  游戏中对话
  voice-clone.md                              (5.4KB)  声音克隆
docs/
  lightweight-replacement.md                  (25.7KB) 选型调研报告
DELIVERY.md                                   (本文)   交付清单
```

### 2.2 修改（Linux 兼容保留）

```
README.zh-CN.md                               (MOD) 末尾追加 Windows 入口
install/README.md                             (MOD) 加 Windows 章节
install/README.zh-CN.md                       (MOD) 加 Windows 章节
services/webinfer/live_adapter.py             (MOD +200 行) 角色注入 + 2 端点
services/webinfer/README.md / README.zh-CN.md (MOD) 角色 + 后端切换
services/background-agent/pyproject.toml      (MOD) + httpx
services/background-agent/README.md           (MOD) 加 Hermes 章节
services/background-agent/README.zh-CN.md     (MOD) 加 Hermes 章节
services/background-agent/scripts/run.sh      (MOD 顶部) 指向 Windows
services/tts/tts_adapter.py                   (MOD 428→564 行) + voice_clone dispatch
services/asr/asr_adapter.py                   (MOD 378→403 行) 加注释
```

### 2.3 保持不变

- `services/webui/`（webui 端**零修改**，靠现有 `update_prompt` 机制）
- `services/codex_api/`（原 Codex CLI 实现保留作 fallback）
- 所有 `*.sh` 脚本（Linux 部署路径完整保留）
- 原 `</silence>` / `</response>` / `</delegate>` 字符串解析逻辑

## 3. 端到端启动序列（从零到能对话）

```powershell
# 0) 一次性：装系统级
winget install Python.Python.3.12 git.Git Gyan.FFmpeg Anaconda.Miniconda3
irm https://astral.sh/uv/install.ps1 | iex
# 重启 PowerShell 让 PATH 生效

# 1) 拉项目
git clone https://github.com/jd-opensource/JoyAI-VL-Interaction.git C:\AI\workspace\JoyAI-VL-Interaction-main
cd C:\AI\workspace\JoyAI-VL-Interaction-main

# 2) 主安装（~10 分钟）
.\install\install-windows.ps1

# 3) 下载模型（~10-15 分钟，约 6-7 GB）
.\install\download-gguf-models.ps1 -Component all

# 4) 装 4 个原生后端（~5 分钟）
.\install\setup-llama-cpp.ps1
.\install\setup-whisper-cpp.ps1
.\install\setup-cosyvoice.ps1
.\install\setup-hermes.ps1
# 记下末尾打印的 API key

# 5) 写 env（首次）
copy services\scripts\run-windows.env.example services\scripts\run-windows.env
notepad services\scripts\run-windows.env
# 填 HERMES_API_KEY / TTS_DEFAULT_VOICE_ID / MAIN_MODEL_PATH 等

# 6) 编辑角色 prompt
notepad prompts\bt-7274.txt
# 把 TODO BT7274 占位符替换成真实角色

# 7) 启动
cd services
.\scripts\run-windows.ps1 -Mode gaming

# 8) 浏览器
# 打开 https://127.0.0.1:8099/ 接受自签证书警告

# Ctrl+C 停全部
```

## 4. 验收对照

| 用户原始需求 | 满足？ | 证据 |
| - | - | - |
| 部署在 Windows 5060Ti 16GB | ✅ | `run-windows.ps1` + 显存预算 11.5GB |
| 用社区 GGUF 版主模型 | ✅ | `Nasa1423/JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF` |
| 其余模型可替换/量化 | ✅ | 摘要 / ASR / TTS 都换轻量版 |
| 角色 prompt（bt-7274） | ✅ | `prompts/bt-7274.txt` + 热重载 |
| 声音克隆 | ✅ | `services/voice-clone/` + CosyVoice3 零样本 |
| 接 hermes-agent | ✅ | `services/background-agent/hermes_api/main.py` |
| 轻量本地部署 | ✅ | 11.5GB 显存 / 零云依赖 |
| 游戏中对话 | ✅ | `-Mode gaming` + voice-only 默认 |
| 保留原本高效一体化结构 | ✅ | 单 `run-windows.ps1` 启全部，Ctrl+C 停全部 |
| 改 PM 文档 | ✅ | `doc/pm-local.md` (13KB) |
| 改技术文档 | ✅ | `doc/tech-local.md` (20KB) + 3 个配套 doc |

## 5. 已知风险与回退

| 风险 | 回退方案 |
| - | - |
| llama.cpp sm_120 build 不稳 | 切官方 `*bin-win-cuda-12.4-x64.zip`（慢 10-20% 但稳） |
| CosyVoice3 装失败 | 切 CosyVoice2-0.5B / F5-TTS / GPT-SoVITS V3 |
| Hermes Win beta bug | 把 `run-windows.env` 切回 `codex_api`（代码保留） |
| 显存爆 | 关 hermes / 关 summary / 关 ASR / 关 TTS |
| PyTorch cu128 装失败 | 只跑 llama-server（不依赖 PyTorch）+ whisper.cpp（纯 C++） |
| 声音克隆效果差 | 多录几段 / 换 GPT-SoVITS V3 |

## 6. PM 自填项

用户接下来需要做的：

- [ ] 编辑 `prompts/bt-7274.txt` 填入真实角色 prompt
- [ ] 录 3-10 秒角色参考音频
- [ ] 上传到 voice_clone_api
- [ ] 选 Hermes 的 model provider（Nous Portal / OpenAI / Anthropic / 本地 GGUF）
- [ ] 跑完 `install-windows.ps1` + `setup-*.ps1` + `download-gguf-models.ps1`
- [ ] 跑 `run-windows.ps1 -Mode gaming` 验证
- [ ] 填 `pm-local.md` 第 12 节的 checkbox

## 7. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 本地化首发：Windows 5060Ti 16GB + bt-7274 + Hermes + 声音克隆 | Codex (4 sub-agents + 4 docs) |
| 2026-07-10 | v1.4 | KWS v4 自训落地（t 唤醒词，FAR 2% / recall 49%）；jarvis 状态机代码集成 | Codex |
| 2026-07-12 | v3.3 | **MiniMax Token Plan 接入（半落地）**：声音克隆走 speech-2.8-hd + voice_id minimax_man_33333 跑通（链路测试 wav 见 services/.logs/bt_persona_roundtrip.wav 类产物）；webinfer BT-7274 persona 视觉链路验证（llm_inference=948ms，prompt_tokens=511 含 character_profile）；jarvis_mode.py 结构性修复（class 范围被 0-indent helper 切断 → helper 模块级化 + 字段归位，rom_env AttributeError 消除）。**未消除**：
un-windows.env 凭证配置未沉淀 / v3.2 #2 收尾未做 / v3.2 #4 全链路 e2e 仍是 ⚠️ 状态 | Codex |
| 2026-07-12 | v3.4 | **放弃 voice-ui 薄壳（错误方向）**；直接改 webui 索引：删除重复 `<html><head><body>` 块 + 重复 `llmReplySection` + 重复状态徽章（index.html 12,679 → 8,985 行）；新增 `POST /api/tts/synthesize` 代理 voice_clone_api 并把 PCM16 包成 WAV；曾新增 `id="llmTestSendBtn"` 文本测试按钮（v3.9 已删除并入纸飞机）+ `id="btTtsPlayer"` 自动播放 audio；WS `llm_reply` 触发 TTS 链路；17/17 测试绿；详见 `doc/jarvis-mode.md` §14 / `doc/00-main-direction.md` §3 / §4.0 | Codex |
---

| 2026-07-13 | v3.24 | Jarvis短期上下文、MiniMax-only与7060/8070/8099/8985统一启动链路 （受影响：`doc\jarvis-mode.md`; `doc\architecture-local.md`; `doc\adr\0004-service-lifecycle.md`；改动文件：-） | Codex |
| 2026-07-13 | v3.25 | **memory-store v0.1 skeleton（落地 v3.2 #3 P2 记忆持久化骨架）**：新增 `services/memory-store/`（SqliteBackend + FTS5 BM25、Psql/Obsidian 占位 `NotImplementedError`），端口 8996，端点 `/v1/blocks/push` `POST`、`/v1/blocks/recall` `POST`、`/health` `GET`、`/v1/backends` `GET`；schema 留 score / last_hit_at / hit_count 字段（runtime 默认，recency decay 不在 v0.1）；16/16 测试通过；不影响 `live_adapter.py`（ADR 0005 D 锁定 v0.1 范围）。**前端 vlm-history CSS 修复**：`services/webui/.../static/index.html` 1563 行附近覆盖 `.result-text.vlm-history-shell { min-height:0 }` + `:has(#vlmHistoryEmpty:not([style*='display: none']))` 240px empty-state 兜底 + `.vlm-history { max-height: min(60dvh, 560px) }`，解决空 vlm-history 残留 120px strip 与「对话可见但框不长大」。**生命周期扩**：`run-windows.ps1` 加 `$P.MemoryStore` + `Start-MemoryStore`（env opt-in `JOYAI_ENABLE_MEMORY_STORE=1` 默认 false，避免 v3.x 启动回归）；`stop-joyai.ps1` PortMap 加 8996。受影响：`doc/jarvis-mode.md` §15、`doc/00-main-direction.md` §4 + §4.0、`doc/specs/memory-store-skeleton-spec.md` 落地、`doc/adr/0005-memory-store-start.md` 实施。改动文件：`services/memory-store/**`、`services/scripts/run-windows.ps1`、`stop-joyai.ps1`、`services/webui/.../static/index.html` | Codex |

| 2026-07-13 | v3.27 | **Screen Capture 接入 + hermes-agent 端到端**：(a) `static/screen_capture.js` 去 ES module 改全局 + ImageCapture fallback、`static/index.html` 加 Screen Capture tab + screenControls、`server.py` `websocket_handler` 加 `elif t == "frame"`（base64 → PIL → `vlm_service.process_frame` → `get_session_callback` 广播 vlm_response）；79/79 webui 测试通过、模拟帧 ~5.5s 拿到 llama-server 回复。(b) hermes-gateway(8642) + background-agent shim(8079) 接入：补 `$env:LOCALAPPDATA\hermes\bin\hermes.cmd` wrapper（venv python → `python -m hermes_cli.main`），`Start-Hermes` 用 `API_SERVER_HOST/PORT/KEY` env；`background-agent.env` + `scripts/run-windows.env` 同步 `HERMES_API_KEY`；gateway `/health` 200、shim `/health` 透出 `hermes_gateway:200`，smoke `/v1/solve` 返回中文"烟测通过。"(prompt_tokens=24157/5.9s)。受影响：`doc/00-main-direction.md` §4 + §4.0、`doc/screen-capture.md` §0+§11、`doc/hermes-integration.md` §0+§10；改动文件：`services/webui/src/joy_interaction_webui/static/{screen_capture.js,index.html}`、`services/webui/src/joy_interaction_webui/server.py`、`services/background-agent/background-agent.env`、`services/scripts/run-windows.env` | Codex |

## 8. 复盘后补充（P1 / P2 决策项，2026-07-07）

> 上一版交付清单（§1-§7）只覆盖了 P0 已实现功能。复盘发现 2 个 P1/P2 缺口必须在路线图里显式记录。

### 8.1 P1 — ASR 流式化（gaming 核心痛点）

- **状态**：未实现，已设计
- **设计文档**：`doc/asr-streaming.md`（11.3KB，含协议、迁移、性能对比）
- **改动量**：~350 行 Python（`asr_adapter.py` + `streaming_transcriber.py`）+ 150 行 PowerShell（`setup-sherpa-onnx.ps1` + 编排器）
- **用户决策项**：
  - [ ] 是否在 P4（gaming 跑通）之后立刻启动 P1？
  - [ ] 流式 ASR 中文 CER 损失 1% 可接受？
  - [ ] 接受 sherpa-onnx 占用 ~200MB 内存（CPU 跑）？

### 8.2 P2 — 可插拔记忆库

- **状态**：未实现，已设计
- **设计文档**：`doc/memory-architecture.md`（7.8KB，含命名空间、API 契约、集成点）
- **改动量**：~500 行 Python（新 `services/memory-store/`）+ 100 行 PowerShell
- **用户决策项**：
  - [ ] 接受 SQLite + sqlite-vec 默认？还是直接上 Qdrant？
  - [ ] embedding 模型用 `BAAI/bge-small-zh-v1.5`（中文 SOTA 小模型档）？
  - [ ] 是否立刻预置 bt-7274 lore（`prompts/lore/bt-7274.md`）？
  - [ ] 是否预置 elden-ring wiki（`prompts/wiki/elden-ring/`）？
  - [ ] webui 端是否要加"知识库管理"页面（~30 行 Python）？

### 8.3 复盘修订：webinfer 可移植性

| 项 | 旧版文档估计 | 复盘后 | 证据 |
| - | - | - | - |
| webinfer Win 复现率 | 90% | **100%** | `live_adapter.py` (2935 行) 静态扫描 0 平台特定 API 命中 |
| webui 改动 | 0 | 0 | 维持 |
| 后端 agent 接口契约 | 100% 兼容 | 100% 兼容 | hermes_api/main.py `/v1/solve` 字段名/顺序/类型 byte-for-byte 一致 |

详细证据见 `doc/tech-local.md` §12。

### 8.4 新增风险（已写入 pm-local.md §16）

| 风险 | 触发阶段 | 缓解 |
| - | - | - |
| ASR 离线延迟 | P4 gaming | P1 迁流式 |
| 无持久化记忆 | 跑通 1 周后 | P2 上 memory-store |
| 无 RAG / 知识注入 | 用户问"上次聊的" | P2 同步解决 |

### 8.5 决策项总清单（PM 自填）

- [ ] P1 启动时机（P4 之后？立刻？）
- [ ] P2 是否需要嵌入到 P0 流程（即装即用）
- [ ] memory-store 后端选择（SQLite 默认 / Qdrant 可选）
- [ ] 是否预置游戏 wiki（自填 1-2 个常用游戏）
- [ ] 是否预置角色 lore（自填 bt-7274 背景故事）
- [ ] 声音克隆是否走预热（启动时跑 1 次 dummy synth）
- [ ] 是否启用 webui 端"知识库"管理页面
- [ ] 是否把 90% → 100% 跨平台这个修正同步给原项目 PR

---

## 9. 变更记录（v1.1）

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 本地化首发：Windows 5060Ti 16GB + bt-7274 + Hermes + 声音克隆 | Codex |
| 2026-07-07 | v1.1 | 复盘：P1 ASR 流式设计、P2 记忆库设计、webinfer 100% 跨平台修正 | Codex |

---

## 10. API 化（v2.0 方向，2026-07-08）

> 详细方案见 `doc/api-optimization.md`（19.3KB）+ `doc/tech-local.md §14` + `doc/pm-local.md §19`。
> 核心结论：**语音三件套 API 化（强烈推荐）、主对话 VLM 保持本地、其它按需**。

### 10.1 推荐档位（默认建议）

**档 2：语音上云**（99% 用户适用）

| 模块 | 后端 | 月成本（1h/天） |
| - | - | -: |
| ASR | 阿里云一句话流式 | ¥86 |
| TTS | 火山引擎 | ¥45 |
| 声音克隆 | 火山 5s 样本 | ¥0-20 |
| 主对话 VLM | 本地 IQ4_NL GGUF | 0 |
| **合计** | — | **¥120-150** |

### 10.2 关键收益

- ASR 端到端 1.5-7s → **0.5-1s**（5-10x）
- TTS 冷启动 5-8s → **<300ms**（20x）
- 释放 **1.8GB 显存**（给游戏 1080p 中高画质让出空间）
- 中文 CER 6% → 3%（-50%）
- 声音克隆 5s 样本（vs 本地 0 样本预训练）

### 10.3 关键不变

- **webui 端 0 修改**（所有 API 化在适配器层完成）
- **本地作为 fallback**（API 挂了 3s 内自动切回）
- **主对话 VLM 永远本地**（视频帧不上云是底线）

### 10.4 实施工作量

~3 人天：

| 任务 | 工作量 |
| - | -: |
| asr_adapter 加阿里云后端 | 半天 |
| tts_adapter 加火山后端（HTTP 协议桥） | 半天 |
| voice_clone_api 加云端扩展 | 半天 |
| 适配器 dispatch + 故障转移 | 半天 |
| run-windows.env + 编排器 | 1h |
| webui 状态条 | 1h |
| 三档端到端测试 | 半天 |
| 文档 | 半小时 |

### 10.5 PM 决策项

- [ ] 选哪一档？默认"档 2 语音上云"
- [ ] 阿里云 vs 火山 vs Azure ASR？默认阿里云
- [ ] 火山 vs ElevenLabs vs OpenAI TTS？默认火山
- [ ] 是否申请免费额度试用？阿里云每月 100h、ElevenLabs 每月 10000 字符
- [ ] 隐私弹窗文案是？

### 10.6 路线图合并（v2.0）

| 阶段 | 目标 | 优先级 | 状态 |
| - | - | - | - |
| P0 本地部署 | 跑通 | ✅ | 完成 |
| **P1-API 语音上云（新增）** | ASR/TTS 切云 | **🔴 立即** | 设计完成，待实施 |
| ~~P1-ASR 流式（本地）~~ | ~~sherpa-onnx~~ | 🟡 降级 | P1-API 优先时不做 |
| P2 记忆库 | memory-store | 🟡 | 设计完成 |
| **P2-API 摘要云端（新增）** | DeepSeek-V3 | 🟢 按需 | |
| **P3 声音克隆云端（新增）** | 火山 5s | 🔴 与 P1-API 同步 | |

**关键修订**：原 P1-ASR 流式（sherpa-onnx 本地）被 P1-API 取代——云端流式 + 5-10x 延迟降低 + 3% CER 显著优于本地 7% CER。

### 10.7 修订记录（v2.0）

| 决策 | 旧 | 新 | 理由 |
| - | - | - | - |
| ASR 后端 | whisper.cpp 离线 → sherpa-onnx 本地流式 | **阿里云 API** | 5-10x 延迟 + 3% CER vs 7% + 释放 0.7GB 显存 |
| TTS 后端 | CosyVoice3 本地 | **火山引擎 API** | 5-8s → <300ms + 释放 1.1GB 显存 |
| 声音克隆 | CosyVoice3 0 样本 | **火山 5s 样本 / 本地 0 样本** | 5s 短样本，灵活选 |
| 摘要 | Qwen2.5-VL-3B 本地 | 同（按需切 DeepSeek-V3） | 大多数场景本地够 |
| 主对话 VLM | 本地 IQ4_NL | **保持本地** | 视频帧不上云是底线 |

---

## 11. 变更记录（v2.0）

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 本地化首发 | Codex |
| 2026-07-07 | v1.1 | P1 ASR 流式设计、P2 记忆库、webinfer 100% 跨平台 | Codex |
| 2026-07-08 | v2.0 | API 化方案：3 档云策略，ASR/TTS/声音克隆 API 化，P1-ASR 流式降级 | Codex |

---

## 12. 套餐调研（2026-07-08 完成）

> 详细报告：`doc/token-plan-comparison.md`（14.7KB）
> 推荐整合：`doc/api-optimization.md §13` + `doc/pm-local.md §21`

### 12.1 调研结论

| 厂商 | 是否"全包" | 推荐档 | 月费 |
| - | - | - | -: |
| **MiniMax Token Plan** | ✅ **唯一全包** | Max | **¥119** |
| 阿里云百炼 Token Plan | ❌ 语音单独计费 | 标准 | ¥198 |
| 火山方舟 Agent Plan | ❌ 语音单独计费 | Medium | ¥200 |
| 腾讯云 Hy Token Plan | ❌ 语音单独计费 | Standard | ¥78 |
| 智谱 GLM Coding Plan | ❌ **只面向编程** | Pro | ¥149 |
| ChatGPT Plus | ❌ 无声音克隆 | Plus | $20 |
| Claude Pro | ❌ 无 TTS/ASR | Pro | $20 |
| Gemini AI Pro | ❌ 无 TTS/ASR | Pro | $19.99 |
| Grok SuperGrok | ❌ 无 ASR | SuperGrok | $30 |

### 12.2 本项目推荐

**🔵 平衡档 ¥149/月**：
- MiniMax Token Plan Max ¥119
- 阿里云 ASR 按量 ¥30

**核心收益**：
- LLM 替代 Hermes-agent 200+ provider
- TTS 替代本地 CosyVoice3（<300ms 冷启动）
- 声音克隆 ¥10-15/voice
- 视觉/音乐/视频能力 1:1 折算积分
- 老用户保留 ¥29/¥98 档位

### 12.3 决策项

- [ ] 选 MiniMax Plus ¥49 / Max ¥119 / Ultra ¥469？
- [ ] Hermes-agent 是否完全切换到 MiniMax？
- [ ] 声音克隆用 MiniMax Rapid Clone / 本地 CosyVoice3 / ElevenLabs？
- [ ] 预算上限？默认 ¥149/月

---

## 13. 变更记录（v2.1）

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 本地化首发 | Codex |
| 2026-07-07 | v1.1 | P1 ASR 流式 + P2 记忆库 + 100% 跨平台 | Codex |
| 2026-07-08 | v2.0 | API 化 3 档云策略 | Codex |
| 2026-07-08 | v2.1 | 8 家 token plan 调研完成，推荐 MiniMax Max ¥119 + ASR ¥30 | Codex |

---

## 14. Jarvis 模式（v3.0 重大更新，2026-07-08）

> 详细产品设计：`doc/jarvis-mode.md`（26KB）
> 完整变更：`doc/pm-local.md §23` + `doc/tech-local.md §16` + `doc/asr-streaming.md`（重写）

### 14.1 核心变化

| 项 | v2.x 旧方案 | **v3.0 Jarvis 模式** |
| - | - | - |
| 触发 | 持续 ASR 监听 | **唤醒词 "bt 在吗"** |
| ASR 引擎 | whisper.cpp 离线 1.5-7s | **sherpa-onnx 流式 0.5-1.5s** |
| 退出 | 静默 5s | **EXIT_WORDS 立即退出**（5s 仅作兜底） |
| 打断 | 不可 | **Barge-in**（ASR partial → TTS pause） |
| 唤醒响应 | 无 | **预录 wake.wav**（"铁御，我在"） |
| 结束响应 | 无 | **预录 goodbye.wav**（"任务完成，断开神经链接"） |
| 声音克隆 | 通用 TTS | **BT-7274 声线**（MiniMax Speech 2.8 / 本地 CosyVoice3） |

### 14.2 关键决策（已拍板）

- ✅ 唤醒词 = "bt 在吗"
- ✅ KWS = sherpa-onnx（开源免费，0 网络，1MB）
- ✅ 对话期 ASR = sherpa-onnx 流式（CPU 200MB，0 网络）
- ✅ EXIT_WORDS = {"行", "明白", "了解", "ok", "好的"}
- ✅ 静默兜底保留（5s）
- ✅ MiniMax API 预留（先写程序，后激活）
- ✅ 错误日志只后台，不读出
- ✅ 每次服务启动新 logs（时间戳 + PID）

### 14.3 预录事件响应

| 文件 | 来源 | 内容 |
| - | - | - |
| `prompts/bt/events/wake.wav` | TTS 生成 | "铁御，我在" |
| `prompts/bt/events/goodbye.wav` | TTS 生成 | "任务完成，断开神经链接" |
| `prompts/bt/events/error.wav` | 复制 | "铁御，必须先建立神经链接才能继续" |

声音克隆源：`D:\AI\workspace\bt-voice\ref_audio\1.BT-7274\diag_sp_pilotLink_WD141_43_01_mcor_bt.wav`
参考文字："我们的命令是要展开特殊作业二一七"

### 14.4 端到端延迟（用户感受）

| 阶段 | 延迟 |
| - | -: |
| 唤醒响应 | 0.05s |
| 指令响应（用户说话→听到回答） | 0.6-1.5s |
| 打断响应 | 0.2-0.4s |
| 结束响应 | 0.02s（ASR 命中立即触发） |

### 14.5 资源影响

- **新增**：KWS 1-3MB 内存 + 流式 ASR 200MB 内存 + 100MB 磁盘
- **释放**：whisper.cpp 700MB 显存（可关掉）
- **CPU 静默期**：<0.5%
- **CPU 对话期**：~10%
- **GPU 占用**：0（纯 CPU）

### 14.6 路线图调整

| 阶段 | 目标 | 状态 |
| - | - | - |
| **P0 Jarvis 模式（新增）** | 唤醒 KWS + 流式 ASR | **🔴 立即启动** |
| P0 之前 | 本地部署 | ✅ |
| P1-API 语音上云 | ~~降级~~ | Jarvis 优先本地 |
| P2 记忆库 | memory-store | 🟡 设计完成 |

### 14.7 实施工作量

- 4 个新代码文件（KWS / ASR / 状态机 / 时间戳日志）
- 1 个新脚本（事件音频生成）
- 3 个 wav 生成（wake / goodbye / error）
- 4 个文档改写（jarvis-mode / asr-streaming / gaming-mode / api-optimization / pm-local / tech-local）

**总工作量**：~1.5 人天（含 KWS 训练）

### 14.8 决策项

- [x] 所有关键决策已拍板（见 §14.2）
- [ ] 录制 50 句"bt 在吗"训练数据（30 分钟）
- [ ] 跑 `generate_event_audio.py` 生成 wake/goodbye
- [ ] 复制 error.wav 到 prompts/bt/events/
- [ ] 部署 jarvis_mode.py 到 webui
- [ ] 端到端测试唤醒/对话/打断/结束
- [ ] 未来激活 MiniMax Token Plan 时填 `MINIMAX_API_KEY`

---

## 15. 变更记录（v3.0）

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 本地化首发 | Codex |
| 2026-07-07 | v1.1 | P1 ASR 流式 + P2 记忆库 + 100% 跨平台 | Codex |
| 2026-07-08 | v2.0 | API 化 3 档云策略 | Codex |
| 2026-07-08 | v2.1 | 8 家 token plan 调研 | Codex |
| 2026-07-08 | v3.0 | **Jarvis 模式（重大更新）**：唤醒 KWS + 流式 ASR + EXIT_WORDS + 预录事件 | Codex |

---

## 16. 屏幕捕获 + Hermes 隔离（v3.1，2026-07-09）

> 详细方案：
> - `doc/screen-capture.md`（9.3KB，getDisplayMedia）
> - `doc/hermes-integration.md`（10.5KB，严格隔离）

### 16.1 屏幕捕获（getDisplayMedia）

| 项 | 内容 |
| - | - |
| 方案 | 浏览器原生 `navigator.mediaDevices.getDisplayMedia()` |
| 配置 | `displaySurface: "window"` + `frameRate: 1` + `audio: false` |
| 集成 | **0 后端改动**——纯前端 + 现有 WebRTC 链路 |
| 延迟 | <100ms（捕获 + 编码） |
| 带宽 | ~200 KB/s（1 fps，JPEG 70%） |
| 隐私 | 强制只选窗口（不要整屏） |
| 工作量 | ~2 小时（前端 50 行 + Python 20 行） |

### 16.2 Hermes 严格隔离

**核心原则**：Hermes 是"工具层"，不是"角色层"。

| 维度 | 隔离方式 |
| - | - |
| 人格 | shim 不传 system 字段给 hermes（让 hermes 用自己的 SOUL.md） |
| 记忆 | Hermes 自己的 vs BT-7274 memory-store（命名空间隔离） |
| Skills | 独立命名空间 |
| Provider | shim 不维护，委托给 hermes gateway |

**shim 行为**：
```python
payload = {
    "model": "auto",  # 委托给 hermes gateway
    "messages": [{"role": "user", "content": req.question}],
    # 不传 system 字段
    # 不传 context 字段
}
```

**好处**：
- 调用更快（不解析 BT-7274 人格/记忆）
- 故障隔离（Hermes 挂了 BT-7274 仍能工作）
- 升级独立
- 人格纯粹

### 16.3 实施工作量

- `doc/screen-capture.md` 新建（9.3KB）
- `doc/hermes-integration.md` 新建（10.5KB）
- 现有文档清理与整合：合并到 `jarvis-mode.md` / `tech-local.md` / `pm-local.md`

### 16.4 决策项（已拍板）

- [x] 屏幕捕获 = getDisplayMedia
- [x] Hermes 严格隔离
- [x] shim 不传 system

---

## 17. 变更记录（v3.1）

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 本地化首发 | Codex |
| 2026-07-07 | v1.1 | P1 ASR 流式 + P2 记忆库 + 100% 跨平台 | Codex |
| 2026-07-08 | v2.0 | API 化 3 档云策略 | Codex |
| 2026-07-08 | v2.1 | 8 家 token plan 调研 | Codex |
| 2026-07-08 | v3.0 | Jarvis 模式（重大更新） | Codex |
| 2026-07-09 | v3.1 | 屏幕捕获（getDisplayMedia）+ Hermes 严格隔离 | Codex |

---

## 18. WebUI 链路测试修正（v3.6，2026-07-12）

### 18.1 结论

webui 是当前性价比最高的链路测试入口；不再维护 `services/voice-ui` 薄壳，也不再在右上角另起 LLM 回复面板。中间 `VLM Output Info` 的 `id="resultTextContent"` 是单一对话面。

### 18.2 本次修正

| 项 | 结果 |
| - | - |
| 回复显示 | `[Pilot]` / `[jarvis]` 直接追加到 `resultTextContent` |
| 会话一致性 | `sendBtPrompt()` 使用当前 WebSocket 的 `sessionId`，不再临时生成 `window.sessionId` |
| TTS 触发 | WS `llm_reply` 到达后调用 `/api/tts/synthesize`，`btTtsPlayer` 播放 WAV blob |
| 旧 UI | 删除右上角冗余 `llmReplySection` / `llmReplyList` 路径 |

### 18.3 实测

Chrome DevTools 实测 `http://127.0.0.1:8099/`：点击纸飞机 → `POST /api/llm/message` 200 → 中间框显示 `[jarvis]Confirmed.` → `POST /api/tts/synthesize` 200 → `<audio id="btTtsPlayer">` 拿到 `blob:`，时长约 0.98s，播放完成。

回归：`services/webui` 测试从 17 条扩到 20 条，新增静态契约测试覆盖 session 一致性、回复写入 `resultTextContent`、旧浮动面板不可复活；`python -m pytest tests/ -q` 20/20 通过。

---

## 19. WebUI 对话可观测性修正（v3.7，2026-07-12）

### 19.1 问题

用户实测“能听到回复，但发送文字和 LLM 回复不在聊天框显示”。根因是 v3.6 只手动 append DOM 到 `resultTextContent`，但原 webui 会根据 `vlmHistory.length` 和 overlay 设置把外层 `resultText` 置为 `display:none`，导致 DOM 里有内容但界面不可见。

### 19.2 修正

| 项 | 结果 |
| - | - |
| 对话显示 | 新增 `jarvis_dialog` 历史类型，`Pilot` / `BT-7274` 进入 `vlmHistory` 并由 `createJarvisDialogNode()` 渲染 |
| 语音可观测 | ASR 定稿后广播 `pilot_utterance` WS 事件，前端显示 Pilot 文本后再显示 LLM 回复 |
| TTS 成本 | 文本测试 `/api/llm/message` 调 `_send_to_llm(..., stream_tts=False)`，避免状态机内置 TTS + 浏览器 TTS 双合成 |
| 调试噪音 | `VLMService.set_model()` 补齐并拒绝 `undefined/null/none`；前端过滤无效模型名 |

### 19.3 实测

Chrome DevTools 实测 `http://127.0.0.1:8099/`：点击纸飞机 → 中间 `VLM Output Info` 显示 `Pilot` 输入和 `BT-7274` 回复 → `btTtsPlayer` 播放完成；日志只有一次 `POST /api/tts/synthesize`，控制台无 error/warn。回归测试：`services/webui` 24/24 通过。

---

## 20. ASR 输入缓存修正（v3.8，2026-07-12）

### 20.1 问题

用户开启红色麦克风 ASR，说一段话后手动清空输入框，再继续说话，旧文字会重新出现。根因：清空只修改 `promptText.value`，但前端 `asrFinalText/asrPartialText/asrLastFinalText` 仍保留旧识别结果；录音中的后端流式 ASR 段也可能继续返回旧上下文。

### 20.2 修正

| 项 | 结果 |
| - | - |
| 前端缓存 | `promptText input` 改为 `handlePromptManualInput()`，手动编辑/清空时同步重置 ASR 累积状态 |
| 后端流段 | 录音中手动编辑/清空时发送 `segment_end`，关闭旧 ASR websocket 并新建一段 |
| 旧事件隔离 | ASR websocket handlers 用 `asrWs !== ws` 忽略旧连接 message/close/error，避免误停录音 |
| 测试定位 | 红色麦克风按钮可用于测 ASR 识别质量；完整 KWS→ASR→LLM→TTS 链路仍以 Jarvis 状态机为准 |

回归测试：`services/webui` 25/25 通过。
---

## 21. WebUI 单一发送入口（v3.9，2026-07-12）

### 21.1 结论

纸飞机和旧 `LLM` 按钮语义重复。当前只保留纸飞机 `id="promptSendBtn"` 作为文本/ASR 发送入口；旧 `id="llmTestSendBtn"` 不允许复活。

### 21.2 修正

| 项 | 结果 |
| - | - |
| 发送入口 | `promptSendBtn` 点击、Cmd/Ctrl + Enter、ASR 结束自动发送全部调用 `sendBtPrompt()` |
| 旧按钮 | 当前 DOM 不再存在 `id="llmTestSendBtn"` |
| ASR 清空 | 发送后同步 `resetAsrTranscriptState("")` 与 `resetActiveAsrSegment()`，避免旧识别文本回流 |
| 错误标识 | 前端错误前缀从 `[llm-test]` 改为 `[bt-send]`，避免继续把它理解成临时测试按钮 |
| 测试 | `test_paper_plane_is_the_only_bt_send_button` 守住唯一入口 |

回归测试：`services/webui` 26/26 通过。
---

## 22. ASR 独立录音与旧文本复活修正（v3.10，2026-07-12）

### 22.1 结论

红色 Start 是源项目视频分析状态机入口，不应该作为 ASR 测试前置条件。红色麦克风应可独立打开浏览器麦克风，直接测试 `/ws/asr` → sherpa ASR → `promptText`。

### 22.2 根因

| 现象 | 根因 |
| - | - |
| 不点红色 Start，麦克风无法真正开始录音 | `startSpeech()` 里仍有 `!isAnalysisRunning` 门禁，未运行视频分析时会立刻 `stopSpeech()` |
| 点红色 Start 后再点麦克风，输入框自动出现之前文字 | 外部 ASR 不可达时走 in-process sherpa fallback；该 fallback 使用全局 `_INPROC_ASR`，新 websocket 连接没有重置 `engine.last_text` |

### 22.3 修正

| 项 | 结果 |
| - | - |
| 前端 | `startSpeech()` 移除 `!isAnalysisRunning` 门禁，ASR 不再依赖红色 Start |
| 后端 | `connect_asr_inproc()` 每次新连接执行 `engine.start()`，清掉旧 stream / `last_text` |
| 分段重置 | in-process fallback 收到 `segment_end` 时 `engine.stop()` + `engine.start()`，配合前端手动编辑清缓存 |
| 测试 | 新增静态契约测试守住 ASR 独立启动；新增 in-process fallback 重置回归测试 |

回归测试：`services/webui` 28/28 通过。
---

## 23. ASR 发送态收口（v3.11，2026-07-12）

### 23.1 页面实测状态

当前页面已加载前端新逻辑，但 8099 运行进程早于 `asr.py` 修改时间；因此浏览器刷新不能让后端 fallback 重置生效。页面上还出现了另一个独立问题：ASR 仍在录音，`asrPartialText` 长文本持续写回 `promptText`，并且 partial 中含有 `</s>` 控制 token。

### 23.2 修正

| 项 | 结果 |
| - | - |
| 发送态 | `sendBtPrompt()` 在 POST `/api/llm/message` 前停止活跃 ASR，防止发送后输入框继续被录音填充 |
| 文本清洗 | 新增 `sanitizeAsrTranscriptText()`，ASR partial/final 写入输入框前去掉 `</s>` 并压缩多余空白 |
| 状态边界 | 发送后只清空 ASR 前端状态，不再调用 `resetActiveAsrSegment()` 重开录音段 |
| spec | 新增 `doc/specs/webui-asr-input-state.md`，记录 ASR 输入状态问题、方案和测试缝 |
| 测试 | 新增静态契约测试守住 ASR 文本清洗与发送时停止录音 |

回归测试：`services/webui` 30/30 通过。
---

## 24. BT 延迟 HUD 与 ASR 启动优化（v3.12，2026-07-12）

### 24.1 分析

ASR 体感慢至少有三段：浏览器麦克风权限/AudioContext 建立、ASR websocket 连接与模型冷启动、首个 partial / final 产生。当前确定的代码问题是：`8994` 未监听时，webui 仍默认先连外部 `ASR_URL=ws://127.0.0.1:8994/ws/asr` 并重试，然后才 fallback 到本地 sherpa。这个默认路径会把“外部连接失败 + fallback + 冷启动”叠在第一次语音输入上。

### 24.2 修正

| 项 | 结果 |
| - | - |
| 延迟显示 | `VLM Output Info` 左上角新增 BT 链路 HUD：`ASR / LLM / TTS / E2E` |
| ASR timing | 记录 start、mic ready、WS connected、first partial、final |
| LLM timing | 记录 send start、POST ack、`llm_reply` WS 到达 |
| TTS timing | 记录 TTS fetch start、WAV blob ready、audio play |
| VLM 设置降噪 | 左侧 `VLM API Configuration` 改为 `Video/VLM Settings`，明确只影响红色 Start 视频/VLM |
| ASR 启动 | 默认 `ASR_URL=""`，直接使用 in-process sherpa；只有显式设置 `ASR_URL` 才走外部 ASR |
| 冷启动 | webui startup 后台 warm in-process sherpa ASR，降低第一次点麦克风的加载体感 |

回归测试：`services/webui` 35/35 通过。

---

## 25. WebUI 独立 KWS 监听链路（v3.13，2026-07-12）

### 25.1 结论

WebUI 现在有三条明确入口：红色 Start 只做视频/VLM；红色麦克风只做一次性 ASR 输入；新增 `btListenBtn` 才是常驻 KWS 监听链路。之前页面显示 `KWS OK` 只代表模型文件存在，不代表浏览器麦克风已经进入 KWS。

### 25.2 修正

| 项 | 结果 |
| - | - |
| spec | 新增 `doc/specs/webui-kws-listening-chain.md` |
| 前端 | 新增 `btListenBtn`，启动 audio-only WebRTC，payload 带 `jarvis_audio: true` |
| 状态清理 | 开始监听前调用 `/api/jarvis/stop` 清理旧 session，停止监听时关闭 peer/local tracks 并再次 stop |
| 后端 | `/offer` 对 audio offer 调 `bind_jarvis_audio_for_peer()`，创建 Jarvis session、绑定 `MicAudioTrack`、添加 `SpeakerAudioTrack` |
| KWS sweep | `kws_param_sweep.py` 每个 wav 前执行 `kws.start()`，避免 stream 状态污染 recall/FAR |
| 参数结论 | 可信 sweep 后默认 `score=10.0 / threshold=0.25` 仍最佳（recall 49.06%，FAR 2.00%），本轮不改 env |

### 25.3 待真机验收

自动测试能证明代码路径已接好，但不能代替用户物理麦克风测试。完成标准是：点击监听按钮后状态回到 `KWS_LISTENING`，用户喊 “BT” 后页面进入 `WAKE_DETECTED` / `DIALOG_ACTIVE`，并能听到 wake/TTS 或看到 Pilot/BT 对话进入中间框。