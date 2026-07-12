# Windows llama.cpp runtime (RTX 5060 Ti / sm_120)

> 解决上游 **Andgihat b9150** 在 Blackwell sm_120 上的崩溃（mmq.cuh + flash_attn sm_120 bug, llama.cpp #24218 / #22893），改用 **ggml-org/llama.cpp b9330 + CUDA 13.1**。

## 一键安装（首次）

```powershell
# 1. 下载 b9330 + CUDA 13.1 runtime 到 D:\AI\bin\llama.cpp\
powershell -ExecutionPolicy Bypass -File .\install\setup-llama-cpp.ps1

# 2. 启动
powershell -ExecutionPolicy Bypass -File .\install\windows\start-llama-server.ps1
```

## 启动脚本

`install/windows/start-llama-server.ps1` — 包装 llama-server.exe，自动设置 PATH、写 PID 文件、等待端口监听。

| 命令 | 说明 |
|---|---|
| `start-llama-server.ps1` | 启动 multimodal (LLM + mmproj)，端口 7060，ctx 4096 |
| `start-llama-server.ps1 -Port 8080 -CtxSize 8192` | 自定义端口和 ctx |
| `start-llama-server.ps1 -NoMmproj` | 纯文本 LLM（省 ~1.2 GB 显存） |
| `start-llama-server.ps1 -Status -Port 7060` | 查看状态 |
| `start-llama-server.ps1 -Stop -Port 7060` | 停止 |

PID 文件：`.pids/llama-server.pid`
日志：`logs/llama-server-YYYYMMDD-HHMMSS.log{,.err}`

## 验证

```powershell
# 启动后测试
(Invoke-WebRequest -Uri "http://127.0.0.1:7060/v1/models" -UseBasicParsing).Content
(Invoke-WebRequest -Uri "http://127.0.0.1:7060/health" -UseBasicParsing).Content
# → {"status":"ok"}
```

curl 测 chat：

```bash
curl -s http://127.0.0.1:7060/v1/chat/completions -H "Content-Type: application/json" -d '{
  "model": "joyai-vl-interaction-preview-iq4_nl-imat.gguf",
  "messages": [{"role":"user","content":"用中文说一句你好"}],
  "max_tokens": 50
}'
```

## 硬件 / 模型

| 项 | 值 |
|---|---|
| GPU | NVIDIA RTX 5060 Ti 16GB (sm_120 / Blackwell) |
| 驱动 | NVIDIA 591.86 (CUDA 13.1) |
| 主模型 | `D:\AI\models\main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\joyai-vl-interaction-preview-iq4_nl-imat.gguf` (4.79 GB, IQ4_NL 量化) |
| 上游源 (备用) | `D:\AI\models\main\JoyAI-VL-Interaction-Preview-src\` (16.3 GB, 4 safetensors) |
| mmproj | `D:\AI\models\main\mmproj\mmproj-joyai-vl-interaction-preview-f16.gguf` (1.16 GB, F16) |
| llama.cpp | `D:\AI\bin\llama.cpp\llama-server.exe` (b9330, Clang 19.1.5) |

性能（IQ4_NL + mmproj, ctx 4096, ngl 999）：

| 指标 | 值 |
|---|---|
| Prompt eval (32 tok) | 170 tok/s |
| Generation | 83 tok/s |
| 加载时间 | ~5s 监听 |
| 显存 (model+mmproj+KV) | ~5.4 GB / 16 GB |

## 故障排除

### STATUS_DLL_NOT_FOUND (-1073741515)
缺 `nvrtc64_120_0.dll` / `cudart64_12.dll` / `libssl-4-x64.dll` / `libcrypto-4-x64.dll`：

```powershell
# 装 nvrtc (阿里 pip)
& D:\AI\envs\joyai-main\python.exe -m pip install nvidia-cuda-nvrtc-cu12==12.4.127 --index-url https://mirrors.aliyun.com/pypi/simple/

# 复制到 llama.cpp
Copy-Item D:\AI\envs\joyai-main\Lib\site-packages\nvidia\cuda_nvrtc\bin\nvrtc64_120_0.dll D:\AI\bin\llama.cpp\
Copy-Item D:\AI\envs\joyai-main\Lib\site-packages\nvidia\cuda_nvrtc\bin\nvrtc-builtins64_124.dll D:\AI\bin\llama.cpp\
Copy-Item D:\AI\envs\joyai-main\Lib\site-packages\nvidia\cuda_runtime\bin\cudart64_12.dll D:\AI\bin\llama.cpp\

# 装 openssl 4 (临时环境, 然后复制 DLL)
& D:\anaconda3\Scripts\conda.exe create -p D:\AI\envs\_tmp_openssl4 -y -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge openssl=4.0.1
Copy-Item D:\AI\envs\_tmp_openssl4\Library\bin\libcrypto-4-x64.dll D:\AI\bin\llama.cpp\
Copy-Item D:\AI\envs\_tmp_openssl4\Library\bin\libssl-4-x64.dll D:\AI\bin\llama.cpp\
Remove-Item -Recurse -Force D:\AI\envs\_tmp_openssl4
```

### 启动后 5s 内 STATUS_INVALID_DEVICE_OBJECT_PARAMETER 崩溃
sm_120 + IQ4_NL + 老 build 冲突。**用 b9330+**（见上文）。`-fit off` 必加。

### 模型加载超慢
第一次 mmap 需 ~5s。后续启动 5s 内 listen。

### `--jinja` chat template 异常
确认模型有 chat template（`joyai-vl-interaction-preview` 内置 `<|im_start|>` 格式）。
