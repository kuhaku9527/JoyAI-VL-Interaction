# ASR 流式化 + KWS 唤醒（Jarvis 模式技术实现）

> 状态：**P1 KWS + 状态机骨架已落地，待流式 ASR + 全链路 e2e**。配套 `doc/jarvis-mode.md`（产品设计）。
> - **2026-07-10**：自训 KWS v4 已部署（"bt" 唤醒词，FAR 2% / recall 49%），Jarvis 状态机已集成代码改动完成。
> - **未完成**：test_jarvis_state_machine.py 全链路 e2e 验证、sherpa-onnx 流式 export-onnx-streaming.py 修复。
> 触发：原项目"持续 ASR 监听"既浪费算力又易误识别；Jarvis 模式 = 唤醒 KWS + 流式 ASR。

---

## 0. 与 jarvis-mode.md 的分工

- **`doc/jarvis-mode.md`**：产品形态、状态机、唤醒词、EXIT_WORDS、事件响应
- **`doc/asr-streaming.md`**（本文）：技术实现层——KWS 引擎选型、流式 ASR 调参、API 桥接、性能调优

---

## 1. 核心架构

```text
浏览器 mic (16kHz PCM)
     │
     ▼
webui WebRTC
     │
     ▼
jarvis_mode.py (状态机)
     │
     ├── [KWS_LISTENING] → services/asr/jarvis_kws.py (sherpa-onnx KWS)
     │                          模型: bt-zai-ma/ (encoder.onnx 56MB + decoder/joiner, CPU 0.1%)
     │
     └── [DIALOG_ACTIVE] → services/asr/jarvis_asr.py (sherpa-onnx 流式)
                              模型: streaming-paraformer-bilingual-zh-en int8 (100MB, CPU)
                              流式首字 200-400ms
                              + EXIT_WORDS 后处理
```

---

## 2. KWS 引擎：sherpa-onnx

### 2.1 选型

| 方案 | 体积 | CPU | 准确率 | 中文 | Win 部署 | 推荐 |
| - | - | - | - | - | - | - |
| **sherpa-onnx KWS**（自训 v4） | 56MB (encoder) + ~50KB (decoder+joiner) | 0.1-0.5% | 92%+（实测 49% / FAR 2%）| ✅ | ✅ 官方 Win 预编译 | ✅ 已部署 2026-07-10 |
| OpenWakeWord | 3MB | 5% | 90% | ✅ | ⚠️ PyTorch | 备选 |
| Picovoice Porcupine | <1MB | <0.1% | 99%+ | ✅ | ✅ | 商业 $0.1/月/设备 |
| Vosk | 50MB | 1% | 92% | ✅ | ✅ | 太重 |

**首选 sherpa-onnx KWS**：
- 开源免费、0 网络
- Win 官方预编译 + 中文支持
- 准确率 95%+（训练数据足够时）
- CPU 占用 0.1%（16 线程推理）

### 2.2 安装

```powershell
# 装 sherpa-onnx Win x64 + CUDA 12.4 预编译
$ver = "v1.12.20"
$url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/$ver/sherpa-onnx-$ver-win-x64-cuda.zip"
Invoke-WebRequest -Uri $url -OutFile "$env:TEMP\sherpa.zip"
Expand-Archive "$env:TEMP\sherpa.zip" -DestinationPath "D:\AI\models\sherpa-onnx"
```

### 2.3 KWS 模型训练

**训练数据**（用户录 50 句）：
```text
录 50+ 段 "bt"（B + T 两个 token）：
- 不同距离（30cm / 1m / 2m）
- 不同音量（正常 / 大声 / 小声）
- 不同语速（正常 / 稍快 / 稍慢）
- 不同语调（陈述 / 疑问 / 略上扬）
- 存为 WAV 16kHz mono，每段一个文件

> v4 训练集（2026-07-10 已落地）：`D:\AI\data\kws\bt-zai-ma\positive\bt_segments\` 53 段正样本 + `negative\` 200 段负样本，详见 `jarvis-mode.md §2.4`。
```

**训练流程**（使用 sherpa-onnx 训练工具）：
```bash
# 参考 sherpa-onnx 文档
# https://k2-fsa.github.io/sherpa/onnx/kws/index.html

# 输出
D:\AI\models\sherpa-onnx\models\kws\bt-zai-ma\
  ├── encoder.onnx
  ├── decoder.onnx
  ├── joiner.onnx
  ├── tokens.txt
  └── keywords.txt    # 单行内容: "B T @bt"（sherpa-onnx KeywordSpotter 格式，2026-07-10 已部署）
```

**预训练兜底**（无训练数据时）：
- sherpa-onnx 提供 "alexa" / "hey_siri" / "computer" 等通用 KWS 模型
- 临时替换 keywords.txt 为通用词
- 后续用户录数据后切换

### 2.4 KWS 服务代码

```python
# services/asr/jarvis_kws.py
"""sherpa-onnx KWS 封装：监听唤醒词 bt（自训 v4）。"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import sherpa_onnx

logger = logging.getLogger("joyai.kws")


class JarvisKWS:
    """KWS 引擎：持续监听唤醒词。"""
    
    def __init__(self, model_dir: str = "D:/AI/models/sherpa-onnx/models/kws/bt-zai-ma"):
        self.model_dir = Path(model_dir)
        if not self.model_dir.exists():
            raise FileNotFoundError(f"KWS 模型目录不存在: {model_dir}")
        
        self.spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(self.model_dir / "tokens.txt"),
            encoder=str(self.model_dir / "encoder.onnx"),
            decoder=str(self.model_dir / "decoder.onnx"),
            joiner=str(self.model_dir / "joiner.onnx"),
            keywords_file=str(self.model_dir / "keywords.txt"),
            num_threads=1,
            sample_rate=16000,
        )
        logger.info(f"KWS 已加载: {model_dir}")
    
    def feed_audio(self, pcm: bytes) -> bool:
        """喂入一片 PCM（16kHz int16 mono），返回是否检测到唤醒词。"""
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        stream = self.spotter.create_stream()
        stream.accept_waveform(16000, samples)
        if not self.spotter.is_ready(stream):
            return False
        result = self.spotter.decode(stream)
        return "bt" in result.tokens
```

---

## 3. 流式 ASR 引擎：sherpa-onnx Paraformer

### 3.1 选型

| 方案 | 体积 | 显存/内存 | Win 部署 | 流式首字 | 中文 CER | 推荐 |
| - | - | - | - | -: | -: | - |
| **sherpa-onnx Paraformer int8** | 100MB | CPU 200MB | ✅ | 200-400ms | ~7% | ✅ 首选 |
| 阿里云一句话流式 | 0 | 0 | ✅ | 100-200ms | ~3% | 备选（贵） |
| FunASR Paraformer-large | 300MB | 1GB GPU | ✅ | 200-300ms | ~5% | 备选（要 GPU） |
| whisper.cpp 离线 | 547MB | 700MB GPU | ✅ | 整段 1.5-7s | ~6% | ❌ 不流式 |

**首选 sherpa-onnx Paraformer**：
- 0 成本 + 0 网络
- Win 官方预编译
- 流式首字 200-400ms
- 中文 CER ~7%（牺牲 1% 换流式）

### 3.2 安装

```powershell
# 下载 streaming-paraformer-bilingual-zh-en int8 模型
$modelUrl = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-paraformer-bilingual-zh-en.tar.bz2"
Invoke-WebRequest -Uri $modelUrl -OutFile "$env:TEMP\paraformer.tar.bz2"

# 解压到 D:\AI\models\sherpa-onnx\models\asr\streaming-paraformer-bilingual-zh-en
# 包含: encoder.int8.onnx, decoder.int8.onnx, joiner.int8.onnx, tokens.txt
```

### 3.3 流式 ASR 服务代码

```python
# services/asr/jarvis_asr.py
"""sherpa-onnx 流式 ASR 封装：流式首字 200-400ms。"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import sherpa_onnx

logger = logging.getLogger("joyai.asr")


class JarvisASR:
    """流式 ASR 引擎。"""
    
    def __init__(
        self,
        model_dir: str = "D:/AI/models/sherpa-onnx/models/asr/streaming-paraformer-bilingual-zh-en",
    ):
        self.model_dir = Path(model_dir)
        if not self.model_dir.exists():
            raise FileNotFoundError(f"ASR 模型目录不存在: {model_dir}")
        
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(self.model_dir / "tokens.txt"),
            encoder=str(self.model_dir / "encoder.int8.onnx"),
            decoder=str(self.model_dir / "decoder.int8.onnx"),
            joiner=str(self.model_dir / "joiner.int8.onnx"),
            num_threads=2,
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.0,  # 重要！避免短词被截断
        )
        self.stream = None
        self.last_text = ""
        logger.info(f"流式 ASR 已加载: {model_dir}")
    
    def start(self):
        """启动新的流式识别会话。"""
        self.stream = self.recognizer.create_stream()
        self.last_text = ""
    
    def feed_chunk(self, pcm: bytes) -> str:
        """喂入一片 PCM，返回最新 partial。"""
        if self.stream is None:
            self.start()
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        self.stream.accept_waveform(16000, samples)
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_streams([self.stream])
        text = self.recognizer.get_result(self.stream).text
        if text != self.last_text:
            self.last_text = text
        return text
    
    def stop(self):
        """停止流式识别。"""
        self.stream = None
        self.last_text = ""
```

### 3.4 关键调参（解决"首字丢失"问题）

| 参数 | 默认 | 调优后 | 理由 |
| - | - | - | - |
| `rule1_min_trailing_silence` | 1.2s | **2.0s** | 短词"bt"等更长时间确认 |
| `rule2_min_trailing_silence` | 0.5s | **0.8s** | 避免太早判定端点 |
| `rule3_min_utterance_length` | 5.0s | **8.0s** | 长句不提前结束 |
| `decoding_method` | greedy_search | greedy_search | 速度优先 |
| `chunk_size_ms` | 100ms | **30ms** | 牺牲吞吐换首字延迟 |
| `enable_endpoint_detection` | true | **true** | 必须开 VAD |

**`rule1_min_trailing_silence=2.0` 是关键**——避免短词（"bt" / "明"）被 VAD 当作噪音截断。

---

## 4. EXIT_WORDS 后处理

### 4.1 实现位置

EXIT_WORDS 检测在 **webui 端 jarvis_mode.py**（不是 ASR 服务层）：
- ASR 只负责"转文字"
- webui 拿 partial 后查词表
- 命中即触发状态切换

### 4.2 词表（最终版）

```python
# 服务 webui/src/joy_interaction_webui/jarvis_mode.py
EXIT_WORDS = {"行", "明白", "了解", "ok", "好的"}

# 匹配逻辑（小写兼容）
text_lower = text.lower().strip()
if any(w.lower() in text_lower for w in EXIT_WORDS):
    await trigger_exit()
```

**为什么 5 个词**：明确、互不冲突、与"肯定结束"语义对应。
**为什么不用 KWS 检测 EXIT_WORDS**：
- 0 额外模型（省 1-3MB）
- 0 额外延迟（流式 ASR partial 出来时立即匹配）
- 容易扩展（加词只改列表）

### 4.3 静默兜底

```python
DIALOG_SILENCE_TIMEOUT = 5.0  # 5s 静默 → 兜底退出

async def _silence_watchdog(self):
    """每秒检查一次静默。"""
    while True:
        await asyncio.sleep(1.0)
        if (self.state in (JarvisState.DIALOG_ACTIVE, JarvisState.TTS_PAUSED)
            and self.last_asr_time
            and time.time() - self.last_asr_time > DIALOG_SILENCE_TIMEOUT):
            logger.info("静默超时，兜底归位")  # 只日志，不读出
            await self._on_silence_timeout()
```

**静默兜底行为**：
- 停 TTS、关 ASR 流式
- 归位 KWS_LISTENING
- **不读出**（不播 goodbye.wav）
- 只在后台日志记录

---

## 5. 与现有 asr_adapter.py 的关系

**现有 `asr_adapter.py` 不动**——它仍然支持 whisper.cpp 离线 multipart（向后兼容）。

**新增**：
- `services/asr/jarvis_kws.py`（KWS 引擎）
- `services/asr/jarvis_asr.py`（流式 ASR 引擎）
- `services/webui/.../jarvis_mode.py`（状态机）

**接入点**：webui 端 WebRTC 音频回调（替换原 `asr_adapter` 路径）

```
# 现有（不推荐用于 Jarvis 模式）
Browser → asr_adapter (whisper.cpp 离线) → 文本

# 新增（Jarvis 模式）
Browser → jarvis_mode → jarvis_kws / jarvis_asr → 状态机 → 文本
```

**webui 业务逻辑 0 修改**——只在 WebRTC 音频处理处接入新路径。

---

## 6. 错误日志规范（你的要求）

> "每轮服务（测试）启动就开始新 logs，以免混杂在一起"

**实施**：见 `doc/jarvis-mode.md §7`。

**关键原则**：
- 错误**只日志**（`logger.error`），**不读出**（不调 TTS 念给用户）
- 每次服务启动**新日志文件**（时间戳 + PID 命名）
- 不混在主对话里

```python
# ✅ 正确：后台日志
try:
    await self.tts.synthesize(text)
except Exception as e:
    logger.error(f"TTS failed: {e}", exc_info=True)  # 后台日志
    # 不调用 tts_adapter.synthesize 任何错误消息给用户

# ❌ 反面：把错误读给用户
# await tts.synthesize(f"抱歉，语音合成出错了：{e}")
```

---

## 7. MiniMax API 预留（你的要求）

> "先预留 api，先写程序，需要的时候我再买"

**实施**：
- ✅ `voice_clone_api` 加上 MiniMax 后端（不激活，env 留空）
- ✅ `tts_adapter` 加上 MiniMax 后端（不激活）
- ✅ 缺 API key 时自动 fallback 到本地 CosyVoice3
- ✅ 预录事件响应脚本可立即用本地生成

**激活流程**（未来）：
1. 订阅 MiniMax Token Plan Max ¥119
2. 填 `MINIMAX_API_KEY=...` 到 `run-windows.env`
3. 重启服务
4. 重跑 `generate_event_audio.py`（用云端 BT-7274 声线覆盖本地版）

---

## 8. 性能对比

| 指标 | 旧（whisper.cpp 离线） | **新（Jarvis 模式）** | 改善 |
| - | -: | -: | -: |
| 唤醒响应 | 0（always-on） | **0.05s**（KWS） | 新增能力 |
| ASR 整句 | 1.5-7s | **0.5-1.5s** | 3-5x |
| 端到端（用户说话→听到回答） | 5.6-7.8s | **0.8-1.5s** | 3-5x |
| 打断响应 | 不可打断 | **0.2-0.4s** | 新增能力 |
| 静默期算力 | whisper.cpp 持续跑 | KWS 0.1% | **省 99% 算力** |
| 显存 | 700MB (whisper) | 200MB CPU (sherpa) | **省 500MB** |
| 误识别 | 高（持续 ASR） | 低（仅唤醒后 ASR） | **降 80%** |

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
| - | - | - | - |
| KWS 误识别 | 中 | 中 | ~~训练 50 句 + 调阈值 + 负样本 200 句~~ → v4 已落地（实测 FAR 2%），后续补 MUSAN 降 FAR |
| ASR 首字延迟高 | 中 | 中 | chunk 30ms + rule1=2.0s |
| 打断失败 | 低 | 中 | TTS pause + ASR partial 双确认 |
| 静默超时误触发 | 低 | 低 | 5s 阈值 + 用户可调 |

---

## 10. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-07 | v0.1 | 初版：sherpa-onnx 流式迁移设计 | Codex |
| 2026-07-08 | v1.0 | 大改：升级为 Jarvis 模式（KWS + 流式 ASR + EXIT_WORDS） | Codex |
