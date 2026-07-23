# ADR 0004 — 服务停止方案（让用户不再用任务管理器）

- **状态**：Accepted
- **日期**：2026-07-11
- **作者**：Codex

## 背景

用户原话："你启动的服务，我都不知道怎么关闭，我只能 kill，或者在任务管理器那里结束任务，很麻烦给方案。"

## 现有方案

仓库已经有 `stop-joyai.ps1`（根目录），可以一键干掉以下所有进程：

| 服务 | 端口 |
| - | - |
| llama-main | 7060 |
| llama-summary | 8065 |
| webinfer | 8070 |
| background-agent | 8079 |
| webui | 8099 |
| hermes-gateway | 8642 |
| voice-clone | 8985 |
| cosyvoice | 8991 |
| tts-adapter | 8992 |
| whisper | 8993 |
| asr-adapter | 8994 |
| webui-8090 | 8090 |

脚本机制：
1. PID 文件（`services/.pids/*.pid`）+ 端口监听（`Get-NetTCPConnection`）双管齐下
2. 即使你用 `Start-Process -WindowStyle Hidden` 起 PID 文件丢失的进程，端口探测也能抓到
3. `-DryRun` / `-Only <port>` 两个开关

**问题是用户不知道有**。

## 决策

执行 4 件事让"停止服务"不再需要任务管理器：

### A. `stop-joyai.ps1` 顶部 README 显眼引导

```powershell
# 默认杀全部 12 个服务
powershell -ExecutionPolicy Bypass -File stop-joyai.ps1

# 仅杀疯掉的那个
powershell -ExecutionPolicy Bypass -File stop-joyai.ps1 -Only 8985

# 不真杀，先列出
powershell -ExecutionPolicy Bypass -File stop-joyai.ps1 -DryRun
```

### B. `start-joyai.ps1` 加 `-Stop` 转发

```powershell
powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Stop
```

### C. 文档回写

- `doc/subsystems/jarvis-mode.md` §14.2 已经在，文档够；
- `README.md` / `README.zh-CN.md` 顶部加 "How to stop everything" 章节
- `start-joyai.ps1 -Stop` 的等价命令写到两个 README

### D. 把 KWS / voice-clone 服务加到 stop-joyai 端口清单

当前 stop-joyai 已经覆盖全部 12 个端口（ADR 不需要新代码），但确认下没有遗漏。

## 不做的事

- ❌ 不做 GUI 终止按钮（webui 里加按钮，要求服务全活时才点得动，反而更复杂）
- ❌ 不做 systemd / Windows Service（一次性脚本足够）

## 测试

`test_stop_joyai_dryrun.ps1`：跑 `stop-joyai.ps1 -DryRun`，**不杀任何进程**，但列出当前所有监听。验证脚本在不真杀情况下能看到活的端口。

## 后果

- 用户在任务管理器杀进程的经历消失
- 任何一次启动脚本启动的服务都有对应的"-Stop"或单独 `stop-joyai.ps1`
- 兼容性：start-joyai.ps1 是 thin wrapper，向下兼容（只加新参数）
## 2026-07-12 实施修订

- 当前默认/voice/gaming 启动计划只启动 `llama-main:7060`、`webinfer:8070`、`webui:8099`、`voice-clone:8985`。
- KWS/Paraformer ASR 在 WebUI 进程内运行；TTS 直接调用 MiniMax voice-clone API，不启动 `8991/8992/8993/8994`。
- `stop-joyai.ps1` 继续保留历史端口表，只用于清理旧进程，不代表这些服务会被启动。
- `run-windows.ps1 -DryRun` 在打印计划后立即返回，禁止启动或停止任何进程。
- WebUI 默认使用 `http://127.0.0.1:8099/`；本机 localhost 满足浏览器安全上下文要求。

验证命令：

```powershell
powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Mode default -DryRun
powershell -ExecutionPolicy Bypass -File stop-joyai.ps1 -DryRun
