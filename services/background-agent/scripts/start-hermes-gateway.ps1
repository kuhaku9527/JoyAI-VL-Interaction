<#
.SYNOPSIS
  Start a local NousResearch hermes-agent HTTP gateway (default port 8642).

.DESCRIPTION
  Writes the gateway's PID to ``hermes_gateway.pid`` next to this script, waits
  ~3 seconds, and probes ``GET /health`` to confirm the service is live.

  Required environment inputs (loaded from ``background-agent.env`` if present,
  else the parent shell):
    HERMES_GATEWAY_HOST    (default 127.0.0.1)
    HERMES_GATEWAY_PORT    (default 8642)
    HERMES_API_KEY / API_SERVER_KEY  (auto-read from ``D:\Workspace\hermes-data\.env``)

  Canonical hermes home is ``D:\Workspace\hermes-data`` (NOT ``$env:LOCALAPPDATA\hermes``
  nor ``~/.hermes`` — a prior agent rewrote the launcher and pointed HERMES_HOME at a
  stale path, corrupting the env; this script pins HERMES_HOME back to the canonical dir).

  Optional:
    API_SERVER_CORS_ORIGINS (default http://127.0.0.1:8079, the shim port)
#>

[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..\..").Path,
    [string]$HermesHome = "D:\Workspace\hermes-data",
    [switch]$NoProbe
)

$ErrorActionPreference = "Stop"

# Pin the canonical hermes home. A prior agent rewrote the launcher and set
# HERMES_HOME to the stale ``C:\Users\22186\AppData\Local\hermes``; we force the
# project-canonical ``D:\Workspace\hermes-data`` so the gateway uses the right
# config.yaml / .env / state.db.
$env:HERMES_HOME = $HermesHome

# ---------------------------------------------------------------------------
# Locate hermes CLI. Canonical launcher is ``$HermesHome\bin\hermes.cmd``.
# As of 2026-07-23 a read-only audit found only ``.bak``/``.backup`` copies in
# that bin dir (prior-agent corruption), so we fall back to the real CLI exe
# discovered during the audit, then to PATH.
# ---------------------------------------------------------------------------
$candidate = @(
    (Join-Path $HermesHome "bin\hermes.cmd")
    (Join-Path $HermesHome "bin\hermes.exe")
    "D:\Workspace\hermes-agent\venv\Scripts\hermes.exe"
    (Join-Path $HermesHome "gateway-service\Hermes_Gateway.cmd")
    ((Get-Command "hermes.cmd" -ErrorAction SilentlyContinue) | ForEach-Object { $_.Source })
    ((Get-Command "hermes" -ErrorAction SilentlyContinue) | ForEach-Object { $_.Source })
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $candidate) {
    throw "hermes CLI not found. Install via:`n  iex (irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1)"
}

Write-Host "Using hermes CLI: $candidate"

# ---------------------------------------------------------------------------
# Resolve configuration
# ---------------------------------------------------------------------------
$gatewayHost = $env:HERMES_GATEWAY_HOST
if (-not $gatewayHost) { $gatewayHost = "127.0.0.1" }
$gatewayPort = $env:HERMES_GATEWAY_PORT
if (-not $gatewayPort) { $gatewayPort = "8642" }

# Re-use background-agent.env for shared knobs (port, max subagents, etc.)
$envFile = Join-Path $PSScriptRoot "..\background-agent.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $eq = $line.IndexOf("=")
        if ($eq -le 0) { return }
        $name = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
        $existing = Get-Item "env:$name" -ErrorAction SilentlyContinue
        if (-not [string]::IsNullOrEmpty($name) -and $existing -and -not [string]::IsNullOrEmpty($existing.Value)) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

# Ensure API_SERVER_* are set for the gateway child process.
if (-not $env:API_SERVER_ENABLED) { $env:API_SERVER_ENABLED = "true" }
if (-not $env:API_SERVER_CORS_ORIGINS) { $env:API_SERVER_CORS_ORIGINS = "http://127.0.0.1:8079" }
if (-not $env:API_SERVER_HOST) { $env:API_SERVER_HOST = $gatewayHost }
if (-not $env:API_SERVER_PORT) { $env:API_SERVER_PORT = $gatewayPort }

# Load the canonical hermes dotenv (D:\Workspace\hermes-data\.env) wholesale so the
# gateway subprocess inherits all provider keys (MINIMAX_API_KEY, etc.) and any
# API_SERVER_KEY / HERMES_API_KEY if present. The audit found the .env carries
# provider keys but no API_SERVER_KEY, so the gateway runs auth-disabled — that
# matches the shim contract (the shim only sends HERMES_API_KEY when set).
$hermesEnvPath = Join-Path $HermesHome ".env"
if (Test-Path $hermesEnvPath) {
    Get-Content $hermesEnvPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $eq = $line.IndexOf("=")
        if ($eq -le 0) { return }
        $name = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
        $existing = Get-Item "env:$name" -ErrorAction SilentlyContinue
        if (-not [string]::IsNullOrEmpty($name) -and ($existing -and -not [string]::IsNullOrEmpty($existing.Value))) {
            # keep an explicitly-set parent-shell value; otherwise adopt the dotenv value
            return
        }
        if (-not [string]::IsNullOrEmpty($name)) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

if (-not $env:API_SERVER_KEY -and -not $env:HERMES_API_KEY) {
    Write-Warning "API_SERVER_KEY / HERMES_API_KEY is empty. The hermes gateway will run with auth disabled."
    Write-Warning "Set it in $HermesHome\.env or pass it in via the parent shell."
}

# ---------------------------------------------------------------------------
# Launch the gateway detached, capture PID.
# ---------------------------------------------------------------------------
$pidFile = Join-Path $PSScriptRoot "hermes_gateway.pid"
if (Test-Path $pidFile) {
    $existing = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existing -and (Get-Process -Id $existing -ErrorAction SilentlyContinue)) {
        Write-Host "Hermes gateway already running (PID $existing)."
    } else {
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

$logFile = Join-Path $PSScriptRoot "hermes_gateway.log"
# The gateway-service\Hermes_Gateway.cmd is itself the gateway launcher, so it
# takes no "gateway" subcommand; the canonical hermes.cmd / hermes.exe do.
$isGatewayCmd = $candidate -like "*\gateway-service\Hermes_Gateway.cmd"
$argList = if ($isGatewayCmd) { @() } else { @("gateway") }

Write-Host "Starting hermes gateway on ${gatewayHost}:${gatewayPort} (log: $logFile)"
$proc = Start-Process `
    -FilePath $candidate `
    -ArgumentList $argList `
    -WorkingDirectory (Split-Path $candidate -Parent) `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError "$logFile.err" `
    -WindowStyle Hidden `
    -PassThru

Set-Content -Path $pidFile -Value $proc.Id
Write-Host "Hermes gateway PID: $($proc.Id) (pid file: $pidFile)"

# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------
if ($NoProbe) { return }

$healthUrl = "http://${gatewayHost}:${gatewayPort}/health"
Write-Host "Probing $healthUrl ..."
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 3
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
            Write-Host "Hermes gateway is up (HTTP $($resp.StatusCode))."
            return
        }
    } catch {
        # swallow and retry
    }
}
Write-Warning "Hermes gateway did not respond on $healthUrl within 30s. Check $logFile."
