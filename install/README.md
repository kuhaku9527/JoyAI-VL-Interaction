# JoyVL Installation Compatibility Notes

> 中文文档: [README.zh-CN.md](README.zh-CN.md)

This `install` directory keeps the core WebUI installation, optional service adapters, and heavy model runtime environments separate.
`install/` no longer provides service startup entrypoints; startup scripts live under `services/`, with service-level scripts in each component's `scripts/` directory.

Unless stated otherwise, run the commands below from the repository root.

All default model weight paths are under `/tmp/models/<model-name>`. The current defaults are:

- Main interaction model: `/tmp/models/JoyAI-VL-Interaction-Preview`, default repo `jdopensource/JoyAI-VL-Interaction-Preview`
- Summary model: `/tmp/models/Qwen3-VL-4B-Instruct`, default repo `Qwen/Qwen3-VL-4B-Instruct`
- ASR model: `/tmp/models/Qwen3-ASR-1.7B`, default repo `Qwen/Qwen3-ASR-1.7B`
- TTS model: `/tmp/models/Qwen3-TTS-12Hz-1.7B-CustomVoice`, default repo `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`

If a default directory does not exist or is empty, download the weights with the unified download script first. Do not fall back to a `models/` subdirectory inside the project:

```bash
./install/download-models.sh --all
```

## Core Installation

- `install.sh` creates the virtual environment with `uv venv`, then downloads and installs dependencies with `uv pip install`.
- `install.sh` installs the WebUI in editable mode.
- `install.sh` pins `vllm==0.22.0`.
- `install.sh` uses `constraints.txt` by default to constrain vLLM-related transitive Web stack dependencies.
- This install directory standardizes on Python 3.12.
- `vllm==0.22.0` supports Python `>=3.10,<3.15`, but this project installs and tests it with Python 3.12. It pulls in heavy PyTorch/CUDA dependencies, so a clean new virtual environment is recommended.
- The WebUI template itself does not declare FastAPI directly. FastAPI is installed when optional adapters are enabled, and `vllm==0.22.0` may also install FastAPI through transitive dependencies.

### vLLM Web Stack Constraints

`vllm==0.22.0` declares broad dependencies:

- `fastapi[standard]>=0.115.0`
- `prometheus-fastapi-instrumentator>=7.0.0`

Without constraints, the current resolver may select `fastapi==0.137.x`, `prometheus-fastapi-instrumentator==8.0.0`, or `starlette==1.x`. With `fastapi==0.137.x`, some routes remain as `_IncludedRouter` after `include_router`, while the metrics middleware used by the current vLLM still reads `.path` from the older route shape. This combination can make vLLM OpenAI API requests fail inside the metrics middleware:

```text
AttributeError: '_IncludedRouter' object has no attribute 'path'
```

For that reason, `constraints.txt` pins:

```text
fastapi<0.137
prometheus-fastapi-instrumentator<8
```

These constraints make the resolver choose a FastAPI/Starlette 0.x stack that remains compatible with `vllm==0.22.0`. In testing, `fastapi==0.136.0` still expands routers into regular `APIRoute` objects, while `fastapi==0.137.0` starts producing `_IncludedRouter`.

## Optional Adapter Services

These options install only lightweight adapter/API packages:

- `--with-asr`: install the FastAPI ASR WebSocket adapter service.
- `--with-tts`: install the FastAPI TTS WebSocket adapter service.
- `--with-background-agent`: install the FastAPI Codex background agent API.
- `--with-all`: install all optional packages above.

These packages depend on common Web service libraries such as FastAPI, Uvicorn, WebSockets, HTTPX, and Pydantic. They do not install ASR nightly vLLM, vLLM Omni, model weights, or CUDA-specific wheels.

## ASR Runtime Environment

`services/asr/README.md` uses Python 3.12, vLLM nightly, and the CUDA 12.9 index. Unless you explicitly want to replace the pinned `vllm==0.22.0` in the main environment, do not mix that runtime into the core WebUI environment.

Install the ASR adapter:

```bash
./install/install.sh --with-asr
```

If you start the real ASR model service following the ASR README, use a separate environment.

Install the real ASR model service runtime:

```bash
./install/install-audio-runtime.sh --asr
./install/download-models.sh --all
```

The default download path is `/tmp/models/Qwen3-ASR-1.7B`.

Start it:

```bash
./services/asr/scripts/run.sh all
```

## TTS Runtime Environment

The TTS adapter can share the core environment, but the real TTS model service requires `vllm-omni==0.22.0` together with `vllm==0.22.0`. This install directory standardizes on Python 3.12. When installing the real TTS environment, resolve `vllm==0.22.0` and `vllm-omni==0.22.0` in the same install command, and continue using `constraints.txt` to constrain the vLLM Web stack.

Install the TTS adapter:

```bash
./install/install.sh --with-tts
```

For production use, install and run vLLM Omni in a separate environment.

Install the real TTS model service runtime:

```bash
./install/install-audio-runtime.sh --tts
./install/download-models.sh --all
```

The default download path is `/tmp/models/Qwen3-TTS-12Hz-1.7B-CustomVoice`.

Start it:

```bash
./services/tts/scripts/run.sh all
```

`services/tts/scripts/run.sh all` starts TTS vLLM Omni first, waits for the upstream port to become available, retrying every 5 seconds by default, and then runs one real end-to-end warmup in the background after the adapter `/health` endpoint is ready:

```bash
joyvl-tts-adapter smoke --text "Hello." --output /tmp/joyvl_tts_warmup.pcm --timeout 180
```

This spends the first-request cost of Triton JIT, CUDA graph capture, code predictor warmup, and cache initialization before user traffic arrives. In testing, a cold first TTS response may take tens of seconds; after warmup, subsequent requests return to normal latency. Set `TTS_ENABLE_WARMUP=0` to disable it. Use `TTS_WARMUP_TEXT`, `TTS_WARMUP_OUTPUT`, and `TTS_WARMUP_TIMEOUT` to change the warmup text, output file, and timeout.

## Background Agent

Install:

```bash
./install/install.sh --with-background-agent --max-subagents 6
```

The install script writes:

- `services/background-agent/background-agent.env.example`（复制为 `background-agent.env` 并填入真实值；`*.env` 已被 gitignore，真实配置不进 VCS）

Start:

```bash
./services/background-agent/scripts/run.sh
```

`--max-subagents N` configures both `CODEX_API_MAX_SUBAGENTS` and `BACKGROUND_MAX_SUBAGENTS`. The current project default is `6`.

## Windows Native Deployment (PowerShell)

> Reference: `doc/lightweight-replacement.md`.
> All scripts are PS 5.1-compatible (no PowerShell-7-only syntax).

The Windows native stack replaces `vLLM` / `vLLM-Omni` (Linux-only) with native Windows binaries:

| Linux component (existing) | Windows replacement (new) | Backed by |
| --- | --- | --- |
| `vllm` (main + summary) | `llama.cpp` sm_120 prebuilt | `install\setup-llama-cpp.ps1` |
| `vllm` ASR (Qwen3-ASR) | `whisper.cpp` cublas prebuilt | `install\setup-whisper-cpp.ps1` |
| `vllm-omni` TTS (Qwen3-TTS) | `CosyVoice3-0.5B` FastAPI server | `install\setup-cosyvoice.ps1` |
| `codex` CLI / shim | `hermes-agent` gateway (NousResearch) | `install\setup-hermes.ps1` |

Ports are kept identical to the Linux deployment so adapters and the webui
do not need any code changes.

### Three-step quick start

```powershell
# 1) One-shot install (Python 3.12, uv, git, ffmpeg, venv, all 5 editable
#    services, optional PyTorch cu128, optional conda env 'cosyvoice').
powershell -ExecutionPolicy Bypass -File .\install\install-windows.ps1

# 2) Download all GGUF models into D:\AI\models\.
powershell -ExecutionPolicy Bypass -File .\install\download-gguf-models.ps1 -Component all

# 3) Install the four native backends (each is idempotent).
powershell -ExecutionPolicy Bypass -File .\install\setup-llama-cpp.ps1
powershell -ExecutionPolicy Bypass -File .\install\setup-whisper-cpp.ps1
powershell -ExecutionPolicy Bypass -File .\install\setup-cosyvoice.ps1
powershell -ExecutionPolicy Bypass -File .\install\setup-hermes.ps1

# 4) Launch the full stack (webui in the foreground, Ctrl+C to stop).
cd services
powershell -ExecutionPolicy Bypass -File .\scripts\run-windows.ps1
```

### Installer parameters

| Script | Notable flags |
| --- | --- |
| `install\install-windows.ps1` | `-SkipCuda` `-SkipConda` `-SkipTorch` `-SkipEditable` `-Python312Path <path>` |
| `install\download-gguf-models.ps1` | `-Component main|summary|all` (default `all`) `-HfToken <token>` `-SkipMmproj` |
| `install\setup-llama-cpp.ps1` | `-ForceRedownload` |
| `install\setup-whisper-cpp.ps1` | `-AsrModel <file>` `-ForceRedownload` |
| `install\setup-cosyvoice.ps1` | `-CondaExe <path>` `-EnvName <name>` `-ForceReclone` |
| `install\setup-hermes.ps1` | `-HermesRepo owner/repo` `-HermesVersion vX.Y.Z` |
| `services\scripts\run-windows.ps1` | `-Mode default|minimal|voice|gaming` `-Restart <name|all>` `-Stop` |
| `services\scripts\stop-windows.ps1` | `-Only <name1,name2>` `-AllPorts` `-GraceSeconds N` |

### Generated layout

```
D:\AI\
├── bin\
│   ├── llama.cpp\llama-server.exe
│   └── whisper.cpp\whisper-server.exe
├── models\
│   ├── main\
│   │   ├── JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\joyai-vl-interaction-preview-iq4_nl-imat.gguf
│   │   ├── JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\imatrix.dat
│   │   └── mmproj\mmproj-joyai-vl-interaction-preview-f16.gguf
│   ├── summary\Qwen2.5-VL-3B-Instruct-GGUF\Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf
│   ├── summary\Qwen2.5-VL-3B-Instruct-GGUF\Qwen2.5-VL-3B-Instruct-mmproj-f16.gguf
│   ├── asr\ggml-large-v3-turbo-q5_0.bin
│   └── tts\CosyVoice3-0.5B\
└── tools\
    └── CosyVoice\        (git clone --recursive)
%LOCALAPPDATA%\hermes\   (set up by setup-hermes.ps1)
D:\AI\workspace\JoyAI-VL-Interaction-main\services\.venv\
```

### Run modes

| Mode | Services started |
| --- | --- |
| `default` | main, summary, whisper, cosyvoice, voice-clone, hermes, background-agent, webinfer, tts-adapter, asr-adapter, webui |
| `minimal` | main, webinfer, webui (smallest end-to-end smoke) |
| `voice`   | main, whisper, cosyvoice, voice-clone, tts-adapter, asr-adapter, webinfer, webui (full voice loop, no background agent) |
| `gaming`  | `default` + `FORCE_SILENCE_BEFORE_QUERY=false` + `LOG_LEVEL=WARNING` |

### Restart / stop one service

```powershell
# Re-launch only the main model (useful after swapping the GGUF).
powershell -ExecutionPolicy Bypass -File services\scripts\run-windows.ps1 -Restart llama-main

# Tear down everything.
powershell -ExecutionPolicy Bypass -File services\scripts\stop-windows.ps1
```

### VRAM budget (RTX 5060 Ti 16 GB)

| Process | Approx VRAM | Notes |
| --- | --- | --- |
| llama-server main (JoyAI-VL IQ4_NL + mmproj) | ~7.0 GB | `-ngl 999` |
| llama-server summary (Qwen2.5-VL-3B Q4_K_M + mmproj) | ~3.2 GB | `-ngl 999`, `-c 8192` |
| whisper.cpp (ggml-large-v3-turbo-q5_0) | ~1.2 GB | cublas |
| CosyVoice3-0.5B (FP16) | ~1.0 GB | cu128 |
| voice-clone / tts-adapter / asr-adapter / webinfer / hermes / webui | ~0.2 GB each (CPU) | negligible |
| **Total under `default` mode** | **~12.6 GB** | leaves ~3.4 GB for games |
| **Total under `minimal` mode** | **~7.2 GB** | leaves ~8.8 GB for games |
| **Total under `voice` mode** | **~9.0 GB** | leaves ~7.0 GB for games |

If you need more headroom for a game, lower `-ngl` on the summary model or
remove the summary service entirely by using `Mode = voice` (the webinfer
adapter still works without a summary model — the chunk-summarisation steps
become a no-op).

### Idempotency / failure behaviour

- Every script writes a `services\.pids\<name>.pid` after spawn. Restart the
  same script and it cleans up the previous PID first.
- `run-windows.ps1` aborts on the first service that fails to become ready
  and tears down the rest.
- `Ctrl+C` in `run-windows.ps1` triggers a `Stop-All` that walks all PID
  files and then falls back to per-port `Get-NetTCPConnection` to kill any
  remaining listener.
- All scripts are re-runnable: nothing destructive is done when the
  expected artefact is already in place (the script reports `[OK]` and
  exits early).
