# JoyAI-VL Voice Clone Service

> **Current implementation (2026-07-12):** this service supports MiniMax Rapid Clone and `speech-2.8-hd` only on port `8985`. `TTS_PROVIDER` must be `minimax`; startup fails without `MINIMAX_API_KEY` and `MINIMAX_GROUP_ID`.
> WebUI/Jarvis calls `POST /v1/synthesize` directly; ports `8991/8992` are not in the active path.
> The CosyVoice launch scripts and stub synthesis branch have been deleted.
> The CosyVoice material below is retained only as initial-design history. Do not use it to start the service; see [`../../doc/voice-clone.md`](../../doc/voice-clone.md) for the current contract.

---

A small FastAPI shim that wraps an upstream **CosyVoice3** server and exposes:

* a CRUD surface for **voice profiles** (3-10s reference audio + optional transcript)
* a `POST /v1/synthesize` endpoint that performs **zero-shot TTS** in the
  timbre of the selected profile and returns PCM16 24 kHz mono audio
* a `WebSocket /v1/synthesize/ws` bridge that streams PCM16 chunks for
  low-latency playback

It listens on **`127.0.0.1:8985`** by default, keeping the CosyVoice
(`8991`), the TTS adapter (`8992`), and the whisper.cpp ASR (`8993`)
ports untouched.

## Why a separate service?

`CosyVoice3` ships an official FastAPI server
(`runtime/python/fastapi/server.py`) whose endpoints speak a very
specific multipart wav contract. The rest of the JoyAI-VL stack (the
TTS adapter, the webui) already speaks a higher-level WebSocket
protocol. This service is the **adapter** in between: it owns voice
profile management, smoke-tests every upload against CosyVoice, and
translates the upstream's wav output into clean PCM16.

## Architecture

```
                  +-----------------------------+
   WebUI / webui  |  tts_adapter (8992)        |
   ─────────────► |   - ws://.../ws/tts         |
                  |   - voice_id aware          |
                  +-------------+---------------+
                                | voice_id set?
                                v
                  +-----------------------------+         +---------------------------+
                  |  voice_clone_api (8985)     |  HTTP   |  CosyVoice3 server (8991) |
                  |   - /v1/voices CRUD         | ──────► |  /inference_zero_shot     |
                  |   - /v1/synthesize          |  wav    |  /inference_cross_lingual |
                  +-----------------------------+         +---------------------------+
```

## Quick start

### 1. Start CosyVoice3

```powershell
# One-time model download (Fun-CosyVoice3-0.5B-2512, ~1 GB)
huggingface-cli download FunAudioLLM/Fun-CosyVoice3-0.5B-2512 `
  --local-dir D:\AI\models\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B-2512

# Activate the cosyvoice conda env (Python 3.12 + torch cu128)
conda create -n cosyvoice python=3.12 -y
conda activate cosyvoice
pip install -r D:\AI\models\CosyVoice\requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# Launch via the helper script
.\services\voice-clone\scripts\start-cosyvoice.ps1
```

The script writes its PID to `services/voice-clone/scripts/cosyvoice.pid`
and probes `http://127.0.0.1:8991/` until the model reports ready.

### 2. Start the voice-clone service

```powershell
# Create a venv and install the service
py -3.12 -m venv services\voice-clone\.venv
.\services\voice-clone\.venv\Scripts\Activate.ps1
pip install -e services/voice-clone

# Launch via the helper script
.\services\voice-clone\scripts\run-windows.ps1
```

The script writes its PID to `services/voice-clone/scripts/voice_clone_api.pid`
and probes `http://127.0.0.1:8985/health` until the service responds.

### 3. Tell the TTS adapter to use the clone service

Set the env var in `services/tts/scripts/run-adapter.sh` (or in your
shell) before launching the TTS adapter:

```bash
export TTS_DEFAULT_VOICE_ID=vc_1730000000_abc12345
export TTS_CLONE_API_URL=http://127.0.0.1:8985
```

When `TTS_DEFAULT_VOICE_ID` is set, `tts_adapter` forwards every TTS
request to the clone service instead of the original vLLM-Omni
upstream. Per-request overrides are also possible: the webui can include
`voice_id` in its TTS `config` message and the adapter will use that
value instead of the default.

## API reference

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

List all voice profiles.

```json
{ "items": [ { "voice_id": "vc_...", "name": "narrator", "duration_sec": 4.2, ... } ], "count": 1 }
```

### `POST /v1/voices`

Multipart upload. Fields: `name`, `audio` (wav/mp3, <=25 MiB), `transcript`
(optional), `language` (`zh`/`en`/`auto`, default `zh`).

```bash
curl -X POST http://127.0.0.1:8985/v1/voices \
  -F "name=narrator" \
  -F "language=zh" \
  -F "transcript=这是一段示例参考音频" \
  -F "audio=@samples/reference.wav;type=audio/wav"
```

The service:
1. re-encodes stereo -> mono (if needed) and stores `voices/<id>/ref.wav`
2. calls CosyVoice `/inference_zero_shot` once to verify the audio is usable
3. returns the profile metadata

### `GET /v1/voices/{voice_id}` / `DELETE /v1/voices/{voice_id}`

Read or delete a single profile.

### `POST /v1/synthesize`

Single-shot or streaming synthesis.

```json
{
  "text": "你好，欢迎来到 JoyAI。",
  "voice_id": "vc_1730000000_abc12345",
  "speed": 1.0,
  "streaming": false
}
```

* `streaming=false` -> returns `SynthesizeResponse` with base64 pcm16
  inline (`format: pcm16, sample_rate: 24000, channels: 1`).
* `streaming=true` -> returns a `text/event-stream` of `data: {json}`
  events. Payload types: `start`, `audio.delta` (base64 pcm16 chunk),
  `done`, `error`.

### `WebSocket /v1/synthesize/ws`

```text
client -> server: {"text": "...", "voice_id": "..."}
server -> client: {"type": "start", "voice_id": "...", "sample_rate": 24000, "format": "pcm16"}
server -> client: <binary pcm16 chunks>
server -> client: {"type": "done", "voice_id": "..."}
```

## Workflow: clone a real voice

1. **Record 3-10 seconds** of clean speech. WAV 24 kHz mono is best but
   16 kHz mp3 is also accepted.
2. **Transcribe** what was said. If you skip this CosyVoice will
   auto-ASR the reference and may pick a slightly different transcript.
3. **Upload**:
   ```bash
   curl -X POST http://127.0.0.1:8985/v1/voices \
     -F "name=<user-name>" \
     -F "language=zh" \
     -F "transcript=<exact transcript>" \
     -F "audio=@<ref.wav>;type=audio/wav"
   ```
4. **Smoke-test** the profile:
   ```bash
   curl -X POST http://127.0.0.1:8985/v1/synthesize \
     -H "Content-Type: application/json" \
     -d "{\"text\":\"测试一下声音\",\"voice_id\":\"<id>\",\"streaming\":false}" \
     | python -c "import sys,json,base64; d=json.load(sys.stdin); open('out.pcm','wb').write(base64.b64decode(d['pcm16_base64']))"
   aplay -f S16_LE -r 24000 -c 1 out.pcm   # Linux
   # On Windows, open out.pcm in Audacity: 24 kHz, 16-bit signed LE, mono
   ```
5. **Wire to the webui** by setting `TTS_DEFAULT_VOICE_ID=<id>` before
   starting `tts_adapter`. All subsequent TTS playback uses the cloned
   voice.

## Port map

| Service               | Port | Override env var          |
|-----------------------|------|---------------------------|
| whisper.cpp ASR       | 8993 | `ASR_UPSTREAM_URL`        |
| TTS adapter (this)    | 8992 | `TTS_ADAPTER_PORT`        |
| CosyVoice3            | 8991 | `COSYVOICE_PORT`          |
| voice-clone (this)    | 8985 | `VOICE_CLONE_PORT`        |
| webui                 | 7860 | (webui)                   |

## Configuration

Environment variables (all optional, defaults shown):

| Variable                | Default                                  | Purpose                                |
|-------------------------|------------------------------------------|----------------------------------------|
| `VOICE_CLONE_HOST`      | `127.0.0.1`                              | Bind interface                         |
| `VOICE_CLONE_PORT`      | `8985`                                   | Listen port                            |
| `COSYVOICE_URL`         | `http://127.0.0.1:8991`                  | Upstream CosyVoice base URL            |
| `VOICES_DIR`            | `./voices`                               | Where voice profiles are persisted     |
| `VOICE_SAMPLE_RATE`     | `24000`                                  | Fallback sample rate (CosyVoice native)|
| `VOICE_CLONE_TIMEOUT`   | `120.0`                                  | Per-request timeout in seconds         |
| `LOG_LEVEL`             | `INFO`                                   | Standard uvicorn log level             |

## Frequently asked questions

* **"CosyVoice keeps OOM-ing on my RTX 5060 Ti."** Make sure you are
  running PyTorch 2.7+ with CUDA 12.8 wheels. See
  [`doc/lightweight-replacement.md`](../../doc/lightweight-replacement.md)
  for the exact `pip install` line and the
  [sm_120 issue #1815](https://github.com/FunAudioLLM/CosyVoice/issues/1815)
  workaround.
* **"Model download is slow."** Use a Hugging Face mirror
  (`huggingface-cli download ... --endpoint <mirror>`) or pre-fetch on
  a different machine and copy the snapshot to
  `D:\AI\models\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B-2512`.
* **"Voice sounds like the wrong speaker."** Verify the `transcript`
  matches the audio word-for-word. CosyVoice uses the transcript for
  prosody alignment; even a 1-2 word drift can change the timbre.
* **"Can I share voices across machines?"** Yes -- `voices/<id>/` is
  self-contained (`ref.wav` + `ref.txt` + `meta.json`). Copy the
  directory to another host and restart the service.
