# JoyAI-VL-Interaction 服务启动运维手册

> 写给 workbuddy / 任何接手 launcher 的人。
> 涵盖：环境位置、启动指令、env 配置、模型路径、端口（高频失败原因）、启动验证。
> 最后修改：2026-08-04（Codex 写于本会话首轮重启修复之后）。

---

## 1. 环境在哪里

| 用途 | 路径 |
|---|---|
| 仓库根 | `D:\AI\workspace\JoyAI-VL-Interaction-main` |
| Python venv（含 webui / webinfer / memory-store / voice-clone / background-agent）| `D:\AI\envs\joyai-main\python.exe` |
| llama.cpp 二进制 | `D:\AI\bin\llama.cpp\llama-server.exe` |
| 模型根 | `D:\AI\models\` |
| 主 VLM 模型 | `D:\AI\models\main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\joyai-vl-interaction-preview-iq4_nl-imat.gguf` |
| 主 VLM 视觉编码 | `D:\AI\models\main\mmproj\mmproj-joyai-vl-interaction-preview-f16.gguf` |
| Summary 模型（可选）| `D:\AI\models\summary\Qwen2.5-VL-3B-Instruct-GGUF\Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` |
| ASR 模型（可选）| `D:\AI\models\asr\ggml-large-v3-turbo-q5_0.bin` |
| HOME（含 `.workbuddy/`） | `C:\Users\22186\.workbuddy` |
| 启动日志（per-launch）| `services\.logs\<service>.log` + `.err.log` |
| 持久日志（gitignored）| `logs/launcher-<UTC>.log` + `logs/drift-gate-history/<UTC>.json` + `logs/vlm-probes/<UTC>.json` + `logs/vlm-runtime-props.json` + `logs/events/<service>-<UTC>.jsonl`（spec 已批，待实施）|

---

## 2. 启动指令

```powershell
# 完整启动（默认 = main + voice-clone + webinfer + webui + memory-store）
powershell -ExecutionPolicy Bypass -File D:\AI\workspace\JoyAI-VL-Interaction-main\start-joyai.ps1

# 最小启动（main + webinfer + webui；不含 voice/memory-store）
powershell -ExecutionPolicy Bypass -File D:\AI\workspace\JoyAI-VL-Interaction-main\start-joyai.ps1 -Mode minimal

# 单服务重启（不影响其他）
powershell -ExecutionPolicy Bypass -File D:\AI\workspace\JoyAI-VL-Interaction-main\start-joyai.ps1 -Restart llama-main

# 全部停
powershell -ExecutionPolicy Bypass -File D:\AI\workspace\JoyAI-VL-Interaction-main\start-joyai.ps1 -Stop

# 只看 plan（不实际启动）
powershell -ExecutionPolicy Bypass -File D:\AI\workspace\JoyAI-VL-Interaction-main\start-joyai.ps1 -Mode minimal -DryRun
```

启动顺序由 `run-windows.ps1` 写死（不可并行，plan 数组顺序）：`llama-main → webinfer → webui → memory-store → ...`，每个等 `Wait-Http` 200 才进下一个。

启动耗时：llama-server 加载模型 ~30-60s（VLM 模型大），其它服务各 ~5-10s。

---

## 3. `run-windows.env` 是啥、必不必要

**位置**：`services/scripts/run-windows.env`

**加载机制**：`run-windows.ps1:74-87` 自动读此文件，对每行 `KEY=VALUE` 调 `Set-Item Env:<KEY> -Value <VALUE>`。launcher 启动 + launcher 派的子进程都继承这些 env var。

**是否必要**：**必要**。每项都对应一个不读会导致事故的硬约束：

| 缺失后果 | 该项 |
|---|---|
| llama 走 4096 上下文（drift 漂移） | `MAIN_CONTEXT=16384` + `MAIN_CTX_TOKENS=16384` |
| memory-store 走 8996 空壳（webui 代理错） | `JOYAI_MEMORY_STORE_URL=http://127.0.0.1:8997` + `MEMORY_PORT=8997` |
| 找不到 venv | `JOYAI_VENV_PY=D:\AI\envs\joyai-main\python.exe` |
| 找不到 binary / 模型 | `JOYAI_BIN_ROOT=D:\AI\bin` + `JOYAI_MODELS_ROOT=D:\AI\models` |
| memory-store 默认 opt-in 不启 | `JOYAI_ENABLE_MEMORY_STORE=1`（默认开） |

**不要改默认**。要 override 走 launcher 之外的 env var（shell 级 `Set-Item` 在 `$env:`），但 launcher 启动后不会重读，所以**改 run-windows.env 必须重启 launcher**。

---

## 4. `joyai-main` venv 坏了吗？

**位置**：`D:\AI\envs\joyai-main\`（注意 `python.exe` 在 venv **根目录**，不是 `Scripts/python.exe`）

**验证**：
```powershell
& D:\AI\envs\joyai-main\python.exe -c "import sys; print(sys.version)"   # 应 3.12.x
& D:\AI\envs\joyai-main\python.exe -c "import aiohttp, httpx, yaml; print('ok')"  # 主要依赖
```

**损坏迹象**：
- `ModuleNotFoundError: No module named 'xxx'` → 重新 `pip install`
- `ImportError: cannot import name` → 同包版本冲突，重装
- 没 `python.exe` 或文件 0 字节 → venv 损坏，需要 `python -m venv D:\AI\envs\joyai-main` 重建

**修复**（不重建）：
```powershell
& D:\AI\envs\joyai-main\python.exe -m pip install -r services\webui\pyproject.toml
# 或按 service 装：
# services/webui/pyproject.toml.webinfer/memory-store/voice-clone/background-agent
```

---

## 5. 启动前要手设哪些 env

**默认不需要**（`run-windows.env` + `Start-Background` 设的 `[Environment]::SetEnvironmentVariable` 已覆盖）。

**例外**（debug 场景）：

| 场景 | 设 |
|---|---|
| 跳过 memory-store 启 | `$env:JOYAI_ENABLE_MEMORY_STORE = "0"` |
| 走 8996 空壳（不推荐）| `$env:JOYAI_MEMORY_STORE_URL = "http://127.0.0.1:8996"` |
| 单跑某个服务（不走 launcher）| `& D:\AI\envs\joyai-main\python.exe -m joy_interaction_webui.server --no-ssl --port 8099 --api-base http://127.0.0.1:8070/v1` |
| 直跑 llama-server 单跑 | `& D:\AI\bin\llama.cpp\llama-server.exe -m <gguf> --mmproj <mmproj> -c 16384 -ngl 999 --host 127.0.0.1 --port 7060` |

**注意**：`launcher` 通过 `Start-Process` 转发，**子进程继承**当前 PowerShell session 的 env var。所以 launcher 启动**之前** `$env:XXX` 设的值会被子进程继承。

---

## 6. 模型路径 & minimal 必需

### minimal 模式必需

| 路径 | 大小 | 用途 |
|---|---|---|
| `D:\AI\models\main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\joyai-vl-interaction-preview-iq4_nl-imat.gguf` | ~4.5 GB | 主 VLM 语言模型 |
| `D:\AI\models\main\mmproj\mmproj-joyai-vl-interaction-preview-f16.gguf` | ~1.1 GB | VLM 视觉编码 |

### default 模式额外要

| 路径 | 用途 |
|---|---|
| `D:\AI\models\summary\Qwen2.5-VL-3B-Instruct-GGUF\Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` | summarizer |
| `D:\AI\models\asr\ggml-large-v3-turbo-q5_0.bin` | whisper ASR |

**军模型缺失**会报 `[FAIL] main GGUF missing: ...` 然后 abort。

**检查**：
```powershell
Test-Path 'D:\AI\models\main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\joyai-vl-interaction-preview-iq4_nl-imat.gguf'
Test-Path 'D:\AI\models\main\mmproj\mmproj-joyai-vl-interaction-preview-f16.gguf'
Test-Path 'D:\AI\bin\llama.cpp\llama-server.exe'
```

---

## 7. 端口（高频失败原因）

> **80% 的"跑不起来" = 端口被占**。launcher 会在 `Wait-Http` 失败 900 秒后 abort。

### default 模式必占

| 端口 | 服务 | 备注 |
|---|---|---|
| 7060 | llama-main | VLM |
| 8070 | webinfer | 推理网关 |
| 8099 | webui | 前端 |
| 8642 | hermes-gateway | 多 agent |
| 8985 | voice-clone | TTS |
| 8997 | memory-store | **真后端**，D-L4-001 端口铁律 |
| 8991 | cosyvoice | TTS 后端 |
| 8992 | tts-adapter | |
| 8993 | asr-model | whisper |
| 8994 | asr-adapter | |
| 8079 | background-agent | |

### minimal 模式必占

`7060` / `8070` / `8099` / `8997`（4 个）

### 千万别用

`8996` — 废弃空壳，D-L4-001 锁死 8997

### 预检命令

```powershell
Get-NetTCPConnection -State Listen |
    Where-Object { $_.LocalPort -in 7060, 8070, 8099, 8997, 8985, 8642 } |
    Select-Object LocalPort, OwningProcess
```

### 端口被占怎么办

```powershell
# 1. 看是什么进程
Get-Process -Id <PID>

# 2. 是 launcher 残留（之前没退干净）
powershell -ExecutionPolicy Bypass -File D:\AI\workspace\JoyAI-VL-Interaction-main\start-joyai.ps1 -Stop
# 或精确停某个：
powershell -ExecutionPolicy Bypass -File D:\AI\workspace\JoyAI-VL-Interaction-main\stop-joyai.ps1 -Only 7060

# 3. 是别的程序（早期测试的 python -m http.server、IDE debugger 等）
Stop-Process -Id <PID> -Force
```

**千万别 `Stop-Process -Name python -Force`** —— 会把 launcher 自己的子进程也杀掉。

---

## 8. 怎么确认"真起来了"

**按信号强弱排序**：

```powershell
# === A. 信号最弱：launcher banner（启动时打） ===
# 看 logs/launcher-<UTC>.log 末尾有没有 "All services ready"
$log = Get-ChildItem 'logs\launcher-*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content $log.FullName | Select-Object -Last 20

# === B. 进程全在 ===
Get-Process -Name python, llama-server |
    Where-Object { $_.MainWindowTitle -eq '' } |  # launcher 子进程无窗口
    Select-Object Id, ProcessName, StartTime

# === C. 端口在 listen（信号居中）===
Get-NetTCPConnection -State Listen |
    Where-Object { $_.LocalPort -in 7060, 8070, 8099, 8997 } |
    Select-Object LocalPort

# === D. 服务级 health 端点（信号最强）===
curl http://127.0.0.1:7060/v1/models          # 返回模型列表
curl http://127.0.0.1:8070/health             # {ok: true, ...}
curl http://127.0.0.1:8099/                  # HTML
curl http://127.0.env.JOYAI_MEMORY_STORE_URL:8997/health  # {ok: true, ...}

# === E. 端到端：probe + drift gate ===
& D:\AI\envs\joyai-main\python.exe scripts\vlm_runtime_probe.py --out logs/vlm-runtime-props.json
# 应输出 "n_ctx=16384"

& D:\AI\envs\joyai-main\python.exe scripts\drift_gate.py --contract config/drift-contract.json --phase all --mode closed
# 应 4/4 [OK] exit 0
```

**任何一个 [FAIL] 都查**：
1. `services\.logs\<service>.err.log`（per-launch stderr）
2. `logs/launcher-<UTC>.log`（完整 PowerShell transcript，含每个起停的 banner）
3. `logs/drift-gate-history/<UTC>.json`（哪项 checks fail）
4. `scripts/drift_gate_smoke_test.py` 6/6 全过

---

## 9. 额外补充（你没问的）

### Q: launcher 慢启动？
- 看 `launcher_at: <UTC>` 和 `ran_at: <UTC>` 之间间隔
- llama-server 加载模型 ~30-60s 是正常的（VLM 大）
- 5 分钟未起来 = 卡死，看 `services\.logs\llama-main.err.log` 确认

### Q: 启动后立刻能 chat 吗？
- 启动完毕后第一次 chat 会有 ~1-3s 延迟（webui 初始化 session、warmup 模型）
- 之后稳定 ~100-500ms latency 含网络
- 慢的看 `services/.logs/webui.log` 找 timing

### Q: memory-store 起来了但 webui 报 502？
- webui 代理 `MEMORY_STORE_URL` 错。10% 是 launcher 没启动 memory-store（默认开启，但是 JOYAI_ENABLE_MEMORY_STORE=0 可关）；90% 是 memory-store 起来了但 webui 还在用旧 env
- 解决：`start-joyai.ps1 -Restart webui`（重启 webui，env 重新加载）

### Q: webui 启动但 8099 端口没监听？
- launcher Wait-Http 失败会 abort 后续
- 查 `services/.logs/webui.err.log`：
  - `ModuleNotFoundError` → venv 缺包
  - `NameError: name 'time' is not defined` → 应该是 webui access log 中间件的 typo（commit `0ddd390` 有修）
  - `Address already in use` → 端口被占

### Q: 怎么清理残留 launcher 进程？
- `start-joyai.ps1 -Stop`（最干净）
- `Get-Process -Name python, llama-server | Where-Object { $_.MainWindowTitle -eq '' } | Stop-Process -Force`（精确）

### Q: HEAP_CORRUPTION 问题（llama b10155 已知 bug）？
- 看 `workbuddy/memory/2026-07-29.md`（DRIFT-005 那次）
- 临时解：升级 llama.cpp b10117+ 或换模型
- 长期：等 llama.cpp 修复

### Q: 启动时 launcher 报 "字符编码错误"？
- 90% 是 `run-windows.ps1` 里有未转义的中文引号
- 用 `git diff` 看最近改动
- 修复后 `start-joyai.ps1 -Restart llama-main` 重启

### Q: 怎么对比两次启动的差异？
- 每次 `start-joyai.ps1 ...` 启动会写一条 `logs/launcher-<UTC>.log`
- `Get-Content 'logs\launcher-2026-08-01T08-*.log'` 看具体那次
- Drift gate 历史 `logs/drift-gate-history/` 看每次漂移检查结果

### Q: 启动后服务会写什么日志？
- per-launch stderr：`services/.logs/<service>.err.log`（最近 commit 修复了 launcher 真正写）
- per-launch stdout：`services/.logs/<service>.log`（含 main 启动信息）
- launcher 完整 PS transcript：`logs/launcher-<UTC>.log`
- drift_gate 每次跑的 JSON：`logs/drift-gate-history/<UTC>.json`
- probe 每次 n_ctx snapshot：`logs/vlm-runtime-props.json`（覆盖）+ `logs/vlm-probes/<UTC>.json`（历史）

### Q: 启动失败后怎么 debug？
1. `Get-ChildItem 'logs\launcher-*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1` 看最近 transcript
2. `Get-Content 'services\.logs\<service>.err.log'` 看服务端错误
3. `python scripts/drift_gate.py --phase static --mode closed` 看契约 4 项是否通过
4. `git status` 看工作树有没有未提交改动（可能破坏 launcher）

### Q: 我能用现有 launcher 启新服务吗？
- 不能直接。新服务需要：
  1. `services/scripts/run-windows.ps1` 加 `Start-Xxx` 函数
  2. `Plan-For` 加 `xxx` → `true`
  3. `services/scripts/run-windows.env` 加 env 配置
  4. `.github/workflows/quality.yml` + `config/drift-contract.json`（如需契约）
- 决策书：`决策/README.md` §1 模板

---

## 10. 当启动有 bug 时给我反馈

最高效的格式：
```
[时间] [Mode] [症状]
[相关日志文件路径]
[怀疑点（如果你有）]
```

我会比"跑不起来"快 10 倍找到问题。
