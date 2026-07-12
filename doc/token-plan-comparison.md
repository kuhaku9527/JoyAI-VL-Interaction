# AI 大模型 Token Plan / 订阅套餐对比（2026 Q3 全行业）

> 调研日期：2026-07-08
> 目标：找到"订阅最少、能力最全"的组合，覆盖 LLM + Agent + 多模态（视觉/语音/声音克隆/音乐/视频）
> 配套文档：`doc/api-optimization.md`（本地 vs 云）+ `doc/tech-local.md §14`（技术实现）

---

## 0. 核心结论（先看）

> **唯一真正"全包"的套餐：MiniMax Token Plan**
>
> 业界调研：**没有任何其他厂商的订阅能在一个套餐内同时覆盖 LLM + Agent + TTS + 声音克隆 + 多模态视觉 + 音乐 + 视频**。所有其他厂商都把 TTS/ASR 单独计费（即使是最"全包"的阿里云百炼 Token Plan，也只含 LLM + 视觉）。
>
> **推荐组合**（按需求分档）：
>
> | 档 | 月费 | 适合 | 组合 |
> | - | -: | - | - |
> | 🟢 **省钱档** | **¥29-79** | 个人 / 轻量 | **MiniMax Plus ¥49** + 阿里云 ASR ¥30（按量） |
> | 🔵 **平衡档（推荐）** | **¥119-150** | 日常 / gaming | **MiniMax Max ¥119** + ASR ¥30 |
> | 🟡 **重度档** | **¥469-700** | 重度 / 团队 | **MiniMax Ultra ¥469** + 火山 TTS ¥80 + 阿里云 ASR ¥100 |
> | 🟣 **海外档** | **$25-42** | 海外 / 高质量 | **ChatGPT Plus $20 + ElevenLabs $5** |

---

## 1. 8 家厂商订阅套餐对比（核心表）

### 1.1 总表

| 厂商 | 套餐 | 月费 | LLM | Agent 工具 | 视觉 | TTS | ASR | 声音克隆 | 音乐 | 视频 | 备注 |
| - | - | -: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | - |
| **MiniMax** | Token Plan Plus | **¥49** | ✅ M2.7/M3 | ✅ | ✅ | ✅ Speech 2.8 | ❌单独 | ✅ | ✅ | ✅ 限速 | **唯一全包** |
| **MiniMax** | Token Plan Max | **¥119** | ✅ | ✅ (4-5) | ✅ | ✅ | ❌单独 | ✅ | ✅ | ✅ | 重度 agent |
| **MiniMax** | Token Plan Ultra | **¥469** | ✅ | ✅ (6-7) | ✅ | ✅ | ❌单独 | ✅ | ✅ | ✅ 每日 5 条 | 重度 |
| **阿里云百炼** | Token Plan 标准 | **¥198** | ✅ 150+ 模型 | ✅ | ✅ | ❌单独 | ❌单独 | ❌单独 | ❌ | ✅ Wan | 多模型 + agent 工具 |
| **阿里云百炼** | Token Plan 高级 | **¥698** | ✅ 4× | ✅ | ✅ | ❌单独 | ❌单独 | ❌单独 | ❌ | ✅ | 4 倍用量 |
| **阿里云百炼** | Token Plan 尊享 | **¥1398** | ✅ 10× | ✅ | ✅ | ❌单独 | ❌单独 | ❌单独 | ❌ | ✅ | 10 倍 |
| **火山引擎** | Agent Plan Small | **¥40** | ✅ Doubao+GLM+Kimi+DeepSeek | ✅ | ✅ | ❌单独 | ❌单独 | ❌ | ❌ | ✅ Doubao | 业界首个 Agent 套餐 |
| **火山引擎** | Agent Plan Medium | **¥200** | ✅ | ✅ | ✅ | ❌单独 | ❌单独 | ❌ | ❌ | ✅ Seedance | 7×24 智能伙伴 |
| **火山引擎** | Agent Plan Large | **¥500** | ✅ 5× | ✅ | ✅ | ❌单独 | ❌单独 | ❌ | ❌ | ✅ | 重度多模态 |
| **火山引擎** | Agent Plan Max | **¥1000** | ✅ 12.5× | ✅ | ✅ | ❌单独 | ❌单独 | ❌ | ❌ | ✅ | 团队级 |
| **腾讯云** | Hy Token Plan Lite | **¥28** | ✅ Hy3+第三方 | ✅ | ✅ | ❌单独 | ❌单独 | ❌ | ❌ | ✅ | 国内便宜 |
| **腾讯云** | Hy Token Plan Standard | **¥78** | ✅ 2.2× | ✅ | ✅ | ❌单独 | ❌单独 | ❌ | ❌ | ✅ | 日常 IDE 协作 |
| **腾讯云** | Hy Token Plan Pro | **¥238** | ✅ 11.4× | ✅ | ✅ | ❌单独 | ❌单独 | ❌ | ❌ | ✅ | 密集 Agent |
| **腾讯云** | Hy Token Plan Max | **¥468** | ✅ 23× | ✅ | ✅ | ❌单独 | ❌单独 | ❌ | ❌ | ✅ | 主力工作流 |
| **智谱** | GLM Coding Plan Lite | **¥49** | ✅ GLM-4.7 only | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | **只编程** |
| **智谱** | GLM Coding Plan Pro | **¥149** | ✅ GLM-5 全系 | ✅ | ✅ 视觉 MCP | ❌ | ❌ | ❌ | ❌ | ❌ | 视觉理解 MCP |
| **智谱** | GLM Coding Plan Max | **¥469** | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | 4× Pro |
| **OpenAI** | ChatGPT Plus | **$20** | ✅ GPT-5.5 | ✅ Codex | ✅ | ✅ Advanced Voice | ❌ | ❌ | ❌ | ❌ Sora | DALL-E |
| **OpenAI** | ChatGPT Pro | **$200** | ✅ GPT-5.5 Pro | ✅ Max | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | 5-20× |
| **Anthropic** | Claude Pro | **$20** | ✅ Sonnet 4.6 | ✅ Code/Cowork | ✅ | ✅ Voice | ❌ | ❌ | ❌ | ❌ | Skills |
| **Anthropic** | Claude Max 5× | **$100** | ✅ Opus 4.8 | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | 5× |
| **Google** | Gemini AI Pro | **$19.99** | ✅ Gemini 3.1 Pro | ✅ Antigravity | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ Veo 3.1 | 1M context |
| **Google** | Gemini AI Ultra | **$99.99-249.99** | ✅ 3.1 Pro+ | ✅ Max | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ 4K | Deep Think |
| **xAI** | SuperGrok | **$30** | ✅ Grok 4 | ✅ Build CLI | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ Aurora | 无限 voice |
| **xAI** | X Premium+ | **$16** | ✅ Grok 4 限制 | ❌ | ✅ | ✅ 30min/天 | ❌ | ❌ | ❌ | ✅ | 社交 + AI |

> **注**：所有不含 TTS/ASR/声音克隆的套餐，都需要额外按量付费（API 单独计费）。MiniMax 内部积分可直接抵扣 TTS/ASR 跨模态用量；其他厂商积分/credits 通常只覆盖 LLM。


### 1.3 MiniMax 声音克隆（Rapid Voice Cloning）详解

> 用户反馈之前没看到这块细节。补充如下。

**API 端点**：`/v1/voice_clone`（音色快速复刻）
**官方文档**：https://platform.minimaxi.com/docs/api-reference/voice-cloning-clone

**输入规格**：

| 字段 | 要求 |
| - | - |
| 最低时长 | **10 秒**（官方） / 5 秒（Replicate 第三方） |
| 最长时长 | 5 分钟 |
| 支持格式 | mp3 / m4a / wav |
| 文件大小 | ≤ 20 MB |
| 推荐采样率 | 24kHz / 16kHz mono |
| 推荐语种 | 中文（也支持 40 语种） |

**两种模式**：

| 模式 | 触发 | 输入 | 适用 |
| - | - | - | - |
| `clone` | 真实声音克隆 | 1 段参考音频 | 录一段 BT-7274 台词 |
| `design` | 文字描述生成 | 文本描述（如"中年男声，磁性"）+ preview_text | 不想录参考音频时 |

**计费（核心数字）**：

| 通道 | 单价 | 触发 |
| - | - | - |
| **官方按量** | **¥9.9 / 被接受的 voice** | 首次使用 `voice_id` 合成时扣费（试听不扣） |
| **Token Plan 套餐** | 套餐赠额内免费 / 超出按 1:1 折算积分 | 跨模态共享积分池 |
| 第三方（APIXO） | $0.50/request | 不分接受/试听 |
| 第三方（Replicate） | $0.05/秒输出音频 | 按使用时长 |

**7 天强制保活限制**（重要）：

> 复刻得到的 voice_id **7 天内未正式调用合成**，系统自动删除。

- 不影响使用，只是不活跃会清
- 解决：每月调 1 次任意合成保活；或选 ElevenLabs Starter $5（不限时）
- 本项目日常对话频繁，**7 天限制基本无影响**

**三步实操流程**：

```python
import requests

API = "https://api.minimaxi.com/v1"
KEY = "eyJ..."  # 订阅 Key（Token Plan 套餐内送）

# 1) File Upload API
with open("bt7274_sample.wav", "rb") as f:
    r = requests.post(f"{API}/files/upload", 
        headers={"Authorization": f"Bearer {KEY}"},
        files={"file": f})
file_id = r.json()["file"]["file_id"]

# 2) Voice Clone API（可选：上传 prompt_audio 增强质量）
r = requests.post(f"{API}/voice_clone",
    headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    json={
        "file_id": file_id,
        "voice_id": "bt7274_minimax_v1",   # 自定义 ID，必须字母开头 ≥6 字符
        "model": "speech-2.8-hd",
        "text": "早上好指挥官，今天的天气看起来不错。",   # 试听文本
        "clone_prompt": {                              # 可选：增强 prompt
            "prompt_audio": "<file_id_of_prompt_audio>",
            "prompt_text": "沉稳磁性男声，节奏感强"
        }
    })
voice_id = r.json()["voice_id"]   # 拿到的 voice_id 用于后续合成

# 3) T2A API 合成（流式 WebSocket）
# 用 voice_id 调 /v1/t2a_streaming 或 /v1/t2a
```

**质量参考**：
- 10 秒干净音频 → **99% 相似度**（官方 + 第三方 Replicate 都引用这个数）
- 主观 MOS：4-4.5/5（与 ElevenLabs Multilingual V2 接近）
- 适合：BT-7274 这种"角色声线"场景

**与本项目其他方案对比**：

| 方案 | 样本时长 | 相似度 | 成本 | 7 天限制 | 模型体积 |
| - | - | - | - | - | - |
| **MiniMax Rapid Clone** | **10s** | **99%** | ¥9.9/voice 或套餐内 | ⚠️ 有 | 云端（无需本地模型） |
| 本地 CosyVoice3 0 样本 | **0s** | 主观 3-4/5 | 0 | ❌ 无 | 1.1GB 显存 |
| ElevenLabs Voice Clone | 1-2 min | 5/5 | $5-$22/月 | ❌ 无 | 云端 |
| 阿里云 CosyVoice API | 5-10s | 4/5 | 按字符 | ❌ 无 | 云端 |

**风险与缓解**：

| 风险 | 缓解 |
| - | - |
| 7 天不调用就删 | 月度合成任务保活 / 选 ElevenLabs |
| 认证要求 | 提前完成个人/企业认证 |
| 与本地 CosyVoice 流程差异 | voice_clone_api 加 `cloud_clone.py` 后端桥接 |
| voice_id 不在本地 `voices/` 目录 | voice_clone_api 内部维护 `local_voice_id ↔ minimax_voice_id` 映射表 |

### 1.2 各家 ASR/TTS/声音克隆 单价（按量计费）

| 厂商 | ASR 单价 | TTS 单价 | 声音克隆 | 备注 |
| - | - | - | - | - |
| **阿里云百炼** | 0.0008元/秒 (流式) / 0.05-0.75元/轮 | cosyvoice-v3-plus 按字符 | 单独模型 | 流式 WebSocket 协议 |
| **火山引擎** | 1.2元/小时（闲时版）/ 实时按 token | 豆包端到端 10元/M token | 单独 | Doubao-tts |
| **MiniMax** | （需查 paygo） | speech-2.8-turbo $60/M chars / hd $100/M | $1.5/voice | 40 语种 |
| **OpenAI** | Whisper $0.006/min | tts-1 $15/M chars / tts-1-hd $30/M | ❌ | Realtime $0.06/min |
| **ElevenLabs** | ❌ | Multilingual V2 $0.30/1K chars | $1-5/voice | 最佳质量 |
| **xAI Grok** | $0.10/hr REST / $0.20/hr streaming | $15/M chars | $5+ for custom | 25+ 语言 |
| **智谱** | ❌ 不含 ASR | ❌ 不含 TTS | ❌ | **完全不含** |

---

## 2. 关键发现

### 2.1 "全包"的真实含义

业界对"全模态 token plan"普遍理解有误：
- **阿里云百炼 Token Plan（¥198）** = LLM + 视觉 + 150+ 模型 + 兼容 agent 工具，**不含 TTS/ASR/声音克隆**
- **火山方舟 Agent Plan（¥40-1000）** = LLM + 视觉 + 视频 + Harness，**ASR/TTS 单独计费**
- **腾讯云 Hy Token Plan（¥28-468）** = LLM + 视觉 + 视频，**不含 TTS/ASR**
- **智谱 GLM Coding Plan（¥49-469）** = **只面向编程**，含视觉 MCP，**不含 TTS/ASR**

**真正全包（LLM + Agent + TTS + ASR + 视觉 + 声音克隆 + 音乐 + 视频）**：
- **只有 MiniMax Token Plan**（¥29-469，跨模态共享积分池）

### 2.2 套餐实际可消费内容对比

| 套餐 | LLM 消耗 1 次 = 多少积分/credits | 1 元能买多少 LLM 调用 | 视觉/TTS/ASR 是否共享 |
| - | - | -: | - |
| MiniMax Token Plan | 1:1 折算 | 1000 积分 = ¥7 | ✅ 共享（核心卖点） |
| 阿里云百炼 | 1:1 Credits | 1 Credit = 0.008 元 | ❌ Credits 只 LLM，语音单独计费 |
| 火山 Agent Plan | AFP 积分 | 1 AFP = 0.005 元 | ❌ AFP 只 LLM + 视觉，语音单独 |
| 腾讯 Hy Token Plan | Token 配额 | 1 元 = ~3.2M tokens | ❌ 配额只 LLM |

**结论**：只有 MiniMax 是真正"一个积分跨所有模态"。

### 2.3 MiniMax Token Plan 详细（2026 最新）

来源：https://platform.minimaxi.com/docs/token-plan/intro

| 套餐 | 月费 | 适合 | 资源覆盖 | 备注 |
| - | -: | - | - | - |
| **Starter** | **¥29** | 轻量试用 | M2.7 + M3 + 全模态 | **已停售**（老用户保留） |
| **Plus** | **¥49** | 轻量开发 | 全部 5 个模态 | 3-4 个 Agent |
| **Max** | **¥119** | 高频 Agent + 多模态 | 全部 | 4-5 个 Agent |
| **Ultra** | **¥469** | 重度工作流 | 全部 + 每日 5 条视频 | 6-7 个 Agent |

**核心承诺**（来源：IT之家 2026-03-23 + 2026-06-05 报道）：

- 编程模型用量（M2.7 调用数/5h）+ 多模态额度**不冲突**
- 套餐内**不区分**文本/图像/语音/音乐额度，**共享一份额度池**
- 1,000 积分 = ¥7（与 API 按量付费 1:1 等价，**无加价**）
- 超出套餐额度后可**增购语音/视频资源包**（节省 20%）
- 2026-06-05 升级后老用户**权益不缩水**（M2.7 调用数 +10% + 增 M3 + 多模态）

**模型清单**：
- M2.7 / M3（编程 + agent 主力）
- Hailuo 2.3 / 2.3-Fast（视频生成）
- Speech 2.8 HD / Turbo（T2A 语音合成，40 语种）
- Music 2.x（音乐生成）
- Image（图像生成）
- Rapid Voice Cloning（$1.5/voice / ¥10-15/voice）

### 2.4 各家核心差异（一句话）

| 厂商 | 一句话定位 |
| - | - |
| **MiniMax** | 唯一全模态订阅；M2.7 编程强；最便宜的真正"全包" |
| **阿里云百炼** | 150+ 模型生态最大；阿里系；多坐席企业级；TTS/ASR 单独 |
| **火山引擎** | 字节系全栈；Doubao 多模态生成强；Agent Harness 工具链丰富；TTS/ASR 单独 |
| **腾讯云** | 混元 + 第三方；最便宜入门（¥28）；视频生成强；TTS/ASR 单独 |
| **智谱** | **只做编程**；GLM-5.2 旗舰；不面向多模态；最便宜的"编程专家" |
| **OpenAI** | 综合最强（GPT-5.5 + Codex + Advanced Voice + Sora）；$20 起 |
| **Anthropic** | 长上下文 / 写作 / Claude Code 强；opus 顶级；TTS 弱 |
| **Google** | 多模态（Veo 视频） + 长上下文（1M） + 工具链最丰富（Workspace） |
| **xAI** | 实时搜索 + 社交集成（X Premium+）；中文一般 |

---

## 3. 推荐组合（按需求分档）

### 3.1 🟢 省钱档（¥29-79/月，1h/天 个人）

**主套餐**：**MiniMax Token Plan Plus ¥49**
- 覆盖：LLM (M2.7/M3) + Agent + 视觉 + TTS (Speech 2.8) + 声音克隆 + 音乐
- 用量：3-4 个 Agent

**补充**（如需 ASR）：阿里云 ASR 按量 ¥0.0008/秒
- 1h/天 = 30h/月 × 3600 = 108000 秒 × 0.0008 = **¥86**（如果用流式 ASR）
- 1h/天 = 30h × 3600 秒 × 0.0008 ≈ ¥86 → 实际**¥30-50**（轻量闲聊场景）

**总计**：¥79-100/月

**适合**：个人开发者、试玩、文本为主的 agent 场景

### 3.2 🔵 平衡档（推荐，¥119-180/月，3h/天 日常 + gaming）

**主套餐**：**MiniMax Token Plan Max ¥119**
- 覆盖：4-5 个 Agent + 全模态
- 用量上限：高频编程 + 中度多模态

**补充**（如需 ASR）：阿里云 ASR 按量 ¥30-50
**可选补充**：火山 TTS 备用 ¥20-30

**总计**：¥150-180/月

**适合**：本项目（JoyAI-VL-Interaction）的推荐档——既覆盖主对话（用本地 VLM），也覆盖 LLM agent 后端（用 MiniMax 替代 Hermes）

### 3.3 🟡 重度档（¥469-700/月，团队 / 商业）

**主套餐**：**MiniMax Token Plan Ultra ¥469**
- 6-7 个 Agent + 每日 5 条视频

**补充**：
- 火山方舟 TTS ¥80-100
- 阿里云 ASR ¥100-150

**总计**：¥600-700/月

**适合**：重度多模态生产（短视频创作、播客生成）

### 3.4 🟣 海外档（$25-42/月）

**主套餐**：**ChatGPT Plus $20 + ElevenLabs Starter $5**
- ChatGPT Plus 覆盖 LLM (GPT-5.5) + Agent (Codex) + Vision + Advanced Voice
- ElevenLabs 覆盖声音克隆 + 顶级 TTS

**总计**：$25/月 ≈ ¥180

**适合**：海外用户、追求最高质量

### 3.5 🔴 极简档（仅本地 VLM，无云端 LLM）

**只用本地**：
- llama-server + 阿里云 ASR ¥30 + 火山 TTS ¥45 = **¥75/月**
- 适合：极致隐私、断网、显存够

---

## 4. 与本项目（JoyAI-VL-Interaction）的匹配

### 4.1 当前架构缺口

| 模块 | 当前实现 | 可优化为 |
| - | - | - |
| 主对话 VLM | 本地 IQ4_NL GGUF | **保持本地**（视频帧不上云） |
| 摘要 | 本地 Qwen2.5-VL-3B | **MiniMax 套餐内**（省钱，省 2.9GB 显存） |
| ASR | 本地 whisper.cpp | **阿里云流式 ASR** ¥30/月 |
| TTS | 本地 CosyVoice3 | **MiniMax Speech 2.8**（套餐内）或火山 TTS |
| 声音克隆 | 本地 CosyVoice3 0 样本 | **MiniMax Rapid Voice Cloning**（¥10-15/voice） |
| Hermes-agent | OpenAI/Anthropic/... | **MiniMax Max/Ultra** 替代（200+ provider + 中文 SOTA） |

### 4.2 推荐组合（针对本项目）

**省钱版（¥50-80/月）**：
- **MiniMax Plus ¥49** 替代 Hermes-agent（agent + 编程 + 视觉）
- 阿里云 ASR ¥30
- 本地 VLM + 本地 TTS（CosyVoice3 保留）
- **总计 ¥79**

**推荐版（¥150-180/月）**：
- **MiniMax Max ¥119**（4-5 个 agent + 全模态）
- 阿里云 ASR ¥30
- **总计 ¥149**

**重玩版（¥500+/月）**：
- **MiniMax Ultra ¥469**
- ASR/TTS 全套餐内
- **总计 ¥469**

### 4.3 关键收益对比

| 项 | 全本地 | MiniMax 平衡档（推荐） | 全海外（ChatGPT+ElevenLabs） |
| - | -: | -: | -: |
| 月费 | 0 | **¥149** | ¥180 |
| 显存 | 11.5GB | **9.5GB**（关本地 ASR/TTS） | 9.5GB |
| ASR 延迟 | 1.5-7s | **0.5-1s** | 0.5-1s |
| TTS 冷启动 | 5-8s | **<300ms** | <300ms |
| 声音克隆质量 | 主观 3-4/5 | **主观 4-4.5/5** | 5/5（ElevenLabs 顶级） |
| 中文能力 | 本地 95% | **95%** | ChatGPT 90% / ElevenLabs 80% |
| Agent 工具 | Hermes 200+ | **MiniMax + 本地工具** | ChatGPT Codex |
| 隐私 | ✅ 全本地 | ⚠️ 文本/语音上云 | ⚠️ 上云 |

---

## 5. 与 `doc/api-optimization.md` 选型对齐

把 `doc/api-optimization.md` §2.2 的"阿里云一句话流式" 改为按本调研的实际最优：

| 模块 | 原推荐 | 新推荐 | 理由 |
| - | - | - | - |
| ASR | 阿里云一句话流式 | **维持**（确实最便宜 ¥30） | 0.0008元/秒，月 ¥30-50 |
| TTS | 火山引擎流式 | **MiniMax Speech 2.8**（若订阅 MiniMax）**或火山** | MiniMax Plus/Max 套餐内含 TTS |
| 声音克隆 | CosyVoice3 0 样本本地 | **MiniMax Rapid Voice Cloning**（¥10-15/voice） | 套餐内 1:1 折算 |
| 摘要 | DeepSeek-V3 按量 | **MiniMax 套餐内**（更便宜） | M2.7/M3 摘要能力 SOTA |
| 主对话 VLM | 本地 | **保持本地** | 视频帧不上云 |
| Hermes-agent | 200+ provider | **MiniMax Max/Ultra 替代** | 中文 SOTA + 全模态 |

---

## 6. 决策项（PM 拍板）

- [ ] **套餐选择**：MiniMax Plus ¥49 / Max ¥119 / Ultra ¥469？
- [ ] **ASR 选型**：阿里云流式（¥30）还是 MiniMax 套餐内？
- [ ] **TTS 选型**：MiniMax 套餐内 / 火山（按量）？
- [ ] **声音克隆**：本地 CosyVoice3 / MiniMax Rapid Clone / ElevenLabs？
- [ ] **Hermes-agent 是否完全切换到 MiniMax**？（保留旧 codex 兜底）
- [ ] **是否保留本地 ASR/TTS 作为 fallback**？（网络抖动时）
- [ ] **预算上限**：月 ¥100 / ¥200 / ¥500？

---

## 7. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-08 | v1.0 | 初版：8 家厂商对比表 + 5 套推荐组合 + 本项目匹配方案 | Codex |
