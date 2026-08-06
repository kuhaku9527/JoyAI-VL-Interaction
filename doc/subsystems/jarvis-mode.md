# Jarvis 模式（产品设计）

> **v1.6（2026-07-11 增补）**：KWS 配置 env 化（§2.5）；模型目录从 `bt-zai-ma` 改名为 `bt-en`；ADR 索引见 §0.
> **v1.5（2026-07-11 重建）**：从被旧转义序列损坏的文档中重建。唤醒词定型 `bt`（自训 KWS v4 已上线）；EXIT_WORDS 8 个；错误日志规范；真机启动踩坑文档化；WebUI 加 LLM/TTS/KWS 服务状态徽章 + LLM 回复面板；KWS 调参建议（针对干净录音）；服务生命周期管理脚本（start-joyai.ps1 / stop-joyai.ps1）。
> **v1.4（2026-07-10）**：唤醒词定型 `bt`（自训 KWS v4 上线，FAR 2% / recall 49%）；EXIT_WORDS 扩为 8 个；错误日志规范；真机启动踩坑文档化。
> **v3.26（2026-07-13）**：memory-store v0.2 hooks 落地（live_adapter push/pull/recall + compose_system_prompt_with_memory）；详见 0-main-direction.md §4 + memory-architecture.md §6。
> **当前状态（v3.26，2026-07-13）**：KWS v4 + Hybrid fresh-window 兜底、流式 ASR、社区量化 LLM、MiniMax TTS、WebUI 可观测链路已落地；视频/VLM 仍经 webinfer。**memory-store v0.2 hooks 已落地**：live_adapter 在 `get_session` fire-and-forget warmup、`_session_cleanup_loop` 与 `handle_reset` end-of-session push、`_build_main_http_messages` 注入 `[Local Wiki] / [本地知识库]` 上下文、`handle_health` 暴露 memory_store 健康字段、`on_cleanup` 关闭 httpx pool；`--no-memory-store` 可关闭。短期对话上下文保留最近 10 轮；Hermes fallback 仍待实施。
> **配套文档**：[asr-streaming.md](asr-streaming.md)（KWS + 流式 ASR 技术实现）｜[memory-architecture.md](memory-architecture.md)（P2 记忆层）｜[screen-capture.md](screen-capture.md)（屏幕捕获）｜[hermes-integration.md](hermes-integration.md)（LLM 接入）

---

## §0 与 asr-streaming.md 的分工

- `doc/jarvis-mode.md`（本文）：产品形态、状态机、唤醒词、EXIT_WORDS、事件响应、错误日志规范、HTTP API、启动踩坑
- `doc/asr-streaming.md`：技术实现层——KWS 引擎选型、sherpa-onnx 安装训练、流式 ASR 调参、性能调优

## §1 核心架构

```
浏览器 mic (16kHz PCM)
     │
     ▼
webui WebRTC
     │
     ▼
jarvis_mode.py
     │
     ├── KWS_LISTENING → sherpa-onnx KWS (CPU 0.1%)
     └── DIALOG_ACTIVE → sherpa-onnx 流式 ASR
                              │
                              ▼
                         LLM (llama-server :7060)
                              │
                              ▼
                         TTS (voice_clone_api :8985)
                              │
                              ▼
                    SpeakerAudioTrack → WebRTC → 浏览器
```

### §1.1 三方通信

- **LLM**：`http://127.0.0.1:7060/v1/chat/completions`（llama-server，JoyAI-VL 8.19B IQ4_NL）
- **TTS**：`http://127.0.0.1:8985/v1/synthesize`（voice_clone_api，BT-7274 voice `vc_<cloud-id>`，最新一次成功克隆的 voice_id 写在 `voices/bt7274/meta.json` 的 `minimax_voice_id` 字段）
- **ASR**：本地 sherpa-onnx（CPU only，~200MB RAM）
- **KWS**：本地 sherpa-onnx（CPU 0.1%，~56MB encoder + ~50KB decoder+joiner）

### §1.2 三个 Python 进程

| 服务 | 端口 | 进程入口 | venv |
|---|---|---|---|
| llama-server | 7060 | `D:\AI\bin\llama.cpp\llama-server.exe` v9330 | — |
| webui | 8099 | `python -m joy_interaction_webui.server` | joyai-main |
| voice_clone_api | 8985 | `python -m uvicorn voice_clone_api.main:app` | joyai-main |

## §2 唤醒词（`bt`）

### §2.1 为什么是 `bt`（2 个 token）

> **"铁御" 是用户身份**（由 jarvis 内部引用 + 唤醒后回应），但**唤醒词**是 `bt`（B + T 两个 token）。

**为什么用 2 token 而不是 1 token 单词（如 "jarvis"/"hey bt"）**：

- 中文 1 token 模型识别 "bt" 时特征稀疏，误识别高
- "bt" 两个字母在 BPE 中天然分两个 token（"B" + "T"），特征清晰
- sherpa-onnx KWS 的 keywords.txt 用 `B T @bt` 格式（@bt 是显示别名）
- 自训 53 段正样本 + 200 段负样本（v4 已上线）

### §2.2 自训 KWS v4（2026-07-10 已落地）

| 项 | 值 |
|---|---|
| 模型路径 | `D:\AI\models\sherpa-onnx\models\kws\bt-en\` |
| 训练数据 | `D:\AI\data\kws\bt-en\positive\bt_segments\` 53 段正样本 + `negative\` 200 段负样本 |
| 编码器大小 | 56MB（chunk-8 流式接口，已修复 2026-07-09）|
| 甜蜜点参数 | `keywords_score=10.0` / `keywords_threshold=0.25` / `trailing_blanks=1` / `max_active_paths=10` |
| sherpa-onnx 直跑 | FAR 15.5% / recall 75.5% |
| **JarvisKWS 包装层**（100ms chunk + 持久流） | **FAR 2.00% / recall 49.06%** |
| 测试脚本 | `services/scripts/test_jarvis_kws_e2e.py` |
| 参数扫描 | `services/scripts/kws_param_sweep.py` |

> ⚠️ **后续补强**：训练集仅 53 段（v5 计划扩到 200+ 段 + MUSAN 负样本），recall 可从 49% → 90%+。

### §2.3 唤醒流程

```
用户喊 "bt"
   ↓
KWS_LISTENING（持续监听，CPU 0.1%）
   ↓ detect
WAKE_DETECTED（命中，播放 wake.wav "铁御，我在"）
   ↓ wake.wav 播完
DIALOG_ACTIVE（流式 ASR + LLM + TTS 全双工）
```

**重要**：唤醒后**必须**先播 wake.wav 给用户**听觉反馈**，否则用户不知道是否被识别（之前项目"喊 bt 被当作杂音"问题的根本原因）。

### §2.5 KWS 配置 env 化（2026-07-11）

`jarvis_mode.JarvisConfig.from_env()` 类方法从环境变量读取 KWS 调参，**默认值不动**，
所以 env 不设时仍是 `score=10.0 / th=0.25 / trailing_blanks=1 / max_active_paths=10`：

| Env | 默认 | 说明 |
| - | - | - |
| `JARVIS_KWS_MODEL_DIR` | `<workspace>/models/sherpa-onnx/models/kws/bt-en` | 模型目录（含 `keywords.txt`、`encoder*chunk-8*.onnx` 等）|
| `JARVIS_KWS_SCORE` | 10.0 | 强 boost 补偿 joiner blank 压制 |
| `JARVIS_KWS_THRESHOLD` | 0.25 | 触发的 acoustic probability 阈值 |
| `JARVIS_KWS_TRAILING_BLANKS` | 1 | 触发后必须紧跟的静音帧数 |
| `JARVIS_KWS_MAX_ACTIVE_PATHS` | 10 | beam search 宽度 |

**改完 env 后**：

```powershell
powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Restart webui
```

无需改源码。env 字符串拼错（比如 `JARVIS_KWS_SCORE=abc`）会打 WARNING 日志回退默认，
不会让 webui 启动崩溃。详见 [adr/0002-kws-config-env.md](adr/0002-kws-config-env.md) 与
[services/webui/tests/test_jarvis_config_env.py](../services/webui/tests/test_jarvis_config_env.py)。


### §2.4 调参建议（2026-07-11，针对干净录音）

用户的 BT-7274 参考音频与 53 段训练集都是**近距离、干净录音**（无风扇/空调电流声、无背景音乐、无多人）。在这种情况下可以**放宽阈值**：

| 参数 | 默认甜蜜点 | 干净录音建议 | 风险 |
|---|---|---|---|
| `keywords_score` | 10.0 | 10.0 → 12.0（更尖锐的判定）| 高分会让 joiner 难触发；过高 → recall 反而掉 |
| `keywords_threshold` | 0.25 | **0.25 → 0.20**（更敏感）| 过低（< 0.15）会触发 "be"/"bit"/"bite" 等近音误报 |
| `num_trailing_blanks` | 1 | 保持 1 | 是 sherpa-onnx KWS 强制要求，不可改 |
| `max_active_paths` | 10 | 保持 10 | 社区默认 4 触发率不够，10 已实测甜蜜点 |

**先小批验证**：

```bash
# 跑参数扫描找当前最优点
python services/scripts/kws_param_sweep.py
# 输出 4 列：score / threshold / recall% / FAR%
```

修改 `services/webui/src/joy_interaction_webui/jarvis_mode.py` 的 `JarvisConfig` 默认值后，**必须重启 webui**（jarvis 是 import 缓存的，老进程不会 reload）。

> 重新提醒：一旦未来用了带底噪/远场的录音（>1m 距离），把 `keywords_threshold` 拉回 0.25-0.30，否则 FAR 会突破 5%。

## §3 状态机（6 个状态）

```python
# services/webui/src/joy_interaction_webui/jarvis_mode.py
class JarvisState(Enum):
    KWS_LISTENING = auto()    # 等待唤醒词，KWS 持续监听
    WAKE_DETECTED = auto()    # 唤醒词命中，播放 wake.wav
    DIALOG_ACTIVE = auto()    # 全双工：流式 ASR + TTS
    TTS_PAUSED    = auto()    # 打断：用户说话时暂停 TTS
    EXIT_DETECTED = auto()    # 退出词命中，播放 goodbye.wav
    ERROR         = auto()    # 不可恢复错误（仅日志）
```

```
KWS_LISTENING ── wake ──> WAKE_DETECTED ──> DIALOG_ACTIVE ─┐
       ▲                                                       │
       │                                                       ▼
       └──────────────── EXIT_DETECTED ←─ EXIT_WORD         TTS_PAUSED
                                  ▲                              ▲
                                  │                              │
                                  └──────── user speaking ───────┘
                                              during TTS
```

详细转换定义见 `services/webui/src/joy_interaction_webui/jarvis_mode.py:300-400`。

## §4 全双工对话（打断 + 静默兜底）

### §4.1 打断（barge-in）

当 TTS 在播时用户开始说话，立即停 TTS + 保留 ASR 流：

```python
# jarvis_mode.py:_handle_dialog()
if self._tts_task and not self._tts_task.done():
    self._tts_task.cancel()
    self._tts_task = None
    self.state = JarvisState.TTS_PAUSED
```

### §4.2 静默兜底（避免 KWS 误触发）

5 秒静默后**重置 KWS 流**（不是关 KWS）：

```python
# jarvis_mode.py:JarvisConfig
silence_before_kws_reset_s: float = 5.0
```

避免长音频 buffer 累积导致 KWS 误判。详见 `services/asr/jarvis/kws.py:JarvisKWS.feed_audio` 的 stream reset 逻辑。

## §5 EXIT_WORDS（肯定词即结束词）

肯定词直接结束本轮对话，BT-7274 回 goodbye.wav 进入 KWS_LISTENING：

```python
# services/webui/src/joy_interaction_webui/jarvis_mode.py:30
EXIT_WORDS = {"行", "明白", "了解", "ok", "好的", "知道了", "谢谢", "感谢"}
```

匹配规则：ASR partial/final 经 `.strip().lower()` 后 **endswith** 任一词。8 个词覆盖口语化肯定词，**不要加 "拜拜/再见"**（用户不会对 AI 说"拜拜"，硬要求反而别扭）。

实测发现加更多退出词容易误触发（"了解"在 BT 戏内是高频词，加多了对话会被频繁打断）。当前 8 个是 2026-07-10 实测最优集合。

## §6 事件响应（预录音频）

唤醒、退出、错误三种状态切换都用预录音频，**不走 TTS 合成**（避免冷启动 + 角色化固定）。

| 事件 | 文件 | 时长 | 来源 |
|---|---|---|---|
| 唤醒成功 | `prompts/bt/events/wake.wav` | ~3s | MiniMax 合成（"铁御，我在"）|
| 退出成功 | `prompts/bt/events/goodbye.wav` | ~2s | MiniMax 合成（"任务完成，断开神经链接"）|
| 错误 | `prompts/bt/events/error.wav` | ~2s | MiniMax 合成 |

**路径解析**：`__post_init__` 自动用 `Path(__file__).parents[4] / "prompts" / "bt" / "events"`，不依赖 cwd。

**注意**：错误事件触发后状态机进 `ERROR`，**只会记日志不会自动恢复**。需要用户重新触发唤醒词（KWS 仍在听）。

## §7 错误日志规范

| 字段 | 格式 | 示例 |
|---|---|---|
| 时间戳 | ISO 8601 UTC（毫秒精度）| `2026-07-10T12:34:56.789Z` |
| 会话 ID | 8 字符 session_id | `a1b2c3d4` |
| 状态 | `KWS_LISTENING` 等 | `DIALOG_ACTIVE` |
| 事件 | `wake_detected` / `asr_partial` / `llm_call` / `tts_start` / `tts_done` / `state_transition` / `error` | `state_transition: KWS_LISTENING -> WAKE_DETECTED` |
| payload | 结构化数据 | `{"wake_score": 12.5, "ms": 234}` |

不允许：

- 纯字符串拼接的"自然语言日志"（难搜索）
- 隐藏 traceback（必须 stack trace 全打）
- 静默失败（异常必须上抛到日志）

## §8 Hermes 接入 + Codex fallback

LLM 调用走 OpenAI-compatible HTTP，**优先 llama-server (7060)**；失败 fallback 到 hermes-agent：

```python
# jarvis_mode.py
llm_api_url: str = "http://127.0.0.1:7060/v1"
llm_model: str = "joyai-vl-interaction-preview-iq4_nl-imat.gguf"
llm_system_prompt: str = "你是铁御，钢铁侠的 AI 助手，简洁回答。"
```

失败 fallback 由 `webinfer` 适配器处理（不在 jarvis_mode 内）。

## §9 HTTP API（3 个端点）

`jarvis_routes.py` 注册 3 个 HTTP 端点供浏览器 UI 调试：

| 端点 | 方法 | 用途 | 响应 |
|---|---|---|---|
| `/api/jarvis/status` | GET | 状态机快照（含 wake_word, is_awake, should_synthesize, should_analyze_frame）| `{exists, state, wake_word, is_awake, ...}` |
| `/api/jarvis/force_state` | POST | 手动强制状态（KWS 还没训好时调试用）| `{state: "DIALOG_ACTIVE"}` |
| `/api/jarvis/stop` | POST | 拆掉会话（peer-connection close 时调用）| `{stopped: true}` |

`/api/jarvis/force_state` 转 DIALOG_ACTIVE 时会自动启动 ASR 流，绕过 KWS 等待。**仅用于开发调试**，生产环境禁开。

## §10 性能对比

### §10.1 关键路径时延（实测）

| 路径 | 旧版（无 jarvis） | jarvis 全栈 |
|---|---|---|
| 唤醒 → 收到 wake.wav | 1-2s | **< 300ms**（本地 KWS + 预录音频） |
| 唤醒 → LLM 首 token | 2-3s | 1.5-2s（流式 ASR + 预热 LLM） |
| LLM → TTS 首 PCM | 1-2s | 0.5-1s（cloud TTS + 流式） |
| 端到端 | 4-7s | **2-3s** |

### §10.2 资源占用

| 模块 | CPU | 内存 | 网络 |
|---|---|---|---|
| KWS（sherpa-onnx） | 0.1% | ~120MB | 0 |
| ASR（sherpa-onnx 流式） | 2-5% | ~200MB | 0 |
| LLM（llama-server IQ4_NL） | GPU 60% | 7GB VRAM | 0 |
| TTS（voice_clone_api MiniMax） | 0.1% | ~50MB | 0.5-1s/upload |
| 浏览器 WebRTC | ~5% | ~150MB | 0 |

## §11 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| KWS 误触发率（FAR）| 看到 bt 形似词就唤醒 | 阈值默认 0.25 + max_paths=10 已压到 2%；如新数据 FAR>5%，回退阈值 0.30 |
| KWS 漏触发率（recall）| 喊 bt 不唤醒 | 训练集从 53 扩到 200+（v5 计划）；快速调低阈值到 0.20 |
| 7 天保活 | voice_clone voice_id 失效 | 月度 cron 自动合成 1 次任意文本；失败时合成时自动 refresh |
| 预录音频文件丢失 | 唤醒/退出无反馈 | `prompts/bt/events/*.wav` 在 git 里；脚本启动时检查存在性 |
| WebRTC NAT | 跨网段无法 P2P | webui 提供 STUN `stun.l.google.com:19302`（默认）|
| llama-server OOM | GPU 16GB 不够 | 5060 Ti 16GB 已实测 IQ4_NL 加载 ~6GB；切换可加 `--n-gpu-layers 25` 部分 CPU 卸载 |

## §12 真机启动踩坑（2026-07-10 18:00 webui 500 + voice_clone 数据丢失）

### 坑 1: webui 报 500 但 jarvis 状态是 KWS_LISTENING

**症状**：浏览器 console 报 `/api/jarvis/status 500`，但服务进程还活着。

**根因**：`jarvis_mode.py` 启动时未把 `services/.pids` 加入 `sys.path`，导致 `from services.asr.jarvis.kws import JarvisKWS` 失败。

**修复**：在 `jarvis_mode.py` 顶部加：
```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
```

### 坑 2: voice_clone_api 重启后 `/v1/voices` 返回 count=0

**根因**：`main.py:63` 的 `DEFAULT_VOICES_DIR = "voices"` 是相对路径。启动时 `Path("voices").resolve()` 在 cwd 解析成 `<cwd>/voices/`，但真实 voices 目录在 `services/voice-clone/voices/`。

**修复**：启动时设环境变量指对路径。
```powershell
$env:VOICES_DIR = "D:\AI\workspace\JoyAI-VL-Interaction-main\services\voice-clone\voices"
Start-Process D:\AI\envs\joyai-main\python.exe -ArgumentList `
  "-m", "uvicorn", "voice_clone_api.main:app", "--port", 8985 `
  -WorkingDirectory D:\AI\workspace\JoyAI-VL-Interaction-main `
  -RedirectStandardOutput D:\AI\logs\voice-clone.log -WindowStyle Hidden
Remove-Item Env:VOICES_DIR
```

### 坑 3: voice_clone_api 启动期 `Form data requires "python-multipart"`

**根因**：joyai-main venv 缺 `python-multipart`（joyai-sherpa venv 装了）。

**修复**：`& D:\AI\envs\joyai-main\python.exe -m pip install python-multipart`（阿里源）

### 坑 4: webui Python import 缓存 → 重启才生效

改 `JarvisConfig` 字段（kws_model_dir/wake_word/tts_voice_id）后，老进程不会 reload，必须 Kill + Start。

**新方案**：用根目录的 `stop-joyai.ps1 -Only <port>` + `start-joyai.ps1 -Restart <name>` 替代手动 Task Manager。

### 坑 5: KWS 启动期报 "no chunk-8 ONNX"

**根因**：sherpa-onnx KWS 要求 encoder/decoder/joiner 带 `chunk-8` 或 `chunk-16` 后缀；如果只下载了 `encoder.onnx` 会用默认 chunk=4，性能和准确率都差。

**修复**：下载完整 prebuilt 模型（含 chunk-8 变种），或自己 export_kws_onnx.py 时显式带 `--chunk-size 8`。

## §13 集成清单（开发者参考）

### §13.1 已有代码

| 文件 | 行数 | 职责 |
|---|---|---|
| `services/asr/jarvis/kws.py` | ~280 | sherpa-onnx KWS 引擎（JarvisKWS 类） |
| `services/asr/jarvis/asr.py` | ~150 | sherpa-onnx 流式 ASR 引擎（JarvisASR 类） |
| `services/webui/src/joy_interaction_webui/jarvis_mode.py` | 625 | 状态机（JarvisStateMachine）+ 模块级 `_load_default_llm_system_prompt` helper + 末尾 `_test_main` standalone smoke test |
| `services/webui/src/joy_interaction_webui/jarvis_session.py` | ~250 | 会话管理（JarvisSessionManager） |
| `services/webui/src/joy_interaction_webui/jarvis_routes.py` | ~285 | HTTP API（3 个端点） |
| `services/webui/src/joy_interaction_webui/static/index.html` | ~8800 | WebUI（LLM/TTS/KWS 状态徽章；`VLM Output Info` 作为单一对话面） |
| `services/scripts/test_jarvis_kws_e2e.py` | ~200 | KWS e2e 测试（recall/FAR） |
| `services/scripts/test_jarvis_state_machine.py` | ~150 | 全链路 e2e 测试 |
| `services/scripts/test_jarvis_state_machine_lite.py` | ~180 | 状态机测试（跳过 KWS/ASR/LLM） |
| `services/scripts/kws_param_sweep.py` | ~80 | KWS 参数扫描（找甜蜜点） |
| `stop-joyai.ps1` (root) | 230 | 一键停止全部 11 服务 + 端口 fallback |
| `start-joyai.ps1` (root) | 50 | 一键启动（包装 run-windows.ps1） |

### §13.2 待开发

- 流式 ASR export-onnx-streaming.py 修复（P4 子代理）
- 记忆层接入 → **v3.25/v3.26 落地**（memory-store v0.1/v0.2 hooks）
- KWS v5 训练数据扩到 200+ 段 + MUSAN 负样本
- hermes-agent 严格隔离 → **v3.27 接入 + v3.28 delegation 触发闭环**（详见 `hermes-integration.md`）

## §14 服务生命周期管理（启动 / 停止）

### §14.1 启动

```powershell
# 默认生产模式（1..12 + webui）
powershell -ExecutionPolicy Bypass -File D:\AI\workspace\JoyAI-VL-Interaction-main\start-joyai.ps1

# 轻量模式（main + webinfer + webui，最小端到端烟雾测试）
powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Mode minimal

# 语音模式（含 voice-clone / CosyVoice / adapters）
powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Mode voice

# 只重启某个服务
powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Restart llama-main
powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Restart voice-clone
```

### §14.2 停止

```powershell
# 一键停掉全部 11 个服务（包括以前手动 Start-Process 起来的进程）
powershell -ExecutionPolicy Bypass -File D:\AI\workspace\JoyAI-VL-Interaction-main\stop-joyai.ps1

# 干跑（只看会杀谁，不真杀）
powershell -ExecutionPolicy Bypass -File stop-joyai.ps1 -DryRun

# 只停某个端口（某个进程发狂时用）
powershell -ExecutionPolicy Bypass -File stop-joyai.ps1 -Only 8985,8090
```

`stop-joyai.ps1` 同时覆盖：

1. `services\.pids\*.pid` 里有记录的服务（`run-windows.ps1` 管理的）
2. 任何在目标端口上 LISTEN 的进程（即使是你以前手动 `Start-Process -WindowStyle Hidden` 起来、没 PID 文件的）

运行后会打印 `[OK] All target ports free` 或 `[WARN] Still listening`。无需再用任务管理器手动杀。

### §14.3 现有 bug 修复

`services\scripts\stop-windows.ps1` 之前用了 `$Pid` 这个 PowerShell **只读内置变量**作为函数参数名，会直接报 `Cannot overwrite variable Pid` 退出（导致用户以前必须用任务管理器）。已修：函数参数改名 `$ProcPid`。

### §14.4 WebUI 文本/语音直达链路与 TTS 播放（v3.9）

> 2026-07-12 当前结论：webui 是唯一链路测试入口；旧 `LLM` 测试按钮已删除并并入纸飞机。不要再新增第二个文本发送按钮。

| 要点 | 位置 |
| - | - |
| `/api/tts/synthesize` HTTP 端点 | `services/webui/src/joy_interaction_webui/server.py` `_tts_synthesize_handler` |
| `build_tts_synthesize_payload()` | PCM16 base64 → RIFF/WAVE 包装 |
| 唯一发送入口 | 纸飞机 `id="promptSendBtn"` → `sendBtPrompt()`，不需开启视频 |
| ASR 测试入口 | 红色麦克风按钮，走浏览器麦克风 → `/asr/ws` → sherpa ASR → `promptText`；可测识别质量，但不是完整 KWS 唤醒链路 |
| 回复显示 | `id="resultTextContent"`，通过 `vlmHistory` 渲染 `Pilot` / `BT-7274` 对话块 |
| TTS 自动播放 | `id="btTtsPlayer"`，WS `llm_reply` 触发 |
| TDD 覆盖 | `services/webui/tests/test_webui_static_contract.py` 守住“纸飞机唯一发送入口”；`services/webui/tests/test_tts_synthesize_endpoint.py` 覆盖 TTS |
| 快捷键 | Cmd/Ctrl + Enter 于 `id="promptText"`，同样调用 `sendBtPrompt()` |

使用流程（不走视频）：

1. 在 `id="promptText"` 输入文字，或点红色麦克风把 ASR 结果写入输入框
2. 点纸飞机 `id="promptSendBtn"`（或 Cmd/Ctrl + Enter）
3. JS `sendBtPrompt()` 调 `POST /api/llm/message`，带当前 WebSocket `sessionId`
4. 后端文本进 `jarvis_mode` → LLM 7060
5. LLM 返回 `llm_reply` WS 事件
6. 浏览器看到：`Pilot` / `BT-7274` 文本进入 `vlmHistory` 并渲染到中间 `VLM Output Info`
7. 浏览器调 `POST /api/tts/synthesize` 拿 WAV，`<audio id="btTtsPlayer">` 自动 play；文本测试模式跳过状态机内置 TTS，避免 MiniMax 双合成
## §15 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-07 | v0.1 | 初版：sherpa-onnx 流式迁移设计 | Codex |
| 2026-07-08 | v1.0 | 大改：升级为 Jarvis 模式（KWS + 流式 ASR + EXIT_WORDS）| Codex |
| 2026-07-09 | v1.1 | 唤醒词定型 `bt`（2 token）；退出词定型为肯定词；error.wav 特殊处理 | Codex |
| 2026-07-09 | v1.2 | `kws.py` 持久流修复（之前每 chunk 新建 stream 导致无法检测）| Codex |
| 2026-07-09 | v1.3 | sherpa-onnx KWS v3 自训（FAR 100% / recall 0%，失败）| Codex |
| 2026-07-10 | v1.4 | KWS v4 自训成功（FAR 2% / recall 49%），唤醒词定型 `bt`；EXIT_WORDS 扩 8 个；错误日志规范；真机启动踩坑（§12）；voice_clone voices 路径修复 | Codex |
| 2026-07-10 | v1.4.1 | 文档重建（jarvis-mode.md 被 `Set-Content` 误覆盖后恢复，§0-§14 全部回填）| Codex |
| 2026-07-11 | v1.5 | 二次重建（被转义序列损坏后从代码 + bt-voice-tmp 快照恢复；§2.4 加 KWS 调参建议；§14 加 start-joyai/stop-joyai；§13 加 webui 状态徽章 + LLM 回复面板；stop-windows.ps1 的 `$Pid` bug 修复）| Codex |
| 2026-07-11 | v1.6 | KWS 配置 env 化（§2.5）；模型目录从 `bt-zai-ma` 改名为 `bt-en`；ADR 索引见 §0 | Codex |
| 2026-07-12 | v3.4 | **放弃 `services/voice-ui` 薄壳（错误方向）**
| 2026-07-12 | v3.5 | **修复"我发送了信息，没看到llm回复"：**根因是 `index.html` 里 `installLlmReplyHandler` 函数定义嵌在 IIFE 内（9088 行），而 `connectWebSocket()` 首次调用（8489 行）发生在 IIFE 之前，且 `window.websocket` 是模块作用域、`window.WebSocket` 替换时已创建的 ws 不被 monkey-patch 覆盖 → 首次 WS 没装上 `llm_reply` 监听器。修复：把 `installLlmReplyHandler` 函数提到顶层（4088 行），在 `connectWebSocket` 内 `new WebSocket()` 后立即调用兜底。诊断：用 `services/.logs/diag_ws.py` 模拟浏览器 WS + POST `/api/llm/message` → 后端 5.1s 正常回 `llm_reply`，确认 bug 在前端；同时 webui 启动改为 `python -u webui_launch.py` + stderr/stdout 重定向（之前 Start-Background 没设 RedirectStandardOutput/Error，所有 .logs/*.log 都是 0 字节） |；直接改 webui：清理 12,679 行 index.html 里的重复 `<html><head><body>` 块（3457-7150）+ 重复状态徽章 + 重复 `llmReplySection` div（缩到 8,985 行）；新增 `POST /api/tts/synthesize` 端点（代理 voice_clone_api，`build_tts_synthesize_payload` 把 PCM16 包成 RIFF/WAVE 给 `<audio>` 播）；曾新增旧 `id="llmTestSendBtn"` 文本测试按钮（v3.9 已删除并入纸飞机）+ `id="btTtsPlayer"` 自动播放 audio；WS `llm_reply` 触发 TTS 链路；17/17 测试绿 | Codex |
| 2026-07-12 | v3.6 | **对齐 webui 单一对话面：**删除右上角冗余 `llmReplySection` / `llmReplyList` 方案，旧 LLM 测试按钮发送后直接把 `[Pilot]` 和 `[jarvis]` 追加到中间 `VLM Output Info` 的 `resultTextContent`。修复旧 `sendLlmTestPrompt()` 错用 `window.sessionId` 导致 POST session 与 WebSocket session 不一致的问题；状态轮询同样改用当前 `sessionId`。DevTools 实测历史旧入口：点击 `LLM` → `/api/llm/message` 200 → WS `llm_reply` → 中间框出现 `[jarvis]Confirmed.` → `/api/tts/synthesize` 200 → `<audio>` 拿到 blob 并播放完成。新增前端静态契约测试，webui 测试 20/20 通过。 | Codex |
| 2026-07-12 | v3.7 | **修复“可听但看不到对话”：**根因是手动 append 到 `resultTextContent`，但外层 `resultText` 被原 VLM 渲染逻辑按 `vlmHistory.length` 置为 `display:none`。修复：新增 `jarvis_dialog` 历史类型，`Pilot` / `BT-7274` 消息进入 `vlmHistory` 后由 `createJarvisDialogNode()` 渲染；只要有 Jarvis 对话，中间 `VLM Output Info` 强制可见。语音链路新增 `pilot_utterance` WS 事件：ASR 定稿后先显示 Pilot 文本，再发 LLM。文本测试模式 `POST /api/llm/message` 调 `_send_to_llm(..., stream_tts=False)`，避免状态机内置 TTS + 浏览器 TTS 双合成。并过滤前端 `undefined/null` 模型名，补 `VLMService.set_model()` 防日志噪音。DevTools 实测：中间框显示 `Pilot` 与 `BT-7274`，音频 blob 播放完成，日志只出现一次 `/api/tts/synthesize`，webui 测试 24/24 通过。 | Codex |
| 2026-07-12 | v3.8 | **修复 ASR 文本“删不掉又回来”：**红色麦克风 ASR 输入会把识别结果累积到 `asrFinalText/asrPartialText`，用户手动清空输入框只清 DOM，旧缓存和后端流式 ASR 段仍会把旧字吐回来。修复：`promptText input` 改为 `handlePromptManualInput()`，同步重置前端 ASR 累积状态；录音中手动编辑/清空时发送 `segment_end`，关闭旧 ASR websocket 并新建一段；旧 websocket 的 message/close/error 通过 `asrWs !== ws` 忽略，避免误停录音。webui 测试 25/25 通过。 | Codex |
| 2026-07-12 | v3.9 | **纸飞机成为唯一发送入口：**删除当前 DOM 中的 `id="llmTestSendBtn"` 文本测试按钮，`promptSendBtn` 点击、Cmd/Ctrl + Enter、ASR 结束自动发送全部统一到 `sendBtPrompt()`。程序化发送后同步 `resetAsrTranscriptState("")` / `resetActiveAsrSegment()`，避免旧 ASR 文本复活。静态契约测试守住“纸飞机唯一发送入口”，webui 测试 26/26 通过。 | Codex |
| 2026-07-12 | v3.10 | **ASR 独立于红色 Start + 修复 fallback 旧文字复活：**根因 1：`startSpeech()` 仍保留源项目视频分析门禁 `!isAnalysisRunning`，导致未点红色 Start 时 ASR 拿到麦克风后立即 `stopSpeech()`；已移除该门禁。根因 2：`/ws/asr` 外部 ASR 不可达时使用全局 in-process sherpa-onnx fallback，新连接没有重置 `engine.last_text`，会把上一轮识别作为新 partial 推回前端；已在 `connect_asr_inproc()` 每次连接 `engine.start()`，并让 `segment_end` 清空当前 fallback 流。webui 测试 28/28 通过。 | Codex |
| 2026-07-12 | v3.11 | **ASR 发送态收口：**页面实测发现发送后红色麦克风仍处于录音态，`asrPartialText` 会继续把长文本灌回 `promptText`，同时 sherpa partial 会暴露 `</s>` 控制 token。修复：`sendBtPrompt()` 在 POST 前若 ASR 活跃则 `await stopSpeech({ sendEnd:false, sendPrompt:false })`，发送后不再重开 ASR segment；新增 `sanitizeAsrTranscriptText()` 清理 `</s>` 和多余空白；新增 spec `doc/specs/webui-asr-input-state.md`。webui 测试 30/30 通过。 | Codex |
| 2026-07-12 | v3.12 | **BT 延迟 HUD + ASR 启动优化：**左上角新增 BT 链路指标 `ASR/LLM/TTS/E2E`，前端记录 ASR start→connected/first partial、send→llm_reply、tts fetch→audio ready；左侧源项目设置改名为 `Video/VLM Settings` 并标注只影响红色 Start 视频/VLM，不影响 BT chat/ASR/TTS；ASR 默认从外部 `8994` 改为 in-process sherpa 优先，除非显式设置 `ASR_URL`，并在 webui startup 后台 warm 本地 ASR，减少第一次点击麦克风的冷启动体感。webui 测试 35/35 通过。 | Codex |
| 2026-07-12 | v3.13 | **WebUI 独立 KWS 监听链路：**新增 spec `doc/specs/webui-kws-listening-chain.md`；明确红色 Start=视频/VLM、红麦克风=一次性 ASR 输入、监听按钮=常驻 KWS。`/offer` 对 audio offer 创建 Jarvis session，绑定 `MicAudioTrack` 消费浏览器麦克风，并把 `SpeakerAudioTrack` 加回 peer connection 播放 wake/TTS；前端新增 `btListenBtn`，启动前清理旧 Jarvis session，停止时调用 `/api/jarvis/stop`。修正 `kws_param_sweep.py` 每个 wav 前重置 KWS stream；可信 sweep 结果仍为 `score=10.0 / threshold=0.25` 最佳（recall 49.06%，FAR 2.00%），不改 env 默认。 | Codex |
| 2026-07-12 | v3.14 | **监听链路实机验证 + startBtListening 清理旧 session：**真实麦克风 13:48:56 触发 `Wake word detected: 'bt'` 全链路通；`feed_wav` 注入 5s 样本也立即 DIALOG_ACTIVE；`startBtListening` 进入时立即 `POST /api/jarvis/stop`，避免上一次 state 卡在 TTS_PAUSED 阻止重新进入 KWS_LISTENING。`doc/jarvis-mode.md` §14.7 记录结论与复测步骤。 | Codex |
| 2026-07-12 | v3.15 | **唤醒积压 drain + 麦克风增益 slider：**`_handle_kws` 在 wake 后 `play_wake_wav` 前后两次 drain 音频队列，防止 ASR 吞 4.6s wake.wav 期间累积麦克风音频；前端 HUD 加 `GAIN` select (1.0x–3.0x 默认 1.5x) 通过 Web Audio GainNode 实时调 KWS 输入能量；TDD `test_wake_drain.py` 2 用例 PASS；sweep 验证降 threshold 在当前 v4 无效，主推增益 + 重训 v5。 | Codex |
| 2026-07-12 | v3.16 | **feed_wav 任务生命周期：**`JarvisSession._feed_task` 跟踪 feed 任务，新调用 + session.stop() 自动取消；`feed_wav_to_session(max_duration_s=N)` 硬时长上限，默认 30s 从 `JARVIS_FEED_MAX_DURATION_S` env 读；handler `await feed_task` 捕获 `CancelledError`。`test_feed_task_lifecycle.py` 3 用例 PASS，全套 48 passed。修根因：客户端断开后服务端协程继续推 PCM 导致 ASR/LLM 死循环。 | Codex |
| 2026-07-12 | v3.17 | **Hybrid KWS + ASR 二次唤醒确认：**新状态 `WAIT_ASR_CONFIRM`（KWS fire → ASR 1.2s 内匹配 bt 模式才放 wake.wav）。`asr_confirm_timeout_s` (env `JARVIS_ASR_CONFIRM_TIMEOUT_S`) + `asr_confirm_patterns` 默认 `("bt","BT","B T","b t")`。误唤醒回 KWS_LISTENING 静默不响 TTS。`test_hybrid_wake.py` 4 用例 PASS；全套 52 passed。注意：Hybrid 降 false alarm，不提升 KWS 未触发时的召回；漏唤醒仍要优化 KWS 模型/数据。 | Codex |
| 2026-07-12 | v3.18 | **Prewarm 引擎解决 1.2s ASR 冷启动吞 confirm 窗口：**根因：ASR sherpa-onnx 首次加载 ~1.2s 恶名同 `asr_confirm_timeout_s=1.2s`，KWS fire 后 1.2s 全花在 ONNX 加载上。实验室麦 15.36s 录音 (·mic_captures/mic_1783844050536.wav·) 里 KWS 触发 3 次全部被 hybrid 静默 reject。修法：新增 `JarvisStateMachine.prewarm_engines()`，`JarvisSession.start()` 里先 `await loop.run_in_executor(_init_kws) + run_in_executor(_init_asr)` 再开 bg loop。`test_session_prewarm.py` 3 用例 PASS；全套 55 passed。体感：首次点 Listen 多等 ~3-4s（一次性 KWS + ASR 冷启动），后续每次唤醒均可秒级确认。详见 §14.11。 | Codex |
| 2026-07-12 | v3.19 | **Hybrid confirm 时序修正：**移除 post-wake pre-confirm drain，`_handle_kws(pcm)` 对触发 KWS 的同一片 PCM 做 inline ASR tap；`WAIT_ASR_CONFIRM` 循环不再每片 sleep 100ms，并记录 ASR partial。解决“只说 BT 后队列里只剩静音，ASR confirm 永远听不到 BT”的时序 bug。`test_hybrid_wake_no_pre_confirm_drain.py` 3 用例 PASS。 | Codex |
| 2026-07-12 | v3.20 | **KWS 召回优化转向真实样本闭环：**完整 sweep 证明 `threshold 0.25 -> 0.20` 无召回收益（49.06% 不变），`score=8` FAR 升至 9%，`score=12` recall 降至 13.21%，所以不改默认 `score=10/th=0.25`。新增 KWS diagnostic capture（保存 live 16k PCM 到 `<workspace>/data/kws/mic_captures`）和 KWS shadow ASR 日志（监听态只诊断，不唤醒），用于回答“没唤醒时 ASR 听成什么”和沉淀 v5 训练样本。 | Codex |
| 2026-07-12 | v3.21 | **Fresh-window KWS probe 修实时 stream miss：**实测用户喊 BT 后未唤醒，但保存的 `kws_live_1783848515550_0002...wav` 离线 KWS 可命中，说明长实时 stream 边界/前序音频污染导致 miss。新增 `JarvisKWS.detect_in_pcm()`，在实时 KWS miss 时每 0.5s 对最近 rolling PCM 新建干净 stream 再跑一次 KWS；fresh-window 命中时直接 wake（用于当前召回测试），不依赖 ASR confirm。`test_rolling_kws_probe_can_wake_when_live_stream_misses` 覆盖此路径；全套 65 passed。 | Codex |

| 2026-07-12 | v3.22 | **修复 webui LLM 回复整条链路静默丢失 (`session_websockets` 双 dict 隔离):** 根因是 `python -m joy_interaction_webui.server` 把 server.py 加载为 `__main__`,但 `jarvis_session._make_llm_callback` 里 `from .server import notify_session_llm_reply` 又按 dotted name 重新加载为 `joy_interaction_webui.server` -- 两个模块实例,`session_websockets` 是两个独立 defaultdict。`websocket_handler` 写 `__main__.session_websockets`(id 一致),而 `notify_session_llm_reply` 通过 `joy_interaction_webui.server.session_websockets` 读 (id 不同,永远 0 键)。`send_to_session` 永远 `total sessions in dict: 0` + `Message DROPPED`,前端 `vlmHistory` 始终只有 Pilot 没有 BT-7274。修复: server.py 顶部 `if __name__ == "__main__": sys.modules.setdefault("joy_interaction_webui.server", sys.modules["__main__"])`,让 dotted-name import 复用 `__main__`。诊断:`sys.modules` 比对 + dict `id()` 差异确认是双模块而非 dict 被清空。验证: post `bt 链路测试` -> 后端日志 `LLM response: '链路建立正常,Pilot 可达.'` + `POST /api/tts/synthesize 200` 422KB -> 浏览器 `VLM Output Info` 中 `Pilot` + `BT-7274` 块出现,HUD 链路指标 LLM 3.3s / TTS 1.2s / E2E 4.5s。 | Codex |

| 2026-07-12 | v3.23 | **Hybrid confirm 兜底: WAIT_ASR_CONFIRM 超时前跑 fresh-window KWS probe:** 根因是 streaming-paraformer 模型对两音节 bt 唤醒词只输出 b,1.2s 内永远不匹配 bt/BT/B T/b t,即使 live KWS 已经命中,Hybrid confirm 路径超时回到 KWS_LISTENING,wake 整体丢失。修复: 在 `_wait_asr_confirm_timeout` 超时返回前调用 `_probe_kws_fresh_window(..., bypass_min_s=True)`,fresh-stream KWS 对捕获 PCM 干净流上重新判一次;命中则 `_direct_wake_from_kws` 跳过 ASR confirm 直接进 WAKE_DETECTED -> 播 wake.wav -> DIALOG_ACTIVE。配套:_handle_kws 命中时把 peak/rms 存到 _last_wake_peak/rms,recovery 路径用真实值而非合成值;_probe_kws_fresh_window 加 bypass_min_s 参数让 recovery 不受 1s min_s 门槛限制。验证: 实测 positive_0002.wav(0.6s) -> live KWS fire -> ASR partial "" -> 1.2s timeout -> fresh-window probe 命中 bt -> Direct wake -> wake.wav (2.3s) 播放 -> DIALOG_ACTIVE。新增 `test_hybrid_recovery.py` 2 用例覆盖(命中路径 + 双失败回退)。全套 76/76 通过。 | Codex |
| 2026-07-12 | v3.24 | **Jarvis 短期上下文管理 + 启动链路收敛：** `_send_to_llm` 在 system prompt 与当前用户消息之间注入最近 10 轮 Pilot/BT 对话，使用 `deque(maxlen=20)` 限界，响应后再追加本轮；新增 3 个回归测试覆盖首轮无历史、第二轮携带历史和 10 轮截断。统一 Windows 默认/voice/gaming 启动计划为 `7060 + 8070 + 8099 + 8985`，WebUI 本机 HTTP；删除 CosyVoice 专用脚本、不可达 stub 分支和 8992 启动入口。验证：WebUI 79/79、voice-clone 11/11、三模式 DryRun 均通过。 | Codex |
| 2026-07-13 | v3.25 | **memory-store v0.1 skeleton + 前端 vlm-history CSS 修复（落地 v3.2 #3 记忆持久化骨架）：** 新增 `services/memory-store/`，端口 8996，端点 `/v1/blocks/push|recall` + `/health` + `/v1/backends`；SqliteBackend (FTS5 BM25)，Psql/Obsidian 占位 `NotImplementedError`；schema 留 score/last_hit_at/hit_count，runtime 默认值（recency decay v0.2 再做）；conftest autouse fixture 在 `tmp_path` 单测，模块级 `_reset_backend_for_tests()` 解决 ASGITransport 不触发 lifespan 的问题；端口冲突 pre-bind `socket.bind()` → rc=2；16/16 测试通过（`tests/test_sqlite_backend.py` 8、`test_app.py` 6、`test_port_conflict.py` 1）。**前端 `services/webui/.../static/index.html` CSS patch**（1563 行附近）：覆盖 `.result-text.vlm-history-shell { min-height:0 }` + `:has(#vlmHistoryEmpty:not([style*='display: none']))` 240px empty-state 兜底 + `.vlm-history { max-height: min(60dvh, 560px) }`，解决 `VLM Output Info` 空态留 120px strip + 对话增长后框不长大。**生命周期**：`run-windows.ps1` 加 `$P.MemoryStore = 8996` + `Start-MemoryStore`（env `JOYAI_ENABLE_MEMORY_STORE=1` opt-in 默认 false，避免 v3.x 启动回归）；`stop-joyai.ps1` `$AllPorts` 加 8996。`live_adapter.py` 不动（ADR 0005 D 锁定 v0.1 边界）。详见 `doc/specs/memory-store-skeleton-spec.md` + `doc/adr/0005-memory-store-start.md` + `DELIVERY.md §7 v3.25`。 | Codex |

### §14.5 BT 延迟基线（v3.12，2026-07-12）

页面左上角 BT 链路 HUD 实测基线（短句 `BT 在吗`，无视频，红麦克风→纸飞机发送）：

| 段 | 实测 | 说明 |
| - | - | - |
| ASR 连接 | ~100ms | 麦克风权限 + ASR WS `status=connected` 到达 |
| LLM 回复 | ~7s | POST `/api/llm/message` → `llm_reply` WS 到达 |
| TTS 合成 | ~3s | `/api/tts/synthesize` 返回 WAV blob |
| 端到端 | ~10s | sendStartAt → ttsReadyAt |

#### 后续优化方向

| 段 | 候选 | 风险 |
| - | - | - |
| LLM | 切更小量化档、减 system prompt、关闭过度 preamble | 质量下降 |
| LLM | `_send_to_llm` 改成流式返回 `llm_reply` | 改协议 |
| TTS | `MINIMAX` 切 streaming TTS | 换上游协议 |
| 串行 | `llm_message` 立刻 200，LLM 通过 WS 推，前端 WS 收到就触发 TTS | 需测试 reject/error 路径 |


### §14.6 WebUI 独立 KWS 监听链路（v3.13，2026-07-12）

> 设计 spec：`doc/specs/webui-kws-listening-chain.md`。

三类入口边界：

| 入口 | 作用 | 不承担 |
| - | - | - |
| 红色 Start | 视频/VLM 分析 | 不启动 Jarvis KWS 监听 |
| 红色麦克风 | 一次性 ASR 输入到 `promptText` | 不代表常驻唤醒监听 |
| `btListenBtn` 监听按钮 | 常驻 KWS：浏览器 mic -> WebRTC audio-only -> Jarvis KWS/ASR/LLM/TTS | 不启动视频/VLM，不替代纸飞机发送 |

监听链路：

```text
浏览器 btListenBtn
  -> getUserMedia(audio-only, NVIDIA Broadcast 可作为系统输入源)
  -> RTCPeerConnection addTransceiver('audio', sendrecv)
  -> POST /offer { session_id, jarvis_audio: true }
  -> server bind_jarvis_audio_for_peer()
  -> MicAudioTrack.recv() 持续消费浏览器音频并喂 JarvisStateMachine
  -> KWS_LISTENING -> WAKE_DETECTED -> DIALOG_ACTIVE
  -> SpeakerAudioTrack -> 浏览器 btListenPlayer 播放 wake/TTS
```

可信 KWS sweep（修正为每个 wav 前 `kws.start()`）：

| score | threshold | recall | FAR | 结论 |
| -: | -: | -: | -: | - |
| 10.0 | 0.25 | 49.06% | 2.00% | 当前最佳，保持默认 |
| 10.0 | 0.20 | 49.06% | 2.00% | 无收益 |
| 8.0 | 0.25 | 49.06% | 9.00% | FAR 过高 |
| 8.0 | 0.20 | 49.06% | 9.50% | FAR 过高 |
| 12.0 | 0.25 | 13.21% | 1.50% | 召回过低 |

结论：这次不改 `JARVIS_KWS_SCORE=10.0` / `JARVIS_KWS_THRESHOLD=0.25`。下一步必须做真实浏览器监听验收；若用户实际喊 BT 召回仍低，优先补 KWS 正样本，而不是继续盲扫阈值。
### §14.7 监听链路实机验证（v3.14，2026-07-12）

**结论：监听链路可用。** 13:48:56 真实麦克风成功触发 `Wake word detected: 'bt'` 并完成 `DIALOG_ACTIVE -> ASR -> LLM -> TTS` 全链路；前端 `/api/jarvis/feed_wav` 注入 `<workspace>/data/kws/bt-en/test_bt_5s.wav`（16kHz mono int16，前 5s）也立即进入 `DIALOG_ACTIVE`，证明 model + state machine + audio_output + LLM/TTS 路径全部正常。

**唯一暴露的问题：** `startBtListening()` 之前不清理旧的 Jarvis session，第一次唤醒后注入样本造成 state 一直 `TTS_PAUSED`，再点监听也不会回到 `KWS_LISTENING`。

**修复（v3.14）：** `startBtListening()` 进入时立即 `POST /api/jarvis/stop { session_id }`，确保每次进入监听都是 `KWS_LISTENING` 起点。代码改动：`services/webui/src/joy_interaction_webui/static/index.html` 中 `btListeningStarting = true` 之后调用 `await fetch('/api/jarvis/stop', ...)`。前端热刷新即可生效，无需重启 8099。

**用户复测步骤：**

1. 浏览器刷新 `http://127.0.0.1:8099/`。
2. 点击右下角“监听”按钮，按钮变“停止监听”。
3. 清晰说出 `BT`，观察状态条变为“唤醒已触发” -> “对话中”。
4. 说出退出词，状态回到 “KWS 监听中”。

**已知遗留：** 麦克风链路使用 `echoCancellation:true, noiseSuppression:false, autoGainControl:false`，NVIDIA Broadcast 在系统层进一步做 VAD/EC，可能影响清晰度。如果复测 wake 不稳定，下一步优先用 §14.12 的 live capture 收集真实样本，不再盲目降低阈值。

### §14.8 唤醒后语音积压修复 + 麦克风增益（v3.15，2026-07-12）

**问题 1：唤醒后积压。** 之前 `_handle_kws()` 触发 wake 后，state 进入 `WAKE_DETECTED` -> 播放 `wake.wav`（约 4.6s）。期间 `run()` 循环阻塞在 `play_wake_wav()`，但 `feed_audio()` 仍不断往 `_audio_queue` 推麦克风 PCM。播放结束后转 `DIALOG_ACTIVE`，ASR 把 `wake.wav` 期间累积的 4.6s 麦克风音频一口气吃完，LLM 收到 `bt bt bt ...` 长串。

**修复（v3.15）：** 在 `_handle_kws()` 中：

1. wake 检测到立即 `await self._drain_pending_audio(reason="post-wake-pre-wav")`，丢掉识别 wake 本身的 chunk。
2. `play_wake_wav()` 之后再 `await self._drain_pending_audio(reason="post-wake-wav")`，丢掉 4.6s 播放期间累积的麦克风音频。

> v3.19 修正：Hybrid confirm 前不能 drain，否则 ASR 听不到短促的 `BT` wake phrase。v3.15 的 pre-wake drain 仅作为历史记录；当前代码在 KWS fire 后会 inline tap 触发 KWS 的同一片 PCM 给 ASR。

代码改动：`services/webui/src/joy_interaction_webui/jarvis_mode.py` 新增 `_drain_pending_audio` 方法 + `_handle_kws()` 两处 drain 调用。

**测试：** `services/webui/tests/test_wake_drain.py` 2 个用例（idempotent on empty queue + drains all queued chunks）PASS。全套 45 passed in 1.77s。

**验证：** PID 8100 重启后 `feed_wav` 注入 5s `test_bt_5s.wav` 触发一次 wake，`Drained N queued audio chunks` 日志出现 1 次，之后 ASR endpoint 只处理 `wake.wav` 播放结束后的新音频，没有 wake 重复回放。

**问题 2：唤醒概率低 / 麦克风电平偏低。** MIC RMS 显示 5%/22%/20% 峰值，22% 在日常说话里偏低。NVIDIA Broadcast 系统层 VAD/EC 可能进一步削弱 `BT` 这种短促词。

**前端优化（v3.15）：** HUD chip 区新增 GAIN select（1.0x / 1.5x / 2.0x / 2.5x / 3.0x，默认 1.5x）。`startBtListening()` 用 Web Audio API `MediaStreamSource -> GainNode -> MediaStreamDestination`，把增益后的音轨替换 WebRTC 发送的 `audioTrack`。`change` 事件实时调用 `gain.setTargetAtTime(v, ...)`，无需重连 `RTCPeerConnection`。

**降阈值是否有用：** sweep 数据证明 `score=10.0, th=0.25` 与 `th=0.20` 召回率/FAR 完全相同（49.06% / 2.00%），测试集内 0.20-0.25 区间无样本。所以单纯改 `JARVIS_KWS_THRESHOLD` 帮助有限，应该走 live capture + 重新录更贴近真实链路的样本训 v5。

**NVIDIA Broadcast 影响：** 用户 mic 链路是 `echoCancellation:true, noiseSuppression:false, autoGainControl:false`，但 NVIDIA Broadcast 在系统层独立做 VAD/EC/降噪，对 `BT` 这种 2-syllable 短词更敏感。如果增益拉到 2.0x 仍不理想，下一步用 §14.12 的 shadow ASR 和 capture 判断 Broadcast 是否削掉了短音。

**后续 v5 模型路线：** 增益 + 重新录 BT 样本（更长、更清晰、覆盖不同距离/语速/音量）训 v5 是根本路径，threshold/score 微调只能补丁。

### §14.9 feed_wav 任务生命周期（v3.16，2026-07-12）

**问题：** `POST /api/jarvis/feed_wav` 启动后是一个 100ms 步进的循环（5s wav 约 50 步）。HTTP 客户端如果断开（超时、`Invoke-RestMethod` 中断、Ctrl-C），aiohttp 不会通知服务端协程，`feed_wav` 协程继续在后台推 PCM，导致 ASR 持续触发 endpoint、LLM 持续响应、TTS 持续播放，形成循环。靠 `POST /api/jarvis/stop` 才能打断。

**三层修复（v3.16）：**

1. **任务追踪：** `JarvisSession._feed_task` 保存最近一次 `feed_wav` 的 `asyncio.Task`。新一次 `feed_wav` 调用通过 `attach_feed_task()` 自动取消旧的；`session.stop()` 也会取消在飞的 feed task。
2. **硬时长上限：** `feed_wav_to_session(..., max_duration_s=N)` 在循环里 `time.time() - start_ts >= N` 时 `break` 并日志 `feed_wav hit max_duration=N.Ns, stopping`。`jarvis_feed_wav` handler 从 `data.max_duration_s` 或 `JARVIS_FEED_MAX_DURATION_S` env（默认 30s）读上限。
3. **Cancellable 响应：** handler 把 `feed_wav_to_session(...)` 包成 `asyncio.create_task` 然后 `await feed_task`，捕获 `asyncio.CancelledError` 返回 `{"cancelled": true}` 200，便于客户端主动取消也能正确收到响应。

> 注：尝试注册 `request.transport.add_done_callback` 在 Windows 的 `_ProactorSocketTransport` 上不存在，会 500。所以客户端断开单靠 max_duration 兜底 + 用户主动 stop。

**测试：** `services/webui/tests/test_feed_task_lifecycle.py` 3 个用例 PASS：`attach_feed_task` 取消前一个；`session.stop()` 取消 `_feed_task`；`feed_wav_to_session` 在 `max_duration_s` 触发后早停。

全套 48 passed in 2.26s。

### §14.10 Hybrid KWS + ASR 二次唤醒确认 (v3.17, 2026-07-12)

**问题：** sherpa-onnx v4 + `bt-en` 模型（6 token BPE）离线召回率约 49%。调麦克风增益 / 降阈值 / 关 Broadcast VAD 都没法突破这个天花板；`BT` 只有两个短音节，live mic + VAD 切尾音下很容易漏。纯 ASR 文本匹配（`if text contains "bt" -> wake`）也不适合作为主链路：ASR partial 飘得厉害，文本匹配要么 false positive 高，要么要等 final 约 2s 才响应。

**方案：** 在 KWS fire 和 WAKE_DETECTED 之间插一个新状态 WAIT_ASR_CONFIRM。

`
KWS_LISTENING ─KWS fire─> WAIT_ASR_CONFIRM ─ASR 1.2s 内含 bt 模式─> WAKE_DETECTED
                            │                                     └─> DIALOG_ACTIVE
                            │
                            └──1.2s 超时 / ASR 无 bt / KWS false alarm──> KWS_LISTENING
`

**关键设计：**
- KWS fire 后立刻 drain 音频队列 (v3.15 已有)
- WAIT_ASR_CONFIRM 状态启动 ASR streaming + 起 1.2s 超时任务
- 每个 ASR partial/final 喂入 _asr_confirm_match(text) — 大小写不敏感子串匹配 ("bt" / "BT" / "B T" / "b t")
- 命中 → _promote_from_confirm 取消超时任务、走 WAKE_DETECTED → wake.wav → DIALOG_ACTIVE
- 超时 → _reset_to_kws 直接回 KWS，不放 wake.wav、不发 LLM、不响 TTS（false alarm 静默）
- 1.2s 是 KWS fire 到 wake.wav 的延迟预算；足够 ASR 200-400ms 首 token + 几轮 partial

**配置：** `asr_confirm_timeout_s`（默认 1.2，可通过 `JARVIS_ASR_CONFIRM_TIMEOUT_S` env 调）；`asr_confirm_patterns` 默认 `("bt", "BT", "B T", "b t")`。

**实现位置：**
- services/webui/src/joy_interaction_webui/jarvis_mode.py
  - JarvisState.WAIT_ASR_CONFIRM 新枚举值
  - _handle_kws 改写：fire 后转 WAIT_ASR_CONFIRM (不再直接 wake.wav)
  - _handle_wait_asr_confirm(pcm) 新方法：喂 ASR + 匹配检测
  - _wait_asr_confirm_timeout() 新协程：1.2s 兜底
  - _promote_from_confirm() 新方法：取消超时 + 走原 wake.wav/DIALOG_ACTIVE 流程
  - _asr_confirm_match(text) 新方法：子串匹配 (大小写不敏感)
  - `run()` loop 加 `WAIT_ASR_CONFIRM` 分支
  - _reset_to_kws 加 _confirm_task 取消
- doc/specs/hybrid-wake-confirm.md 新 spec

**测试：** services/webui/tests/test_hybrid_wake.py 4 个用例 PASS：
- `test_kws_fire_enters_wait_asr_confirm` — 状态正确转换
- `test_asr_match_promotes_to_dialog_active` — 命中流程
- `test_asr_no_match_timeout_returns_to_kws` — false alarm 静默回 KWS
- `test_asr_confirm_match_helper` — 子串匹配覆盖 "bt" / "BT" / "B T" / "b t" / "hey bt" / "okay BT-7274"，排除 "hello" / "bet" / "but"

全套 **52 passed in 2.63s**。

### §14.11 Prewarm 引擎 — 修 ASR 冷启动吞 confirm 窗口 (v3.18, 2026-07-12)

**实机现象：** 真麦 15.36s 录音 `mic_captures/mic_1783844050536.wav` 里 KWS 触发 3 次，但 3 次全部被 hybrid 静默 reject 回 KWS_LISTENING — 用户感受「唤不醒」。日志看到：

```
16:14:35.345  KWS fires (✓)
16:14:35-36   ASR model loading 1.2s   ← 整个 confirm 窗口被冷启动吃掉
16:14:36.582  ASR ready
16:14:38.851  1.2s timeout → reject
```

**根因：** `_init_asr()` 在 `_handle_kws` 里 lazy 调用，但 ASR sherpa-onnx (~200MB) 首次加载耗时 ~1.2s，正好等于 `asr_confirm_timeout_s`。KWS 一 fire，1.2s 全花在 ONNX 加载上，ASR 连一帧都没处理过 timeout 就触发。

**修法：** 会话创建时立刻把 KWS + ASR 都 load 完，再开 bg loop。新增 `JarvisStateMachine.prewarm_engines()`：

```python
async def prewarm_engines(self) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, self._init_kws)  # ~10MB / ~0.3s
    await loop.run_in_executor(None, self._init_asr)  # ~200MB / ~1.2s
```

`JarvisSession.start()` 在 `create_task(run)` 之前 `await prewarm_engines()`。冷启动成本从「每次唤醒付 1.2s」变成「首次点 Listen 付 ~3-4s 一次性」，之后每次 wake 都可秒级走完 hybrid 流程。

**适用性：** ASR 冷启动是 sherpa-onnx 不可避免的开销，prewarm 是行业惯例（sherpa-onnx 官方 example 启动时 warm）。

**为什么不用更小的 confirm window：** confirm window 已经是最小可工作值（ASR 首 token 200-400ms + 几轮 partial）。继续缩短会让「用户刚说 BT 还没说完」就被判 false alarm。

**前端体感：** 用户点 Listen 后会看到 `btListenBtn.disabled = True` 大约 3-4s（prewarm 进行中），期间页面无明显提示。后续可加 `Prewarming models...` 角标 — 见 §14.12 待办。

**TDD：** `services/webui/tests/test_session_prewarm.py` 3 用例 PASS：
- `test_session_start_prewarms_kws_and_asr` — `start()` 返回后 `sm._kws` 与 `sm._asr` 都非 None
- `test_prewarm_idempotent_on_second_start_attempt` — 第二次 prewarm 不重复加载
- `test_kws_confirm_window_no_longer_eaten_by_asr_init` — KWS fire 后下一帧 ASR 已能接收 chunk

全套 **55 passed in 2.73s**。

**用户验证步骤：**
1. `powershell -ExecutionPolicy Bypass -File stop-joyai.ps1 -Only 8099`
2. 重启 v3.18 8099: `Start-Process python services\\.logs\webui_launch.py` (已用 hidden window 启动)
3. 刷新 `http://127.0.0.1:8099/`，点 Listen，等 ~3-4s 模型加载
4. 等状态变 `KWS 监听中`，说 `BT`，看 HUD 是否进入 `唤醒已触发 → 对话中`
5. 若仍 false alarm，检查 `services\.logs\webui.err.log` 找 `WAIT_ASR_CONFIRM timeout`，需进一步拉长 prewarm 或 timeout


**实测预期（已修正）：**
- Hybrid 只处理 `KWS fire` 之后的确认，能降低 false alarm，不会提升 KWS 未触发时的召回。
- 漏唤醒（用户说了 BT 但 KWS 没 fire）必须走 KWS 模型/数据优化，见 §14.12。

**后续可调：** timeout 1.2s 是经验值；误拒发生在 `WAIT_ASR_CONFIRM timeout` 时可拉到 1.5-2s；担心延迟可缩到 0.8s。但如果日志没有 `Wake word detected`，调 confirm timeout 没意义。

### §14.12 KWS 召回优化闭环（v3.20，2026-07-12）

**当前结论：** 优化方向是 KWS 召回，不是继续堆 Hybrid confirm。Hybrid 能让误触发静默回监听，但 KWS 没 fire 时，confirm 根本没有机会运行。

**参数 sweep 证据（2026-07-12 全量）：**

| score | threshold | recall | FAR | 结论 |
| - | - | -: | -: | - |
| 10.0 | 0.25 | 49.06% | 2.00% | 当前最佳，保留默认 |
| 10.0 | 0.20 | 49.06% | 2.00% | 降阈值无收益 |
| 8.0 | 0.25 | 49.06% | 9.00% | 召回不变，误报大增 |
| 8.0 | 0.20 | 49.06% | 9.50% | 不采用 |
| 8.0 | 0.30 | 49.06% | 9.00% | 不采用 |
| 12.0 | 0.20 | 13.21% | 1.50% | 召回崩 |
| 12.0 | 0.25 | 13.21% | 1.50% | 召回崩 |

所以本轮不把 `JARVIS_KWS_THRESHOLD` 从 0.25 改到 0.20；旧数据集已经证明它不提高召回。真正问题更可能是：训练正样本太少（53 段）、混淆/困难负样本不足、用户真实链路经过 NVIDIA Broadcast + 浏览器 WebRTC + 重采样，和训练数据存在域偏移。

**已实现观测：**

- `JarvisStateMachine._observe_kws_diagnostics()`：监听态保存有声 rolling PCM 窗口到 `<workspace>/data/kws/mic_captures/kws_live_*.wav`。
- `JarvisStateMachine._feed_kws_shadow_asr()`：KWS 未触发时，ASR shadow 只写日志，不唤醒。日志形如：

```text
KWS shadow ASR partial without KWS hit: 'bt' (peak=0.305 rms=0.305)
KWS MISS: shadow ASR saw wake pattern 'bt', but KWS did not fire
```

**诊断 env：**

| env | 默认 | 作用 |
| - | - | - |
| `JARVIS_KWS_SHADOW_ASR` | `true` | 监听态启用 ASR shadow，仅诊断，不唤醒 |
| `JARVIS_KWS_CAPTURE` | `true` | 保存 live KWS 输入窗口 |
| `JARVIS_KWS_CAPTURE_DIR` | `<workspace>/data/kws/mic_captures` | 诊断 wav 输出目录 |
| `JARVIS_KWS_CAPTURE_WINDOW_S` | `3.0` | rolling capture 长度 |
| `JARVIS_KWS_CAPTURE_INTERVAL_S` | `4.0` | 两次保存最小间隔 |
| `JARVIS_KWS_CAPTURE_PEAK` | `0.035` | 触发保存的峰值阈值 |
| `JARVIS_KWS_FRESH_PROBE` | `true` | KWS stream miss 后，用 rolling PCM 新建干净 KWS stream 再判一次 |
| `JARVIS_KWS_FRESH_PROBE_INTERVAL_S` | `0.5` | fresh-window probe 最小间隔 |
| `JARVIS_KWS_FRESH_PROBE_MIN_S` | `1.0` | rolling PCM 至少多长才 probe |
| `JARVIS_KWS_FRESH_DIRECT_WAKE` | `true` | fresh-window KWS 命中后直接 wake，用于当前召回测试 |

**下一步数据闭环：**

1. 用户点 Listen，等 `KWS 监听中`。
2. 连续说 10-20 次 `BT`，包含正常/稍快/稍慢/不同距离。
3. 查 `services/.logs/webui.err.log`：
   - 有 `Wake word detected`：KWS 命中；若随后失败，看 `WAIT_ASR_CONFIRM ASR partial`。
   - 无 `Wake word detected` 但有 `KWS MISS: shadow ASR saw wake pattern`：这是 KWS 漏召回，样本应并入 v5 正样本/困难样本。
   - shadow ASR 也听不成 `bt`：优先检查输入设备、NVIDIA Broadcast 处理、WebRTC 重采样和说法。
4. 把 `<workspace>/data/kws/mic_captures/kws_live_*.wav` 分拣到 `positive` / `negative` / `hard_negative`，再重训 v5。

**离线分析：**

```powershell
& D:\AI\envs\joyai-main\python.exe services\scripts\analyze_kws_captures.py D:\AI\data\kws\mic_captures
```

输出列：`file / kws_hit / asr_text / duration_s`。旧样本 `mic_1783844050536.wav` 的实测结果是 `kws_hit=1`，ASR 文本约为 `b t b e t рт t рт`，说明 live 链路里短词会被 ASR 拆散或识别成近音，后续训练和 confirm pattern 都要用真实样本校准。

**v3.21 实测根因：** 用户 17:28-17:29 连续喊 `BT` 未唤醒；日志没有实时 `Wake word detected`，但保存了 `kws_live_1783848515550_0002_peak516_rms046.wav`。离线分析该文件 `kws_hit=1 / asr_text=以`。结论：实时长 KWS stream 会受边界/前序音频影响 miss；同一模型从 rolling window 干净 stream 启动能命中。修复是 fresh-window KWS probe，而不是再降阈值。

**TDD：**

- `test_kws_diagnostics.py`：确认 KWS miss 时 shadow ASR 会记录 wake pattern 但不改变状态；确认诊断 wav 是 16k mono PCM16；确认 live stream miss 但 rolling-window KWS hit 时能直接 wake。
- `test_jarvis_config_env.py`：确认 KWS 诊断 env 可配置。
- `test_webui_static_contract.py`：确认 `WAIT_ASR_CONFIRM` 在页面可见、状态区可换行、GAIN 事件不再重复绑定。

### §14.13 BT-7274 `</delegation>` 触发 hermes 闭环 (v3.28, 2026-07-13)

- **动机**：v3.27 把 hermes-gateway(8642) + shim(8079) 接好了，但 `BackgroundModelService.handle_foreground_response` 只在 `VideoProcessorTrack` 路径上跑（webcam/RTSP），Jarvis `sm._send_to_llm` 走的是直连 llama-server(7060) 路径，识别出 `</delegation>` 也不触发后台 worker。
- **改动**：
  - `prompts/bt-7274.txt` 加 **Delegation Protocol (P-D)** 章节，规则（外部查才触发、tag 必须结尾、foreground 短句、问题要 self-contained）+ 3 个中英示例。
  - `services/webui/.../jarvis_session.py::_make_llm_callback` 在广播 `notify_session_llm_reply` 之后顺手调 `BackgroundModelService.handle_foreground_response(text, metrics={"user_prompt": text})`，延迟从 `sessions[session_id]["background_service"]` 拿到。
- **验证**：4-case LLM 行为烟测
  - `Hi, how are you?` → 不触发，前台：`Confirmed. I am operational and ready for your command.`
  - `查 NVIDIA RTX 5060 Ti 16GB 跑 Qwen2.5-VL-7B 显存占用基准` → 触发，前台 `Scanning external sources.` + delegated 同义问题。
  - `What's the weather like today?` → 触发，问题被改写为 `查今天北京天气情况`（中英转换 + 补全）。
  - `Define machine learning in one sentence.` → 不触发，前台直接给出定义。
- **端到端 e2e**：`POST /api/llm/message {text:"查 Cyberpunk 2077 螳螂帮 boss 攻略"}`
  - WS 收到 `llm_reply`：`Scanning external sources.</delegation> 查 Cyberpunk 2077 螳螂帮 boss 攻略与掉落`
  - WS 收到 `background_task_started` (task_id bg-smoke-bt7274-…-1-b9fdf73b)
  - shim 日志：`POST /v1/solve HTTP/1.1 200 OK`
  - hermes-gateway 日志：调用 `web_extract` 工具尝试 cyberpunk2077 wiki（被 url_safety 拦了部分，最终用 LLM 已有知识）
  - WS 收到 `background_result_ready` 含 MiniMax M2 整理后的攻略（含 Royce boss、打法、掉落、支线），耗时 11s
- **不破坏 hermes env**：`run-windows.env` / `background-agent.env` 里的 `HERMES_API_KEY` 没动；shim 与 gateway 用同一 key 由 env 注入；`Start-Hermes` / `Start-BackgroundAgent` 路径不变。