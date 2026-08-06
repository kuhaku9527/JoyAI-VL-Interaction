# 运行时矩阵 (Runtime Matrix)

本文件钉死各服务运行时 python,避免启动脚本引用不存在的 `services/.venv` 导致跑空。`webui` 依用户 2026-08-07 指令隔离到 `D:\AI\envs\joyai-webui`;其余服务沿用 install-windows.ps1 的 `services/.venv` 共享运行时(可用 `JOYAI_VENV_PY` 覆盖单个服务)。

## 各组件运行时 python

| 组件 | 运行时 python | 来源/依据 | 备注 |
| --- | --- | --- | --- |
| webui(FastAPI 服务) | 隔离环境 `D:\AI\envs\joyai-webui`(conda,py3.12) | 本任务新建;用户 2026-08-07 指令「webui 隔离放 D:\AI\envs」 | 钉死方式:启动前设 `$env:JOYAI_VENV_PY = "D:\AI\envs\joyai-webui\python.exe"` |
| webinfer / asr / tts / voice-clone / background-agent(5 个服务) | `services\.venv`(Python 3.12) | `install/install-windows.ps1:320` 的 editable 列表(脚本注释写「5 个」但实列 6 项,见下) | 由 install-windows.ps1 一次性 editable 安装;可用 `JOYAI_VENV_PY` 覆盖单个服务 |
| memory-store | `services\.venv`(Python 3.12),经 `Start-MemoryStore`(`run-windows.ps1:563`)以 `$VenvPy` 启动 | `install/install-windows.ps1:320`(已补入 editable 列表,2026-08-07)+ `run-windows.ps1:563-578` | 现已随 install 脚本一并 editable 安装;core 依赖与 services/.venv 兼容(`sentence-transformers` 仅 local-embed 可选 extra,默认不拉) |
| sherpa / KWS / ASR 独立脚本(test_jarvis_state_machine.py、generate_event_audio.py) | `D:\AI\envs\joyai-sherpa\python.exe`(conda) | `install/windows/start-all-services.ps1:132,189,192` | |
| bge-m3 嵌入(memory-store CPU) | `D:\AI\envs\joyai-main`(conda) | 项目 MEMORY.md「venv D:\AI\envs\joyai-main(CPU bge-m3)」;核验:`& "D:\AI\envs\joyai-main\python.exe" -c "import sentence_transformers"` | |
| hermes background-agent(standalone 脚本入口) | `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe` | `services/background-agent/scripts/run-windows.ps1:58` | hermes 自带 venv;注意 background-agent **另有**主启动器入口(`run-windows.ps1:438/458`)用 `$VenvPy`(services/.venv) |
| cosyvoice | conda `$condaRoot/envs/$EnvName`(依赖 conda 基目录) | `install/setup-cosyvoice.ps1:84` | 独立环境,按需建 |

## 钉死要点

- **webui 隔离**:新建的 `D:\AI\envs\joyai-webui`(conda, Python 3.12.13)专用于 webui,与 `services/.venv` 解耦。启动 webui 前必须通过 `JOYAI_VENV_PY` 显式指到它,否则会回退到尚未构建的 `services/.venv` 而跑空。
- **共享运行时**:webinfer / asr / tts / voice-clone / background-agent 五服务共享 `services/.venv`,由 `install/install-windows.ps1:320` 以 editable 方式安装(脚本自身注释写「5 个」但列表实为 6 项,含 background-agent;此计数口径差异不影响钉死)。
- **memory-store 已补入安装列表(2026-08-07)**:`run-windows.ps1` 用 `$VenvPy` 启动 memory-store,此前 `install-windows.ps1:320` 的 editable 列表**漏了**它(已知缺口,本变更已补 `memory-store`)。现随 install 脚本一并 editable 安装;`sentence-transformers`(local-embed 可选 extra)默认不拉,若要用本地 bge-m3 权重需另 `pip install -e "services/memory-store[local-embed]"`。
- **background-agent 双入口**:主启动器(`run-windows.ps1:438/458`)用 `$VenvPy`(services/.venv);其 standalone 脚本(`services/background-agent/scripts/run-windows.ps1:58`)用 hermes 自带 venv。两者解释器不同,勿混用。
- **`JOYAI_VENV_PY` 覆盖优先级**:单个服务可用该环境变量覆盖默认 python 解释器(webui 即借此指向隔离环境)。
- **独立脚本**:sherpa/KWS/ASR 的离线脚本直接调用 `D:\AI\envs\joyai-sherpa\python.exe`,不进 `services/.venv`。
- **bge-m3 嵌入**在 `D:\AI\envs\joyai-main`(CPU)中运行,与 memory-store 服务进程同机但不同解释器。
- **hermes / cosyvoice** 各自维护独立 venv/conda 环境,不纳入本仓库的 `services/.venv`。

## 命令示例

```powershell
# 1) webui —— 钉死到隔离 conda 环境
$env:JOYAI_VENV_PY = "D:\AI\envs\joyai-webui\python.exe"
#   完整依赖(真实跑 webui 服务时,用户侧需装):
#   & "D:\AI\envs\joyai-webui\python.exe" -m pip install -e services/webui
#   本任务仅验证了 smart-turn 推理,装的是轻量依赖:
#   onnxruntime transformers numpy pytest(未装 torch)。

# 2) 其余 5 个服务 —— 共享 services/.venv(先构建)
#   & "D:\anaconda3\Scripts\conda.exe" create -p .\services\.venv python=3.12 -y
#   & ".\services\.venv\Scripts\python.exe" -m pip install -e services/webinfer -e services/asr -e services/tts -e services/voice-clone -e services/background-agent

# 2b) memory-store —— 现已包含在上面的安装列表(install-windows.ps1:320 已补),
#     如需本地 bge-m3 权重再装可选 extra:
#   & ".\services\.venv\Scripts\python.exe" -m pip install -e "services/memory-store[local-embed]"

# 3) sherpa/KWS/ASR 独立脚本
#   & "D:\AI\envs\joyai-sherpa\python.exe" services\scripts\test_jarvis_state_machine.py
#   & "D:\AI\envs\joyai-sherpa\python.exe" services\scripts\generate_event_audio.py --voice-id bt-7274

# 4) hermes background-agent —— 自带 venv
#   & "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" services\background-agent\run.py

# 5) cosyvoice —— 独立 conda 环境(setup-cosyvoice.ps1 内部按 $condaRoot/envs/$EnvName 解析)
#   .\install\setup-cosyvoice.ps1
```

## 验证记录(本任务)

- 环境:`D:\AI\envs\joyai-webui`(conda, Python 3.12.13),位于 `D:\AI\envs` 与其余 conda 环境并列。
- 轻量依赖:`onnxruntime 1.28.0` / `transformers 5.14.1` / `numpy 2.5.1` / `pytest 9.1.1`;**未装 torch**(`import torch` → ModuleNotFoundError)。
- smart-turn 真实推理:模型 `D:/AI/models/smart-turn/smart-turn-v3.2-cpu.onnx` 加载成功,`adapter.available == True`;合成 16kHz 音频经 Whisper log-mel → ONNX 输出 `prob=0.9574`(∈[0,1],非 fail-open 的 0.0)。
- pytest:`services/webui/tests/test_smart_turn.py` → **2 passed, 1 skipped**(skip 为「模型缺失时 fail-open」用例,因资产已就位而按仓库约定 auto-skip)。
