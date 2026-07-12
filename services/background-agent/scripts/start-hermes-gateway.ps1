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
    HERMES_API_KEY / API_SERVER_KEY  (auto-read from ``$env:LOCALAPPDATA\hermes\.env``)

  Optional:
    API_SERVER_CORS_ORIGINS (default http://127.0.0.1:8079, the shim port)
#>

[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..\..").Path,
    [string]$HermesHome = $env:HERMES_HOME,
    [switch]$NoProbe
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Locate hermes CLI. The official PowerShell installer drops it in
# $env:LOCALAPPDATA\hermes\bin\hermes.cmd; honour that first, then fall back
# to whatever is on PATH.
# ---------------------------------------------------------------------------
$candidate = @(
    (Join-Path $env:LOCALAPPDATA "hermes\bin\hermes.cmd")
    (Get-Command "hermes.cmd" -ErrorAction SilentlyContinue)?.Source
    (Get-Command "hermes" -ErrorAction SilentlyContinue)?.Source
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

# Try to load the API key from the canonical hermes dotenv if the caller
# did not provide one.
if (-not $env:API_SERVER_KEY -and -not $env:HERMES_API_KEY) {
    $hermesEnvPath = Join-Path $env:LOCALAPPDATA "hermes\.env"
    if (Test-Path $hermesEnvPath) {
        $apiServerKey = Select-String -Path $hermesEnvPath -Pattern '^API_SERVER_KEY\s*=' -CaseSensitive:$false |
            ForEach-Object { ($_ -split '=', 2)[1].Trim().Trim('"').Trim("'") } |
            Select-Object -First 1
        if ($apiServerKey) { $env:API_SERVER_KEY = $apiServerKey }
    }
}

if (-not $env:API_SERVER_KEY) {
    Write-Warning "API_SERVER_KEY is empty. The hermes gateway will run with auth disabled."
    Write-Warning "Set it in `$env:LOCALAPPDATA\hermes\.env or pass it in via the parent shell."
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
$argList = @("gateway")

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
