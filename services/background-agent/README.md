# StreamingHarness Background-Agent Shim

> 中文文档: [README.zh-CN.md](README.zh-CN.md)

Two FastAPI shims live in this package, both preserving the exact same
`POST /v1/solve` contract the webui already speaks:

| shim | module | runtime | best for |
| --- | --- | --- | --- |
| **Hermes API (recommended)** | `hermes_api/main.py` | a local [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) HTTP gateway (OpenAI-compatible, port 8642) | Windows hosts and any user who wants the modern agent + delegation toolchain |
| **Codex API (legacy)** | `codex_api/main.py` | a system `codex` CLI subprocess | existing Linux deployments that already depend on the original `codex exec --json` wrapper |

The webui (`services/webui/src/joy_interaction_webui/background_model.py`) only
talks to `POST {BACKGROUND_AGENT_API_URL}/v1/solve`, so flipping between shims
is just a matter of which one is bound to that port.

## Which one is running?

```bash
curl http://127.0.0.1:8079/health
```

- The Hermes shim returns `{ "codex_api": "ok", "hermes_gateway": <int>, "model": "..." }`
  (the `codex_api` key is kept for backward-compatibility).
- The Codex shim returns a JSON object with `codex_cli` and a probe of the
  `codex` binary.

---

## Hermes 接入 (recommended on Windows)

The Hermes shim is a thin OpenAI-format translator that fronts a local
[hermes-agent](https://github.com/NousResearch/hermes-agent) gateway. The
gateway handles the actual agent loop, tool calls, `delegate_task`
sub-orchestration, and (optional) image generation. The shim just packages
the webui's `SolveRequest` into a multimodal `chat.completions` request and
unpacks the response back into the legacy `SolveResponse` shape.

### 1. Install hermes-agent

```powershell
# One-shot PowerShell installer (Windows native, early-beta but functional):
iex (irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1)
```

It drops the `hermes` CLI at `$env:LOCALAPPDATA\hermes\bin\hermes.cmd`.

### 2. Authenticate / pick a model provider

```powershell
hermes setup --portal          # opens the Nous portal for login / provider keys
# or edit $env:LOCALAPPDATA\hermes\.env manually with your OPENAI_API_KEY / OPENROUTER_API_KEY / ...
```

### 3. Tune `~/.hermes/config.yaml`

Key knobs to be aware of:

```yaml
agent:
  max_turns: 30
delegation:
  max_concurrent_children: 6   # mirrors CODEX_API_MAX_SUBAGENTS
```

### 4. Enable the HTTP gateway in `~/.hermes/.env`

```dotenv
API_SERVER_ENABLED=true
API_SERVER_KEY=replace-me-with-a-long-random-string
API_SERVER_CORS_ORIGINS=http://127.0.0.1:8079
```

### 5. Sanity check

```powershell
hermes doctor
```

### 6. Start the gateway (port 8642)

```powershell
cd services\background-agent
powershell -ExecutionPolicy Bypass -File scripts\start-hermes-gateway.ps1
```

This writes `hermes_gateway.pid` and `hermes_gateway.log` next to the script
and probes `GET /health` once the gateway is up.

### 7. Start the shim (port 8079)

```powershell
cd services\background-agent
powershell -ExecutionPolicy Bypass -File scripts\run-windows.ps1
```

This writes `hermes_api.pid` and `hermes_api.log` and probes
`GET /health` once uvicorn is serving.

The webui default `BACKGROUND_AGENT_API_URL=http://127.0.0.1:8079` keeps
working unchanged.

---

## Codex 接入 (legacy / Linux)

```bash
./services/background-agent/scripts/run.sh
```

`run.sh` prefers the shared environment `services/.venv` created by the
install script. If that environment does not exist, it falls back to
`uv run` development mode.

```bash
cd services/background-agent
./scripts/run.sh
```

The WebUI background client uses `http://127.0.0.1:8079` by default.
Override with:

```bash
export BACKGROUND_AGENT_API_URL=http://127.0.0.1:8079
```

`run.sh` uses `<repo>/agent-workspace` as the default Codex workspace and
creates it on startup.

### Security note (Codex path)

The Codex shim uses YOLO mode
(`--dangerously-bypass-approvals-and-sandbox`) so background tasks can run
without interactive approval. Treat it as a high-privilege process: wrap it
in Docker, run as an isolated user, or bind to localhost.

---

## Environment reference

Both shims share the same env-var surface (the Hermes shim reads everything
the Codex shim reads, plus its own prefix):

| variable | default | used by |
| --- | --- | --- |
| `CODEX_API_HOST` | `127.0.0.1` | shim bind host |
| `CODEX_API_PORT` | `8079` | shim bind port (webui targets this) |
| `CODEX_API_MAX_SUBAGENTS` | `6` | shim subagent cap, surfaces in prompt + (Hermes) `delegation.max_concurrent_children` |
| `CODEX_API_MAX_CONCURRENT_RUNS` | `2` | in-process asyncio semaphore |
| `CODEX_API_TIMEOUT_SECONDS` | `600` | upstream call timeout |
| `CODEX_API_MAX_FRAMES` | `50` | tail-truncate frame list |
| `HERMES_API_URL` | `http://127.0.0.1:8642/v1` | Hermes shim only |
| `HERMES_API_KEY` / `API_SERVER_KEY` | _(empty)_ | bearer token for the gateway |
| `HERMES_MODEL` | `hermes-agent` | model name sent in the chat completion body |
| `HERMES_GATEWAY_HOST` / `HERMES_GATEWAY_PORT` | `127.0.0.1` / `8642` | used by `start-hermes-gateway.ps1` and `/health` |

## Health Check

```bash
curl http://127.0.0.1:8079/health
```
