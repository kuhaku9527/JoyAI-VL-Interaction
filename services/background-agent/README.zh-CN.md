# StreamingHarness 后台 Agent Shim

> 原文档: [README.md](README.md)

本包提供两个 FastAPI shim，对 webui 暴露**完全一致**的 `POST /v1/solve` 接口契约：

| shim | 模块 | 运行时 | 适用场景 |
| --- | --- | --- | --- |
| **Hermes API (推荐)** | `hermes_api/main.py` | 本地 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) HTTP gateway（OpenAI 兼容，端口 8642） | Windows 主机；想要现代化 agent + `delegate_task` 子任务编排的用户 |
| **Codex API (旧)** | `codex_api/main.py` | 系统 `codex` CLI 子进程 | 已有的 Linux 部署，依赖原 `codex exec --json` 封装 |

webui 端（`services/webui/src/joy_interaction_webui/background_model.py`）只调
`POST {BACKGROUND_AGENT_API_URL}/v1/solve`，因此切换 shim 只需改变哪个进程占住这个端口。

## 当前跑的是哪一个？

```bash
curl http://127.0.0.1:8079/health
```

- Hermes shim 返回 `{ "codex_api": "ok", "hermes_gateway": <int>, "model": "..." }`
  （保留 `codex_api` 字段名以兼容 webui）。
- Codex shim 返回包含 `codex_cli` 探测结果的 JSON。

---

## Hermes 接入 (Windows 推荐)

Hermes shim 是一个轻量的 OpenAI 格式翻译器，前端对接本地
[hermes-agent](https://github.com/NousResearch/hermes-agent) gateway。
Gateway 负责实际的 agent 循环、工具调用、`delegate_task` 子任务编排，
以及（可选的）图像生成；shim 只把 webui 的 `SolveRequest` 打包成多模态
`chat.completions` 请求，再把响应拆回旧的 `SolveResponse` 形状。

### 1. 安装 hermes-agent

```powershell
# 一行 PowerShell 安装（Windows 原生支持，早期 beta）
iex (irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1)
```

安装后 `hermes` CLI 位于 `$env:LOCALAPPDATA\hermes\bin\hermes.cmd`。

### 2. 登录 / 选模型 provider

```powershell
hermes setup --portal          # 打开 Nous portal 完成登录或配 provider
# 或手动编辑 $env:LOCALAPPDATA\hermes\.env，填入 OPENAI_API_KEY / OPENROUTER_API_KEY / ...
```

### 3. 调 `~/.hermes/config.yaml`

关键配置项：

```yaml
agent:
  max_turns: 30
delegation:
  max_concurrent_children: 6   # 对应 CODEX_API_MAX_SUBAGENTS
```

### 4. 在 `~/.hermes/.env` 启用 HTTP gateway

```dotenv
API_SERVER_ENABLED=true
API_SERVER_KEY=replace-me-with-a-long-random-string
API_SERVER_CORS_ORIGINS=http://127.0.0.1:8079
```

### 5. 自检

```powershell
hermes doctor
```

### 6. 起 gateway（端口 8642）

```powershell
cd services\background-agent
powershell -ExecutionPolicy Bypass -File scripts\start-hermes-gateway.ps1
```

脚本会在同目录写 `hermes_gateway.pid` 和 `hermes_gateway.log`，并对
`GET /health` 做探活。

### 7. 起 shim（端口 8079）

```powershell
cd services\background-agent
powershell -ExecutionPolicy Bypass -File scripts\run-windows.ps1
```

脚本会在同目录写 `hermes_api.pid` 和 `hermes_api.log`，并对 `GET /health`
做探活。

WebUI 默认 `BACKGROUND_AGENT_API_URL=http://127.0.0.1:8079`，**无需任何修改**。

---

## Codex 接入 (旧 / Linux)

```bash
./services/background-agent/scripts/run.sh
```

`run.sh` 优先使用安装脚本创建的共享环境 `services/.venv`。如果该环境
不存在，则回退到 `uv run` 开发模式：

```bash
cd services/background-agent
./scripts/run.sh
```

WebUI 后台客户端默认使用 `http://127.0.0.1:8079`。可通过以下方式覆盖：

```bash
export BACKGROUND_AGENT_API_URL=http://127.0.0.1:8079
```

`run.sh` 默认使用 `<repo>/agent-workspace` 作为 Codex 工作区，并在启动时创建它。

### 安全提示 (Codex 路径)

Codex shim 使用 YOLO 模式
（`--dangerously-bypass-approvals-and-sandbox`），后台任务可以无审批运行，
但请把它视为高权限进程：建议用 Docker 包裹、以隔离用户运行、或仅绑定
localhost。

---

## 环境变量参考

两个 shim 共享同一套环境变量命名空间（Hermes shim 额外多了自己的一组）：

| 变量 | 默认 | 用途 |
| --- | --- | --- |
| `CODEX_API_HOST` | `127.0.0.1` | shim 绑定 host |
| `CODEX_API_PORT` | `8079` | shim 绑定端口（webui 指向这里） |
| `CODEX_API_MAX_SUBAGENTS` | `6` | shim 的子任务上限，会出现在 prompt 中 |
| `CODEX_API_MAX_CONCURRENT_RUNS` | `2` | 进程内 asyncio 信号量 |
| `CODEX_API_TIMEOUT_SECONDS` | `600` | 上游调用超时 |
| `CODEX_API_MAX_FRAMES` | `50` | 帧列表尾部截断 |
| `HERMES_API_URL` | `http://127.0.0.1:8642/v1` | 仅 Hermes shim |
| `HERMES_API_KEY` / `API_SERVER_KEY` | _(空)_ | gateway 的 bearer token |
| `HERMES_MODEL` | `hermes-agent` | chat completion body 中的 model 名 |
| `HERMES_GATEWAY_HOST` / `HERMES_GATEWAY_PORT` | `127.0.0.1` / `8642` | `start-hermes-gateway.ps1` 和 `/health` 用 |

## 健康检查

```bash
curl http://127.0.0.1:8079/health
```
