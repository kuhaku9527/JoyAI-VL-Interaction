# JoyAI-VL 声音克隆服务

> **现行实现（2026-07-12）**：本服务只支持 MiniMax Rapid Clone + `speech-2.8-hd`，端口 `8985`。`TTS_PROVIDER` 只能为 `minimax`，缺少 `MINIMAX_API_KEY` 或 `MINIMAX_GROUP_ID` 时拒绝启动。
> WebUI/Jarvis 直接调用 `POST /v1/synthesize`，不经过 `8991/8992`。
> `scripts/start-cosyvoice.ps1`、旧 `scripts/run-windows.ps1`、stub 分支均已删除。
> 下文 CosyVoice/8991/8992 内容是初版服务设计的历史说明，禁止按其启动；当前接口与操作以 [`../../doc/voice-clone.md`](../../doc/voice-clone.md) 为准。

---

一个轻量的 FastAPI 适配服务，封装上游 **CosyVoice3** 服务，向上提供：

- **声音档案 CRUD**（3-10 秒参考音频 + 可选转写文本）
- `POST /v1/synthesize` 端点：调用 **zero-shot TTS**，按档案音色合成 PCM16 / 24 kHz / 单声道
- `WebSocket /v1/synthesize/ws`：流式输出 PCM16 chunk，适合低延迟播放

默认监听 `127.0.0.1:8985`，避免与 CosyVoice（`8991`）、TTS 适配器（`8992`）、
whisper.cpp ASR（`8993`）等已有端口冲突。

## 为什么单独做一个服务？

CosyVoice3 官方 FastAPI 服务
（`runtime/python/fastapi/server.py`）的接口是特定的多段 wav 协议，
JoyAI-VL 栈的 TTS 适配器 / webui 已经在用一套更上层的 WebSocket 协议。
本服务是**中间适配层**：负责声音档案管理、上传后立即对 CosyVoice 做冒烟测试、
把上游的 wav 翻译成干净的 PCM16。

## 架构

```
                  +-----------------------------+
   WebUI / webui  |  tts_adapter (8992)        |
   ─────────────► |   - ws://.../ws/tts         |
                  |   - 识别 voice_id            |
                  +-------------+---------------+
                                | voice_id 已设?
                                v
                  +-----------------------------+         +---------------------------+
                  |  voice_clone_api (8985)     |  HTTP   |  CosyVoice3 服务 (8991)   |
                  |   - /v1/voices CRUD         | ──────► |  /inference_zero_shot     |
                  |   - /v1/synthesize          |  wav    |  /inference_cross_lingual |
                  +-----------------------------+         +---------------------------+
```

## 快速开始

### 1. 启动 CosyVoice3

```powershell
# 一次性下载模型（Fun-CosyVoice3-0.5B-2512，约 1 GB）
huggingface-cli download FunAudioLLM/Fun-CosyVoice3-0.5B-2512 `
  --local-dir D:\AI\models\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B-2512

# 创建并激活 cosyvoice conda 环境（Python 3.12 + torch cu128）
conda create -n cosyvoice python=3.12 -y
conda activate cosyvoice
pip install -r D:\AI\models\CosyVoice\requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 用本服务提供的脚本启动
.\services\voice-clone\scripts\start-cosyvoice.ps1
```

脚本会把 PID 写到 `services/voice-clone/scripts/cosyvoice.pid`，并
循环探测 `http://127.0.0.1:8991/` 直到 CosyVoice 就绪。

### 2. 启动 voice-clone 服务

```powershell
# 建 venv 并安装本服务
py -3.12 -m venv services\voice-clone\.venv
.\services\voice-clone\.venv\Scripts\Activate.ps1
pip install -e services/voice-clone

# 用本服务提供的脚本启动
.\services\voice-clone\scripts\run-windows.ps1
```

脚本会把 PID 写到 `services/voice-clone/scripts/voice_clone_api.pid`，
并循环探测 `http://127.0.0.1:8985/health` 直到 voice-clone 就绪。

### 3. 告诉 TTS 适配器走声音克隆

在 `services/tts/scripts/run-adapter.sh`（或当前 shell）里加环境变量：

```bash
export TTS_DEFAULT_VOICE_ID=vc_1730000000_abc12345
export TTS_CLONE_API_URL=http://127.0.0.1:8985
```

只要 `TTS_DEFAULT_VOICE_ID` 非空，tts_adapter 就把每条 TTS 请求
**转给** voice-clone 服务，原 vLLM-Omni 路径不再被调用。
也支持按请求覆盖：webui 可以在 TTS `config` 消息里加
`voice_id` 字段，适配器优先用请求里的值。

## API 契约

### `GET /health`

```json
{
  "status": "ok",
  "cosyvoice_url": "http://127.0.0.1:8991",
  "cosyvoice_ok": true,
  "cosyvoice": { "model": "Fun-CosyVoice3-0.5B-2512", "spk": ["中文女", "中文男", ...] },
  "voices_dir": "D:\\AI\\workspace\\JoyAI-VL-Interaction-main\\services\\voice-clone\\voices",
  "voice_count": 1,
  "sample_rate": 24000
}
```

### `GET /v1/voices`

列出全部已注册声音档案。

```json
{ "items": [ { "voice_id": "vc_...", "name": "narrator", "duration_sec": 4.2, ... } ], "count": 1 }
```

### `POST /v1/voices`

multipart 上传。字段：`name` / `audio`（wav/mp3，<=25 MiB）/
`transcript`（可选）/ `language`（`zh`/`en`/`auto`，默认 `zh`）。

```bash
curl -X POST http://127.0.0.1:8985/v1/voices \
  -F "name=narrator" \
  -F "language=zh" \
  -F "transcript=这是一段示例参考音频" \
  -F "audio=@samples/reference.wav;type=audio/wav"
```

服务会：
1. 把立体声转单声道（如果需要）并存到 `voices/<id>/ref.wav`
2. 立即对 CosyVoice 调一次 `/inference_zero_shot` 冒烟测试
3. 返回档案元信息

### `GET /v1/voices/{voice_id}` / `DELETE /v1/voices/{voice_id}`

查询 / 删除单个档案。

### `POST /v1/synthesize`

```json
{
  "text": "你好，欢迎来到 JoyAI。",
  "voice_id": "vc_1730000000_abc12345",
  "speed": 1.0,
  "streaming": false
}
```

- `streaming=false` -> 直接返回 `SynthesizeResponse`（base64 pcm16 整段）
- `streaming=true` -> `text/event-stream`，事件类型：`start` / `audio.delta`（base64 pcm16 chunk） / `done` / `error`

### `WebSocket /v1/synthesize/ws`

```text
client -> server: {"text": "...", "voice_id": "..."}
server -> client: {"type": "start", "voice_id": "...", "sample_rate": 24000, "format": "pcm16"}
server -> client: <binary pcm16 chunks>
server -> client: {"type": "done", "voice_id": "..."}
```

## 工作流：克隆一个真实声音

1. **录 3-10 秒** 干净人声。最佳是 24 kHz 单声道 wav；16 kHz mp3 也接受。
2. **写出准确转写**。如果不传 transcript，CosyVoice 会自己 ASR，可能和
   你预期不一致。
3. **上传**：
   ```bash
   curl -X POST http://127.0.0.1:8985/v1/voices \
     -F "name=<user-name>" \
     -F "language=zh" \
     -F "transcript=<逐字转写>" \
     -F "audio=@<ref.wav>;type=audio/wav"
   ```
4. **冒烟测试**：
   ```bash
   curl -X POST http://127.0.0.1:8985/v1/synthesize \
     -H "Content-Type: application/json" \
     -d "{\"text\":\"测试一下声音\",\"voice_id\":\"<id>\",\"streaming\":false}" \
     | python -c "import sys,json,base64; d=json.load(sys.stdin); open('out.pcm','wb').write(base64.b64decode(d['pcm16_base64']))"
   # Windows: 用 Audacity 打开 out.pcm，选 24 kHz / 16-bit signed LE / 单声道
   ```
5. **接到 webui**：在启动 tts_adapter 之前设
   `TTS_DEFAULT_VOICE_ID=<id>`，之后所有 TTS 都用这个克隆声音。

## 端口分配

| 服务               | 端口 | 环境变量覆盖          |
|--------------------|------|----------------------|
| whisper.cpp ASR    | 8993 | `ASR_UPSTREAM_URL`   |
| TTS 适配器         | 8992 | `TTS_ADAPTER_PORT`   |
| CosyVoice3         | 8991 | `COSYVOICE_PORT`     |
| voice-clone（本服务）| 8985 | `VOICE_CLONE_PORT`   |
| webui              | 7860 | (webui)              |

## 配置

环境变量（全部可选，括号内是默认值）：

| 变量                  | 默认值                                  | 作用                                  |
|-----------------------|-----------------------------------------|---------------------------------------|
| `VOICE_CLONE_HOST`    | `127.0.0.1`                             | 监听地址                              |
| `VOICE_CLONE_PORT`    | `8985`                                  | 监听端口                              |
| `COSYVOICE_URL`       | `http://127.0.0.1:8991`                 | 上游 CosyVoice 根 URL                 |
| `VOICES_DIR`          | `./voices`                              | 声音档案持久化目录                    |
| `VOICE_SAMPLE_RATE`   | `24000`                                 | 兜底采样率（CosyVoice 原生）          |
| `VOICE_CLONE_TIMEOUT` | `120.0`                                 | 单次请求超时（秒）                    |
| `LOG_LEVEL`           | `INFO`                                  | uvicorn 日志级别                      |

## 常见问题

- **CosyVoice 在 RTX 5060 Ti 上 OOM**：请确认你装的是 PyTorch 2.7+ 的
  cu128 wheel。参考
  [`doc/lightweight-replacement.md`](../../doc/lightweight-replacement.md)
  的安装命令和
  [sm_120 issue #1815](https://github.com/FunAudioLLM/CosyVoice/issues/1815)
  解决方案。
- **模型下载太慢**：用 HF 镜像
  （`huggingface-cli download ... --endpoint <mirror>`），或者在
  另一台机器上预下载后拷到
  `D:\AI\models\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B-2512`。
- **声音像另一个人**：检查 `transcript` 是否**逐字**对齐音频。CosyVoice
  依赖转写做韵律对齐，错 1-2 个字就可能音色漂移。
- **能在多台机器上共享档案吗**：可以。`voices/<id>/` 自包含
  （`ref.wav` + `ref.txt` + `meta.json`），直接拷贝目录即可。
