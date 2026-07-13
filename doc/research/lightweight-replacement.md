# JoyAI-VL-Interaction 轻量化替换方案（Windows + RTX 5060 Ti 16GB + 32GB RAM）

> 目标：用 **不依赖 vLLM / vLLM-Omni** 的方案替换原项目里的「摘要模型 / ASR / TTS」三组件，全部能在 Windows 原生跑、并通过 HTTP / OpenAI 兼容 API 暴露给上游 webinfer 适配器。

## 0. 硬件 / 驱动 前置（必读）

- **RTX 5060 Ti 16GB = sm_120 / Blackwell 消费卡**。PyTorch 必须 ≥ 2.7 且绑 **CUDA 12.8+**，否则 kernel 找不到（sm_50 … sm_90 全部 fail）。
  - 官方明确要求："PyTorch 2.7.0 already added Blackwell support on our PyTorch wheels built with CUDA 12.8."（[discuss.pytorch.org – When will sm120 support be available](https://discuss.pytorch.org/t/when-will-sm120-support-be-available/223621)）
  - pip install -U torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
- **llama.cpp**：Windows 官方发 Win x64 **CUDA 12.4 / CUDA 13.x / Vulkan / CPU** 预编译包；Vulkan 对 RTX 50 系可用。
  - [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases)（任选 …bin-win-vulkan-x64.zip 或 …bin-win-cuda-12.4-x64.zip）
  - 第三方针对 sm_120 + TurboQuant 的 Windows 预编译：[Andgihat/llama-cpp-mtp-turboquant-sm120-blackwell-windows](https://github.com/Andgihat/llama-cpp-mtp-turboquant-sm120-blackwell-windows)
- **whisper.cpp**：Win x64 直接有 **cublas 12.4 预编译**（whisper-cublas-12.4.0-bin-x64.zip），自带 /inference HTTP。
  - [whisper.cpp v1.7.6 release](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.7.6)
- **FunASR / CosyVoice / F5-TTS / Spark-TTS**：纯 PyTorch 推理，**必须用 PyTorch cu128** wheel；其中 CosyVoice3 在 sm_120 上有 [已知问题 #1815](https://github.com/FunAudioLLM/CosyVoice/issues/1815)，需用 PyTorch 2.7.0+/nightly + CUDA 12.8+ 解决（[Spark-TTS issue 5 评论区验证方案](https://github.com/SparkAudio/Spark-TTS/issues/5)）。

---

## 1. 摘要模型（Qwen3-VL-4B-Instruct → 轻量）

### 候选对比

| 模型 / 仓库 | 量化 | 文本 | mmproj | 多模态 | 中文摘要 | Win llama-server | 评分 |
|---|---|---|---|---|---|---|---|
| ggml-org/Qwen2.5-VL-3B-Instruct-GGUF | Q4_K_M | 1.80 GB | 1.25 GB (F16) | ✅ | ⭐⭐⭐⭐ | ✅ -hf 直接拉 | **首选** |
| bartowski/Qwen2.5-3B-Instruct-GGUF（纯文本） | Q4_K_M | 1.93 GB | — | ❌ | ⭐⭐⭐⭐⭐ | ✅ | 备选（更省 mmproj 显存） |
| bartowski/Qwen_Qwen3-VL-4B-Instruct-GGUF | Q4_K_M | 2.38 GB | 0.94 GB (BF16) | ✅ | ⭐⭐⭐⭐⭐ | ✅（llama-server 已支持） | 备选（最新） |
| bartowski/Qwen2.5-1.5B-Instruct-GGUF（纯文本） | Q4_K_M | ~1.10 GB | — | ❌ | ⭐⭐⭐ | ✅ | 极致轻 |

> **结论**：摘要场景是**纯文本**（chunk 摘要 + 长期记忆压缩），多模态部分是浪费的。
> 1. **首选**用 ggml-org/Qwen2.5-VL-3B-Instruct-GGUF（社区一致推荐的「省而强」平衡点，且 ggml-org 自家预量化，llama.cpp -hf 一行拉起）。
> 2. 如果**真的不需要多模态**（你确定就是纯文本摘要），用 bartowski/Qwen2.5-3B-Instruct-GGUF 省掉 mmproj 的 1.25 GB。
> 3. 如果想保留「多模态以便后续接 OCR 截图摘要」，用 bartowski/Qwen_Qwen3-VL-4B-Instruct-GGUF Q4_K_M。

### 启动命令（PowerShell）

```powershell
# ---------- 路径与模型 ----------
$env:LLAMA_REPO = "D:\AI\models\llama.cpp"        # llama.cpp 解压目录
`$env:MODEL_DIR  = "D:\AI\models\summary"          # GGUF 放这里

# ---------- 下载（任选一行；首选走 -hf 自动拉） ----------
# 方式 A：直接 huggingface-cli 拉 bartowski 的 Qwen2.5-VL-3B
huggingface-cli download bbartowski/Qwen2.5-VL-3B-Instruct-GGUF 
  --include "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf","Qwen2.5-VL-3B-Instruct-mmproj-f16.gguf" 
  --local-dir `$env:MODEL_DIR

# 方式 B：纯文本更省
huggingface-cli download bbartowski/Qwen2.5-3B-Instruct-GGUF 
  --include "Qwen2.5-3B-Instruct-Q4_K_M.gguf" 
  --local-dir `$env:MODEL_DIR

# ---------- 启动 llama-server（端口 8065，与原项目保持一致） ----------
cd `$env:LLAMA_REPO\build\bin\Release
.\llama-server.exe 
  -m "`$env:MODEL_DIR\Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf" 
  --mmproj "`$env:MODEL_DIR\Qwen2.5-VL-3B-Instruct-mmproj-f16.gguf" 
  --port 8065 
  --host 127.0.0.1 
  -c 8192                 # 摘要一般用 4k-8k context 就够
  -ngl 999                 # 全部层都丢 GPU
  --jinja                   # 用 unsloth 修复过的 Qwen3 chat template
```

> 想更省心：直接用 -hf 让 llama.cpp 帮你下载并挑默认 Q4_K_M：
> ```powershell
> .\llama-server.exe -hf ggml-org/Qwen2.5-VL-3B-Instruct-GGUF --port 8065 -c 8192
> ```
> （官方 multimodal 文档明列该 GGUF 为预量化推荐之一，见下 Reference）

### OpenAI 兼容 API 形态

- POST http://127.0.0.1:8065/v1/chat/completions —— **直接就是 webinfer 适配器要调的标准 OpenAI 接口**。
- 例（无图，纯文本摘要）：

```powershell
$body = @{
  model    = "Qwen2.5-VL-3B-Instruct"
  messages = @(@{ role = "user"; content = "请用 100 字总结以下 chunk：<文本>" })
  max_tokens = 256
} | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8065/v1/chat/completions 
  -ContentType "application/json" -Body `$body
```

- 多模态调用（带图）：在 messages[].content 里加 {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}，
  llama-server 通过 libmtmd 走 mmproj → 与 webinfer 现有 OpenAI 适配器**完全兼容**（[multimodal.md](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)）。

---

## 2. ASR（Qwen3-ASR-1.7B → 轻量）

### 候选对比

| 方案 | 模型 / 量化 | 大小 | 框架 | Win 友好 | 中文 | 流式 | 内置 HTTP | 评分 |
|---|---|---|---|---|---|---|---|---|
| **whisper.cpp** | ggml-large-v3-turbo-q5_0 | **547 MiB** | C++ / cublas | ✅ 官方 Win 预编译 | ⭐⭐⭐ | ❌（离线） | ✅ --inference-path /v1/audio/transcriptions | **首选** |
| **FunASR Paraformer-large + OpenAI-API server** | damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-onnx (int8) | ~300 MB | Python / onnxruntime | ✅（Win 官方 unasr-wss-server.exe） | ⭐⭐⭐⭐⭐ | ✅（双 pass / 流式） | ✅ /v1/audio/transcriptions | 备选 1（中文最准） |
| **sherpa-onnx** | sherpa-onnx-streaming-paraformer-bilingual-zh-en (int8) | ~100 MB | C++ / ONNX | ✅ 官方 Win 预编译 sherpa-onnx.exe | ⭐⭐⭐⭐ | ✅ | ✅ sherpa-onnx-offline-websocket-server | 备选 2（流式 + CPU 即可） |
| **llama.cpp 多模态** | mradermacher/Qwen3-ASR-1.7B-GGUF Q4_K_M | 1.4 GB + mmproj 0.5 GB | C++ / Vulkan | ✅ | ⭐⭐⭐⭐⭐（11 语种 + 方言） | ❌ | ✅ /v1/chat/completions | 备选 3（保留 Qwen3 ASR 能力） |
| **MMS-1B-fl102** | mms-1b-fl102 | 1.0 GB | Python (fairseq2) | ⚠️ 需自配 | ⭐⭐（中文一般） | ❌ | 需自己包一层 | 不推荐（中文弱 + 部署麻烦） |

> **首选 whisper.cpp**：原项目 8993 端口保持不变，547 MiB 模型在 5060 Ti 上纯 GPU 跑，
> 中文 large-v3 准确率已经够用，**无需 PyTorch / onnxruntime**，纯 C++。  
> **强烈备选 FunASR**：如果对中文识别质量最敏感，Paraformer-large 仍是中文 SOTA，且官方有
> **xamples/openai_api/server.py 直接吐 OpenAI 兼容 /v1/audio/transcriptions**。


> ### ⚠️ 限制提醒：whisper.cpp 是**离线**识别
>
> 上文选 whisper.cpp 是因为它在 Win 上有 cublas 预编译 + OpenAI 兼容 API，**零 PyTorch 依赖**。
> 但它的 `whisper-server.exe` 端点 `/v1/audio/transcriptions` 是**整段音频一次性提交 → 整段返回**的离线接口。
>
> 实际项目里 `services/webui/src/joy_interaction_webui/asr.py:24-38` 的 `ASR_RECOGNIZE_PARAMS` 配置了：
>
> - `do_partial_result: True`（要部分结果）
> - `do_server_vad: True`（要服务端 VAD）
> - `continuous_decoding: True`（要连续解码）
> - `forceend_lowerlimit: 6000, forceend_upperlimit: 8000`（VAD 端点阈值）
>
> 这是**完整流式 pipeline** 的预期配置，但 `asr_adapter.py:135` 的 `transcribe_with_vllm` 是**离线 multipart**。
> 也就是说 webui 端是流式 plumbing，asr_adapter 是离线转换器。**端到端延迟 1.5-7s**（用户说完 + 0.6s 静音 + 整段转写 + 回传）。
>
> **gaming 模式**（P4 阶段）会暴露这个痛点：喊"左边有人"等 3-5s 才听到角色回应，体验崩。
>
> **P1 修复方案**：迁移到 **sherpa-onnx streaming-paraformer-bilingual-zh-en**（int8，100MB，CPU 跑）。
> 详见 `doc/asr-streaming.md`（流式协议、迁移步骤、性能对比）。**无需修改 webui**——只改 `asr_adapter.py` 的 `transcriber` 实现。
>
> **过渡措施**（不重写）：gaming 模式默认 `do_partial_result=False`（即用现在的离线 whisper.cpp），
> 接受 2-4s 延迟；等 P1 迁完再恢复流式。
### 启动命令（PowerShell）

#### 2A. 首选 whisper.cpp（OpenAI 兼容路径）

```powershell
# ---------- 下载 Windows cublas 预编译 ----------
Invoke-WebRequest -Uri "https://github.com/ggml-org/whisper.cpp/releases/download/v1.7.6/whisper-cublas-12.4.0-bin-x64.zip" 
  -OutFile "`$env:TEMP\whisper.zip"
Expand-Archive "`$env:TEMP\whisper.zip" -DestinationPath "D:\AI\models\whisper.cpp"

# ---------- 下载 large-v3-turbo q5_0（中文/英文都好，547 MiB） ----------
Invoke-WebRequest -Uri "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin" 
  -OutFile "D:\AI\models\whisper.cpp\ggml-large-v3-turbo-q5_0.bin"

# ---------- 启动 server（OpenAI 路径 /v1/audio/transcriptions） ----------
cd D:\AI\models\whisper.cpp
.\whisper-server.exe 
  -m ggml-large-v3-turbo-q5_0.bin 
  --port 8993 
  --host 127.0.0.1 
  --inference-path "/v1/audio/transcriptions" 
  --request-path "/v1" 
  --convert 
  -l auto
```

> 验证：
> ```powershell
> curl http://127.0.0.1:8993/v1/models
> curl -F "file=@test.wav" -F "model=whisper-1" http://127.0.0.1:8993/v1/audio/transcriptions
> ```

#### 2B. 备选 FunASR（中文最准，OpenAI 兼容）

```powershell
conda create -n funasr python=3.10 -y
conda activate funasr
pip install -U funasr fastapi uvicorn python-multipart
pip install -U torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# 拉官方 openai_api server 代码
git clone https://github.com/modelscope/FunASR.git D:\AI\models\FunASR
cd D:\AI\models\FunASR\examples\openai_api

# 启动（port 8993 与原项目一致）
python server.py --model paraformer --device cuda --port 8993
```

> 客户端调用同 OpenAI SDK：
> ```
> from openai import OpenAI
> c = OpenAI(base_url="http://127.0.0.1:8993/v1", api_key="not-needed")
> print(c.audio.transcriptions.create(model="paraformer", file=open("a.wav","rb")).text)
> ```

#### 2C. 备选 sherpa-onnx（纯 C++ / 零依赖 / 流式）

```powershell
# Windows 官方预编译 (含 cublas)
Invoke-WebRequest -Uri "https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.12.20/sherpa-onnx-v1.12.20-win-x64-cuda.zip" 
  -OutFile "`$env:TEMP\sherpa.zip"
Expand-Archive "`$env:TEMP\sherpa.zip" -DestinationPath "D:\AI\models\sherpa-onnx"

# 启动 WebSocket 离线 server (port 6006)
cd D:\AI\models\sherpa-onnx
.\bin\sherpa-onnx-offline-websocket-server.exe 
  --port=6006 --num-work-threads=3 
  --tokens=.\sherpa-onnx-streaming-paraformer-bilingual-zh-en\tokens.txt 
  --paraformer=.\sherpa-onnx-streaming-paraformer-bilingual-zh-en\encoder.int8.onnx
# （paraformer 走 --paraformer 一个文件即可，详见 k2-fsa 文档）
```

#### 2D. 备选 llama.cpp 跑原 Qwen3-ASR（要保留 11 语种 / 唱歌识别）

```powershell
huggingface-cli download ggml-org/Qwen3-ASR-1.7B-GGUF 
  --include "Qwen3-ASR-1.7B-Q4_K_M.gguf","mmproj-Qwen3-ASR-1.7B-F16.gguf" 
  --local-dir D:\AI\models\qwen3-asr

cd D:\AI\models\llama.cpp\build\bin\Release
.\llama-server.exe 
  -m D:\AI\models\qwen3-asr\Qwen3-ASR-1.7B-Q4_K_M.gguf 
  --mmproj D:\AI\models\qwen3-asr\mmproj-Qwen3-ASR-1.7B-F16.gguf 
  -c 10240 --port 8993 --host 127.0.0.1 -ngl 999

# 客户端：发 base64 音频到 /v1/chat/completions，content type="audio_url"
# 完全复用原项目 vLLM OpenAI 适配器
```

### OpenAI 兼容 API 形态

- **whisper.cpp / FunASR**：POST /v1/audio/transcriptions multipart (ile, model, 
esponse_format) —— **webinfer 直接复用 OpenAI SDK**。
- **llama.cpp (Qwen3-ASR)**：POST /v1/chat/completions，content 用 {"type":"audio_url", "audio_url":{"url":"data:`audio/wav`;base64,..."}}，
  vLLM 官方 Qwen3-ASR 文档里**就是用这个形态**调用，webinfer 适配器不用改。

---

## 3. TTS + 声音克隆（Qwen3-TTS-12Hz-1.7B-CustomVoice → 轻量）

> **关键事实**：Qwen3-TTS 12Hz CustomVoice 是 flow-matching + multi-codebook 结构，**目前没有官方 GGUF / ONNX 端口**；
> 硬要保留只能继续 vLLM-Omni（与你「不友好」的约束冲突）。所以必须换模型。

### 候选对比

| 模型 | 大小 | 框架 | Win 5060Ti | 中文 | 声音克隆 | 流式 | 内置 HTTP | 评分 |
|---|---|---|---|---|---|---|---|---|
| **Fun-CosyVoice3-0.5B-2512**（阿里 2025-12） | 0.5B (~1.0 GB fp16) | PyTorch | ✅（PyTorch cu128，2GB 显存） | ⭐⭐⭐⭐⭐ | ✅ 0 样本 / 3 秒克隆 | ✅ | ✅ FastAPI 
`runtime/python/fastapi/server.py` | **首选** |
| **CosyVoice2-0.5B** | 0.5B (~1.0 GB fp16) | PyTorch | ✅ | ⭐⭐⭐⭐⭐ | ✅ | ✅ | ✅ 同上 | 备选 1（更稳） |
| **F5-TTS v1 Base** + FastAPI wrapper | 0.3B (~1.2 GB) | PyTorch / Triton | ✅ | ⭐⭐⭐⭐ | ✅ 0 样本（5-15s ref） | ✅ 原生流式 | ✅ Nomannazir/f5-tts-fastapi | 备选 2（最快） |
| **Spark-TTS-0.5B** | 0.5B (~1.0 GB) | PyTorch | ✅（社区有 Windows 指南） | ⭐⭐⭐⭐ | ✅ 0 样本 | ❌ | 需自己包（webui.py 是 Gradio） | 备选 3（最轻） |
| **GPT-SoVITS V3** | ~1 GB（多模型） | PyTorch | ✅ 一键 Win 包 | ⭐⭐⭐⭐⭐ | ✅ 5 秒零样本 + 1 分钟 fine-tune | ✅ | ✅ pi.py FastAPI 9880 | 备选 4（克隆最强） |
| **IndexTTS2** | 1.5B | PyTorch | ✅ | ⭐⭐⭐⭐ | ✅ + 情感控制 | ✅ | 需自己包 | 备选 5（带情感） |
| **Qwen3-TTS** GGUF / ONNX | — | — | ❌ 无 | — | — | — | — | **不推荐（不存在）** |

> **首选 CosyVoice3 (Fun-CosyVoice3-0.5B-2512)**：阿里 2025-12 出的最新版，0.5B FP16 只占 ~1.0 GB 显存；
> 中文质量、方言、零样本声音克隆都是开源 SOTA；官方自带 FastAPI server 直接 python r`runtime/python/fastapi/server.py` --port 50000 --model_dir iic/Fun-CosyVoice3-0.5B-2512。  
> **Windows + 5060Ti 警告**：[Issue #1815](https://github.com/FunAudioLLM/CosyVoice/issues/1815) 报告 sm_120 需要 PyTorch 2.7.0+ + cu128，否则 kernel not found。

### 启动命令（PowerShell）

#### 3A. 首选 CosyVoice3（官方 FastAPI 路径）

```powershell
conda create -n cosyvoice python=3.10 -y
conda activate cosyvoice
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git D:\AI\models\CosyVoice
cd D:\AI\models\CosyVoice
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host=mirrors.aliyun.com
pip install -U torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# 下载最新版 CosyVoice3
python -c "from huggingface_hub import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='pretrained_models/Fun-CosyVoice3-0.5B')"

# 启动 FastAPI server (与官方一致 port 50000；为贴近原项目可改成 8991)
cd runtime\python\fastapi
python server.py --port 8991 --model_dir ../../pretrained_models/Fun-CosyVoice3-0.5B
```

> 想用 OpenAI 兼容的 /v1/audio/speech（drop-in）？用社区包装：
> ```powershell
> docker run -d --gpus '"device=0"' -p 8188:8188 ^
>   -v D:\AI\voices:/data/voices neosun/cosyvoice:v3.4.0
> # 端点：POST /v1/audio/speech  body = { "input":"...", "voice":"<voice_id>" }
> ```
> 源码：[neosun100/cosyvoice-docker](https://github.com/neosun100/cosyvoice-docker)

#### 3B. 备选 CosyVoice2（更稳，社区 Windows fork）

```powershell
git clone https://github.com/v3ucn/CosyVoice_For_Windows.git D:\AI\models\CosyVoice-Win
cd D:\AI\models\CosyVoice-Win
pip install -r requirements.txt
pip install -U torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

python api.py            # 默认监听 9880
# 验证：浏览器打开 http://localhost:9880/?text=测试&speaker=中文女
```

#### 3C. 备选 F5-TTS（流式 + 0 样本 + FastAPI 包装）

```powershell
git clone https://github.com/Nomannazir/f5-tts-fastapi.git D:\AI\models\f5-tts-fastapi
cd D:\AI\models\f5-tts-fastapi
python -m venv venv ; .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -U torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
python app.py            # 默认 Gradio 7860；FastAPI 在同一进程（看 main.py）
```
> 自带端点：POST /tts, POST /tts-stream, GET /v1/models。  
> 跑显存约 2-3 GB（[官方 issue #197](https://github.com/SWivid/F5-TTS/issues/197)）。

#### 3D. 备选 GPT-SoVITS（中文克隆最强 / Windows 一键包）

```powershell
# 1. 下一键整合包（自带 ffmpeg、CUDA wheels）
Invoke-WebRequest -Uri "https://huggingface.co/lj1995/GPT-SoVITS-windows-package/resolve/main/GPT-SoVITS-v3lora-20250228.7z?download=true" 
  -OutFile D:\AI\models\GPT-SoVITS-v3.7z
& 7z x D:\AI\models\GPT-SoVITS-v3.7z -oD:\AI\models\GPT-SoVITS
# 2. 双击 _go-webui.bat（或 cli 自启 API server）
cd D:\AI\models\GPT-SoVITS
.\go-api.bat           # 默认 :9880，参数：-dr 参考音频 -dt 参考音频文本 -dl 中文 -d cuda
```
> 端点：POST /  body = JSON {"text":"...","text_lang":"zh","ref_audio_path":"...","prompt_text":"...","prompt_lang":"zh"} 返回 wav。

### OpenAI 兼容 API 形态

| 方案 | 端点 | Body 形态 | 返回 |
|---|---|---|---|
| CosyVoice3 官方 | POST /inference_zero_shot | multipart: tts_text + prompt_text + prompt_wav(file) | StreamingResponse udio/wav (pcm int16 流) |
| CosyVoice2 Windows fork | GET / | ?text=...&speaker=中文女 | wav |
| neosun/cosyvoice-docker (社区) | POST /v1/audio/speech | {"input":"...","voice":"<voice_id>"} | **OpenAI 兼容 `audio/wav`** |
| sin-tag/CosyVoice2-API | POST /v1/audio/speech | OpenAI 兼容 + 流式 | wav |
| F5-TTS FastAPI | POST /tts, POST /tts-stream | {"text":"...","ref_audio":"...","ref_text":"..."} | wav 流 |
| GPT-SoVITS | POST / (Flask 9880) | JSON 字段 | wav |

> **建议**：要 OpenAI /v1/audio/speech 兼容 → 直接跑 
eosun/cosyvoice-docker 镜像；
> 要更原生控制 → 用官方 
`runtime/python/fastapi/server.py` + 自己写一个 30 行的 webinfer 适配器。

---

## 4. 三组件联合启动脚本（PowerShell，端口与原项目一致）

```powershell
# ============== 0. 公共环境 ==============
`$env:MODEL_ROOT = "D:\AI\models"
`$env:HF_ENDPOINT = "https://hf-mirror.com"   # 国内镜像，按需

# ============== 1. 摘要 :8065 ==============
Start-Process -FilePath "D:\AI\models\llama.cpp\build\bin\Release\llama-server.exe" 
  -ArgumentList @(
    "-hf","ggml-org/Qwen2.5-VL-3B-Instruct-GGUF",
    "--port","8065","--host","127.0.0.1",
    "-c","8192","-ngl","999","--jinja"
  ) -WindowStyle Hidden

# ============== 2. ASR   :8993 ==============
Start-Process -FilePath "D:\AI\models\whisper.cpp\whisper-server.exe" 
  -ArgumentList @(
    "-m","ggml-large-v3-turbo-q5_0.bin",
    "--port","8993","--host","127.0.0.1",
    "--inference-path","/v1/audio/transcriptions",
    "--request-path","/v1","--convert","-l","auto"
  ) -WorkingDirectory "D:\AI\models\whisper.cpp" -WindowStyle Hidden

# ============== 3. TTS   :8991 ==============
Start-Process -FilePath "python" 
  -ArgumentList @(
    "r`runtime/python/fastapi/server.py`",
    "--port","8991",
    "--model_dir","pretrained_models/Fun-CosyVoice3-0.5B"
  ) -WorkingDirectory "D:\AI\models\CosyVoice" -WindowStyle Hidden

# ============== 验证 ==============
Start-Sleep -Seconds 5
curl http://127.0.0.1:8065/v1/models
curl http://127.0.0.1:8993/v1/models
curl http://127.0.0.1:8991/inference_sft -X POST
```

### 显存 / 内存预算（粗算）

| 进程 | 模型 | 显存（VRAM） | 内存（RAM） |
|---|---|---|---|
| 主对话 GGUF 8B IQ4_NL | — | ~5.0 GB | ~3 GB |
| 摘要 llama-server Qwen2.5-VL-3B Q4_K_M | text 1.8 GB + mmproj 1.25 GB | **~3.2 GB** | ~1 GB |
| ASR whisper.cpp large-v3-turbo q5_0 | 547 MiB | **~0.7 GB** | ~0.2 GB |
| TTS CosyVoice3 0.5B fp16 | ~1.0 GB | **~1.2 GB** | ~0.5 GB |
| 游戏/前台 | — | ~4-5 GB | — |
| **合计** | | **~14-15 GB**（贴顶 16GB） | 远低于 32GB |

> 想保险一点：摘要改用**纯文本** Qwen2.5-3B-Instruct（无 mmproj，省 1.25 GB 显存）；TTS 用 FP16（默认就够）。

---

## 5. Reference（全部可点开验证）

### 5.1 llama.cpp / 摘要
- llama.cpp multimodal 官方文档（Vision + Audio 模型清单 + --hf 用法）：<https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md>
- llama-server 工具 README：<https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>
- llama.cpp Windows releases（CUDA 12.4 / 13.x / Vulkan / CPU 全套预编译）：<https://github.com/ggml-org/llama.cpp/releases>
- 第三方 sm_120 Windows 优化构建（MTP + TurboQuant）：<https://github.com/Andgihat/llama-cpp-mtp-turboquant-sm120-blackwell-windows>
- ggml-org/Qwen2.5-VL-3B-Instruct-GGUF：<https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF>
- bartowski/Qwen_Qwen3-VL-4B-Instruct-GGUF（含 imatrix 量化尺寸表）：<https://huggingface.co/bbartowski/Qwen_Qwen3-VL-4B-Instruct-GGUF>
- bartowski/Qwen2.5-3B-Instruct-GGUF：<https://huggingface.co/bbartowski/Qwen2.5-3B-Instruct-GGUF>
- Dhptl/Qwen2.5-VL-3B-Instruct-GGUF（详细尺寸表 Q4_K_M=1.80 GB，mmproj-f16=1.25 GB）：<https://huggingface.co/Dhptl/Qwen2.5-VL-3B-Instruct-GGUF>
- unsloth Qwen3-VL-4B chat template 修复（--jinja 必加）：<https://huggingface.co/unsloth/Qwen3-VL-4B-Instruct-GGUF>

### 5.2 ASR
- whisper.cpp 主仓库：<https://github.com/ggml-org/whisper.cpp>
- whisper.cpp Windows 预编译 + 模型清单：<https://github.com/ggml-org/whisper.cpp/releases>
- whisper.cpp server 示例（--inference-path / --request-path 支持 OpenAI 兼容）：<https://github.com/ggml-org/whisper.cpp/tree/master/examples/server>
- PR #2270（OpenAI 客户端兼容路径）：<https://github.com/ggerganov/whisper.cpp/pull/2270>
- sona（基于 whisper.cpp 的 OpenAI 兼容 Rust 单文件 server，Win x64 二进制）：<https://github.com/thewh1teagle/sona>
- sherpa-onnx 主仓库（Win + 流式 Paraformer）：<https://github.com/k2-fsa/sherpa-onnx>
- sherpa-onnx 流式 Paraformer（csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en）：<https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-paraformer/paraformer-models.html>
- sherpa-onnx offline-websocket server：<https://k2-fsa.github.io/sherpa/onnx/websocket/offline-websocket.html>
- sherpa-onnx 社区 HTTP 包装（小米）：<https://github.com/yaming116/sherpa-onnx-asr>
- FunASR 官方 runtime 部署文档：<https://github.com/modelscope/FunASR/blob/main/runtime/quick_start.md>
- FunASR **OpenAI 兼容 server**（/v1/audio/transcriptions，win 直接跑）：<https://github.com/modelscope/FunASR/blob/main/examples/openai_api/README.md>
- FunASR 离线 GPU SDK 部署：<https://github.com/modelscope/FunASR/blob/main/runtime/docs/SDK_advanced_guide_offline_gpu.md>
- mradermacher/Qwen3-ASR-1.7B-GGUF 尺寸表：<https://huggingface.co/mradermacher/Qwen3-ASR-1.7B-GGUF>
- ggml-org/Qwen3-ASR-1.7B-GGUF（llama-server -hf 官方预量化）：<https://huggingface.co/ggml-org/Qwen3-ASR-1.7B-GGUF>
- Qwen3-ASR llama-cpp-python chat handler（JamePeng2023/Qwen3-ASR-1.7B-GGUF）：<https://huggingface.co/JamePeng2023/Qwen3-ASR-1.7B-GGUF>
- CrispASR（Qwen3-ASR 纯 C++ 后端）：<https://huggingface.co/cstr/qwen3-asr-1.7b-GGUF>
- HaujetZhao/Qwen3-ASR-GGUF（ONNX Encoder + GGUF Decoder，Win Vulkan）：<https://github.com/HaujetZhao/Qwen3-ASR-GGUF>

### 5.3 TTS
- CosyVoice 官方仓库：<https://github.com/FunAudioLLM/CosyVoice>
- Fun-CosyVoice3-0.5B-2512（2025-12 最新版）：<https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512>
- CosyVoice2-0.5B（更稳的备选）：<https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B>
- CosyVoice 官方 FastAPI server：
`runtime/python/fastapi/server.py`（端点 /inference_zero_shot, /inference_sft, /inference_cross_lingual, /inference_instruct）：<https://github.com/FunAudioLLM/CosyVoice/blob/main/r`runtime/python/fastapi/server.py`>
- CosyVoice 硬件 / VRAM 报告（0.5B Q4_K_M ≈ 600 MB，FP16 ≈ 1.2 GB）：<https://www.madebyagents.com/models/cosyvoice-2-0>
- CosyVoice Windows 社区 fork（v3ucn/lyricremix，api.py 端口 9880）：<https://github.com/v3ucn/CosyVoice_For_Windows>
- CosyVoice Windows 增强包（含 vLLM 加速 + OpenAI TTS API + 语音管理 WebUI）：<https://github.com/EitanWong/CosyVoice-Enhanced>
- neosun/cosyvoice-docker（**OpenAI 兼容** /v1/audio/speech，一键 docker）：<https://github.com/neosun100/cosyvoice-docker>
- sin-tag/CosyVoice2-API（v2 + v3 REST + 流式）：<https://github.com/sin-tag/CosyVoice2-API>
- fengin/Fun-CosyVoice3-0.5B-2512-Deploy（PyTorch 部署脚本）：<https://github.com/fengin/Fun-CosyVoice3-0.5B-2512-Deploy>
- CosyVoice3 PyTorch 2.7+ sm_120 兼容问题（Issue #1815）：<https://github.com/FunAudioLLM/CosyVoice/issues/1815>
- F5-TTS 主仓库（流式 + 0 样本）：<https://github.com/SWivid/F5-TTS>
- F5-TTS FastAPI wrapper（/tts, /tts-stream）：<https://github.com/Nomannazir/f5-tts-fastapi>
- F5-TTS Windows 5060 / 5070 安装指南（确认需要 cu128）：<https://sneekes.app/posts/f5-tts-installation-guide-for-rtx-5070-on-wsl2/>
- GPT-SoVITS 主仓库：<https://github.com/RVC-Boss/GPT-SoVITS>
- GPT-SoVITS Windows 一键包：<https://huggingface.co/lj1995/GPT-SoVITS-windows-package>
- GPT-SoVITS API 文档（pi.py -p 9880）：<https://github.com/RVC-Boss/GPT-SoVITS/blob/fast_inference_/api_v3.py>
- Spark-TTS 仓库（0.5B，Qwen2.5 内核）：<https://github.com/SparkAudio/Spark-TTS>
- Spark-TTS Windows 安装 Issue（确认需 PyTorch nightly cu128 for sm_120）：<https://github.com/SparkAudio/Spark-TTS/issues/5>
- IndexTTS2 仓库（带情感控制）：<https://github.com/index-tts/index-tts>
- IndexTTS2 arXiv 论文：<https://arxiv.org/html/2506.21619v1>
- Brakanier/FastCosyVoice（RTX 5060ti 性能 benchmark，TTFB 0.376s / RTF 0.203）：<https://github.com/Brakanier/FastCosyVoice>

### 5.4 RTX 5060 Ti / PyTorch / 驱动
- PyTorch sm_120 官方支持说明："PyTorch 2.7.0 already added Blackwell support on our PyTorch wheels built with CUDA 12.8"：<https://discuss.pytorch.org/t/when-will-sm120-support-be-available/223621>
- PyTorch 5060 Ti 实战：必须 nightly cu128 wheel：<https://discuss.pytorch.org/t/how-do-i-use-pytorch-with-rtx-5060-ti/220926>
- PyTorch 5060 早期 issue 与解决路径：<https://discuss.pytorch.org/t/pytorch-support-for-sm-120-nvidia-geforce-rtx-5060/220941>