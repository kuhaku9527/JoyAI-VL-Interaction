# JoyVL 安装兼容性说明

> 原文档: [README.md](README.md)

这个 `install` 目录用于将核心 WebUI 安装、可选服务适配器和较重的模型运行时环境分开管理。`install/` 不再提供服务启动入口；启动脚本位于 `services/` 下，各组件的服务级脚本位于其 `scripts/` 目录中。

除非另有说明，请从仓库根目录运行下面的命令。

所有默认模型权重路径都位于 `/tmp/models/<model-name>`。当前默认值为：

- 主交互模型：`/tmp/models/JoyAI-VL-Interaction-Preview`，默认仓库 `jdopensource/JoyAI-VL-Interaction-Preview`
- 摘要模型：`/tmp/models/Qwen3-VL-4B-Instruct`，默认仓库 `Qwen/Qwen3-VL-4B-Instruct`
- ASR 模型：`/tmp/models/Qwen3-ASR-1.7B`，默认仓库 `Qwen/Qwen3-ASR-1.7B`
- TTS 模型：`/tmp/models/Qwen3-TTS-12Hz-1.7B-CustomVoice`，默认仓库 `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`

如果默认目录不存在或为空，请先使用统一下载脚本下载权重。不要回退到项目内部的 `models/` 子目录：

```bash
./install/download-models.sh --all
```

## 核心安装

- `install.sh` 使用 `uv venv` 创建虚拟环境，然后用 `uv pip install` 下载并安装依赖。
- `install.sh` 以 editable 模式安装 WebUI。
- `install.sh` 固定 `vllm==0.22.0`。
- `install.sh` 默认使用 `constraints.txt` 约束与 vLLM 相关的传递 Web 栈依赖。
- 本安装目录统一使用 Python 3.12。
- `vllm==0.22.0` 支持 Python `>=3.10,<3.15`，但本项目使用 Python 3.12 安装并测试。它会拉取较重的 PyTorch/CUDA 依赖，因此推荐使用干净的新虚拟环境。
- WebUI 模板本身没有直接声明 FastAPI。启用可选适配器时会安装 FastAPI，`vllm==0.22.0` 也可能通过传递依赖安装 FastAPI。

### vLLM Web 栈约束

`vllm==0.22.0` 声明了较宽泛的依赖：

- `fastapi[standard]>=0.115.0`
- `prometheus-fastapi-instrumentator>=7.0.0`

如果没有约束，当前解析器可能选择 `fastapi==0.137.x`、`prometheus-fastapi-instrumentator==8.0.0` 或 `starlette==1.x`。在 `fastapi==0.137.x` 下，一些路由在 `include_router` 后仍会保留为 `_IncludedRouter`，而当前 vLLM 使用的指标中间件仍会从旧路由结构读取 `.path`。这种组合可能导致 vLLM OpenAI API 请求在指标中间件内部失败：

```text
AttributeError: '_IncludedRouter' object has no attribute 'path'
```

因此，`constraints.txt` 固定：

```text
fastapi<0.137
prometheus-fastapi-instrumentator<8
```

这些约束会让解析器选择仍与 `vllm==0.22.0` 兼容的 FastAPI/Starlette 0.x 栈。测试中，`fastapi==0.136.0` 仍会将 router 展开为常规 `APIRoute` 对象，而 `fastapi==0.137.0` 开始产生 `_IncludedRouter`。

## 可选适配器服务

这些选项只安装轻量级适配器/API 包：

- `--with-asr`：安装 FastAPI ASR WebSocket 适配器服务。
- `--with-tts`：安装 FastAPI TTS WebSocket 适配器服务。
- `--with-background-agent`：安装 FastAPI Codex 后台 agent API。
- `--with-all`：安装上述所有可选包。

这些包依赖常见 Web 服务库，例如 FastAPI、Uvicorn、WebSockets、HTTPX 和 Pydantic。它们不会安装 ASR nightly vLLM、vLLM Omni、模型权重或 CUDA 特定 wheel。

## ASR 运行时环境

`services/asr/README.md` 使用 Python 3.12、vLLM nightly 和 CUDA 12.9 index。除非你明确希望替换主环境中固定的 `vllm==0.22.0`，否则不要把该运行时混入核心 WebUI 环境。

安装 ASR 适配器：

```bash
./install/install.sh --with-asr
```

如果你按照 ASR README 启动真实 ASR 模型服务，请使用独立环境。

安装真实 ASR 模型服务运行时：

```bash
./install/install-audio-runtime.sh --asr
./install/download-models.sh --all
```

默认下载路径为 `/tmp/models/Qwen3-ASR-1.7B`。

启动它：

```bash
./services/asr/scripts/run.sh all
```

## TTS 运行时环境

TTS 适配器可以共享核心环境，但真实 TTS 模型服务需要 `vllm-omni==0.22.0` 与 `vllm==0.22.0` 一起使用。本安装目录统一使用 Python 3.12。安装真实 TTS 环境时，请在同一个安装命令中解析 `vllm==0.22.0` 和 `vllm-omni==0.22.0`，并继续使用 `constraints.txt` 约束 vLLM Web 栈。

安装 TTS 适配器：

```bash
./install/install.sh --with-tts
```

生产使用时，请在独立环境中安装并运行 vLLM Omni。

安装真实 TTS 模型服务运行时：

```bash
./install/install-audio-runtime.sh --tts
./install/download-models.sh --all
```

默认下载路径为 `/tmp/models/Qwen3-TTS-12Hz-1.7B-CustomVoice`。

启动它：

```bash
./services/tts/scripts/run.sh all
```

`services/tts/scripts/run.sh all` 会先启动 TTS vLLM Omni，等待上游端口可用（默认每 5 秒重试一次），然后在适配器 `/health` 端点就绪后，在后台运行一次真实端到端预热：

```bash
joyvl-tts-adapter smoke --text "Hello." --output /tmp/joyvl_tts_warmup.pcm --timeout 180
```

这会在用户流量到来前消耗掉 Triton JIT、CUDA graph capture、code predictor 预热和缓存初始化的首次请求成本。测试中，冷启动的第一次 TTS 响应可能需要几十秒；预热后，后续请求会回到正常延迟。设置 `TTS_ENABLE_WARMUP=0` 可禁用预热。使用 `TTS_WARMUP_TEXT`、`TTS_WARMUP_OUTPUT` 和 `TTS_WARMUP_TIMEOUT` 可修改预热文本、输出文件和超时时间。

## 后台 Agent

安装：

```bash
./install/install.sh --with-background-agent --max-subagents 6
```

安装脚本会写入：

- `services/background-agent/background-agent.env`

启动：

```bash
./services/background-agent/scripts/run.sh
```

`--max-subagents N` 会同时配置 `CODEX_API_MAX_SUBAGENTS` 和 `BACKGROUND_MAX_SUBAGENTS`。当前项目默认值为 `6`。

## Windows 原生部署（PowerShell）

> 参考：`docs\lightweight-replacement.md`。
> 所有脚本兼容 PowerShell 5.1（不依赖 PowerShell 7 专属语法）。

Windows 原生部署用原生 Windows 二进制替换 `vLLM` / `vLLM-Omni`（仅 Linux 可用）：

| 原 Linux 组件 | Windows 替代（新增） | 配套脚本 |
| --- | --- | --- |
| `vllm`（主 + 摘要） | `llama.cpp` sm_120 预编译 | `install\setup-llama-cpp.ps1` |
| `vllm` ASR（Qwen3-ASR） | `whisper.cpp` cublas 预编译 | `install\setup-whisper-cpp.ps1` |
| `vllm-omni` TTS（Qwen3-TTS） | `CosyVoice3-0.5B` FastAPI server | `install\setup-cosyvoice.ps1` |
| `codex` CLI / shim | `hermes-agent` gateway（NousResearch） | `install\setup-hermes.ps1` |

端口与 Linux 部署完全一致，所以适配器和 webui 不用改任何代码。

### 三步上手

```powershell
# 1) 一键安装（Python 3.12、uv、git、ffmpeg、venv、5 个服务的 editable 安装、
#    可选 PyTorch cu128、可选 conda env 'cosyvoice'）。
powershell -ExecutionPolicy Bypass -File .\install\install-windows.ps1

# 2) 下载所有 GGUF 模型到 D:\AI\models\。
powershell -ExecutionPolicy Bypass -File .\install\download-gguf-models.ps1 -Component all

# 3) 依次安装四个原生后端（全部幂等）。
powershell -ExecutionPolicy Bypass -File .\install\setup-llama-cpp.ps1
powershell -ExecutionPolicy Bypass -File .\install\setup-whisper-cpp.ps1
powershell -ExecutionPolicy Bypass -File .\install\setup-cosyvoice.ps1
powershell -ExecutionPolicy Bypass -File .\install\setup-hermes.ps1

# 4) 启动完整栈（webui 跑在前台，Ctrl+C 停）。
cd services
powershell -ExecutionPolicy Bypass -File .\scripts\run-windows.ps1
```

### 安装器参数

| 脚本 | 常用参数 |
| --- | --- |
| `install\install-windows.ps1` | `-SkipCuda` `-SkipConda` `-SkipTorch` `-SkipEditable` `-Python312Path <path>` |
| `install\download-gguf-models.ps1` | `-Component main|summary|all`（默认 `all`）`-HfToken <token>` `-SkipMmproj` |
| `install\setup-llama-cpp.ps1` | `-ForceRedownload` |
| `install\setup-whisper-cpp.ps1` | `-AsrModel <file>` `-ForceRedownload` |
| `install\setup-cosyvoice.ps1` | `-CondaExe <path>` `-EnvName <name>` `-ForceReclone` |
| `install\setup-hermes.ps1` | `-HermesRepo owner/repo` `-HermesVersion vX.Y.Z` |
| `services\scripts\run-windows.ps1` | `-Mode default|minimal|voice|gaming` `-Restart <name|all>` `-Stop` |
| `services\scripts\stop-windows.ps1` | `-Only <name1,name2>` `-AllPorts` `-GraceSeconds N` |

### 生成的目录布局

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
    └── CosyVoice\        （git clone --recursive）
%LOCALAPPDATA%\hermes\   （setup-hermes.ps1 创建）
D:\AI\workspace\JoyAI-VL-Interaction-main\services\.venv\
```

### 运行模式

| 模式 | 启动的服务 |
| --- | --- |
| `default` | main、summary、whisper、cosyvoice、voice-clone、hermes、background-agent、webinfer、tts-adapter、asr-adapter、webui |
| `minimal` | main、webinfer、webui（最小端到端冒烟） |
| `voice`   | main、whisper、cosyvoice、voice-clone、tts-adapter、asr-adapter、webinfer、webui（完整语音流，无后台 agent） |
| `gaming`  | `default` + `FORCE_SILENCE_BEFORE_QUERY=false` + `LOG_LEVEL=WARNING` |

### 重启 / 停止单个服务

```powershell
# 只重启主模型（换完 GGUF 常用）。
powershell -ExecutionPolicy Bypass -File services\scripts\run-windows.ps1 -Restart llama-main

# 全部停掉。
powershell -ExecutionPolicy Bypass -File services\scripts\stop-windows.ps1
```

### 显存预算（RTX 5060 Ti 16 GB）

| 进程 | 约占用 | 备注 |
| --- | --- | --- |
| llama-server main（JoyAI-VL IQ4_NL + mmproj） | ~7.0 GB | `-ngl 999` |
| llama-server summary（Qwen2.5-VL-3B Q4_K_M + mmproj） | ~3.2 GB | `-ngl 999`，`-c 8192` |
| whisper.cpp（ggml-large-v3-turbo-q5_0） | ~1.2 GB | cublas |
| CosyVoice3-0.5B（FP16） | ~1.0 GB | cu128 |
| voice-clone / tts-adapter / asr-adapter / webinfer / hermes / webui | 各 ~0.2 GB（CPU） | 可忽略 |
| **`default` 模式合计** | **~12.6 GB** | 给游戏留 ~3.4 GB |
| **`minimal` 模式合计** | **~7.2 GB** | 给游戏留 ~8.8 GB |
| **`voice` 模式合计** | **~9.0 GB** | 给游戏留 ~7.0 GB |

想给游戏让出更多显存，可以降低 summary 模型的 `-ngl`，或者直接用
`Mode = voice`（不启动 summary；webinfer 适配器仍然能工作，chunk 摘要
步骤会变成 no-op）。

### 幂等 / 失败回退

- 每个脚本启动后都写一个 `services\.pids\<name>.pid`；再跑一遍会先清掉
  旧 PID 再起新进程。
- `run-windows.ps1` 在任一服务就绪失败时立即停掉其它已起的服务并报错。
- `Ctrl+C` 触发 `Stop-All`：先按 PID 文件杀，再按端口 `Get-NetTCPConnection`
  兜底。
- 全部脚本可重复运行：期望产物已就位时会直接打 `[OK]` 退出，不做任何
  破坏性动作。
