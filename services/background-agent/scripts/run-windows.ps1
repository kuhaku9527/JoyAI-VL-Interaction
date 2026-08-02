<#
.SYNOPSIS
  Start the StreamingHarness hermes_api shim on Windows (uvicorn under
  hermes-agent venv or whatever Python you point at via $env:PYTHON_EXE).

.DESCRIPTION
  - Listens on the same port the webui already targets (default 8079).
  - Honours CODEX_API_HOST / CODEX_API_PORT / HERMES_API_URL / HERMES_MODEL.
  - Writes PID to ``hermes_api.pid`` and logs to ``hermes_api.log`` next to
    the script, then probes ``GET /health`` once uvicorn has had ~3s to warm.
#>

[CmdletBinding()]
param(
    [string]$PythonExe = $env:PYTHON_EXE,
    [switch]$NoProbe
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$serviceDir = Resolve-Path "$scriptDir\.."
$repoRoot = Resolve-Path "$serviceDir\..\.."

# ---------------------------------------------------------------------------
# Load background-agent.env (shared with run.sh / run-windows.ps1).
# ---------------------------------------------------------------------------
$envFile = Join-Path $serviceDir "background-agent.env"; $envEx = Join-Path $serviceDir "background-agent.env.example"; if (-not (Test-Path $envFile) -and (Test-Path $envEx)) { Write-Host "background-agent.env not found; falling back to template $envEx" -ForegroundColor Yellow; $envFile = $envEx }
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $eq = $line.IndexOf("=")
        if ($eq -le 0) { return }
        $name = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
        if (-not [string]::IsNullOrEmpty($name)) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

# Defaults keep the webui's hard-coded default ``http://127.0.0.1:8079`` working.
if (-not $env:CODEX_API_HOST) { $env:CODEX_API_HOST = "127.0.0.1" }
if (-not $env:CODEX_API_PORT) { $env:CODEX_API_PORT = "8079" }
if (-not $env:HERMES_API_URL) { $env:HERMES_API_URL = "http://127.0.0.1:8642/v1" }
if (-not $env:HERMES_MODEL) { $env:HERMES_MODEL = "hermes-agent" }

# ---------------------------------------------------------------------------
# Locate a usable Python. Prefer the hermes-agent venv, then ``uv`` tool
# resolution, then ``python`` on PATH.
# ---------------------------------------------------------------------------
if (-not $PythonExe) {
    $hermesVenv = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\venv\Scripts\python.exe"
    if (Test-Path $hermesVenv) {
        $PythonExe = $hermesVenv
    } elseif (Get-Command "uv" -ErrorAction SilentlyContinue) {
        $PythonExe = "uv"
    } elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
        $PythonExe = "python"
    } else {
        throw "No Python interpreter found. Set `$env:PYTHON_EXE or install Python 3.12."
    }
}

Write-Host "Using Python: $PythonExe"
Write-Host "  host:        $($env:CODEX_API_HOST)"
Write-Host "  port:        $($env:CODEX_API_PORT)"
Write-Host "  hermes url:  $($env:HERMES_API_URL)"
Write-Host "  hermes mod:  $($env:HERMES_MODEL)"

# Make sure the service dir is on sys.path so uvicorn can import hermes_api.
$env:PYTHONPATH = "$serviceDir$([IO.Path]::PathSeparator)$env:PYTHONPATH"

$pidFile = Join-Path $scriptDir "hermes_api.pid"
$logFile = Join-Path $scriptDir "hermes_api.log"
if (Test-Path $pidFile) {
    $existing = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existing -and (Get-Process -Id $existing -ErrorAction SilentlyContinue)) {
        Write-Host "Hermes API shim already running (PID $existing)."
    } else {
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

$uvicornArgs = @(
    "-m", "uvicorn",
    "hermes_api.main:app",
    "--host", $env:CODEX_API_HOST,
    "--port", $env:CODEX_API_PORT,
    "--no-access-log"  # the request log is noisy; uvicorn's default log level is fine
)

$proc = Start-Process `
    -FilePath $PythonExe `
    -ArgumentList $uvicornArgs `
    -WorkingDirectory $serviceDir `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError "$logFile.err" `
    -WindowStyle Hidden `
    -PassThru `
    -Environment @{ PYTHONPATH = "$serviceDir$([IO.Path]::PathSeparator)$env:PYTHONPATH" }

Set-Content -Path $pidFile -Value $proc.Id
Write-Host "Hermes API shim PID: $($proc.Id) (log: $logFile)"

if ($NoProbe) { return }

$healthUrl = "http://$($env:CODEX_API_HOST):$($env:CODEX_API_PORT)/health"
Write-Host "Probing $healthUrl ..."
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 3
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
            Write-Host "Hermes API shim is up (HTTP $($resp.StatusCode))."
            Write-Host ""
            Write-Host "Try it:"
            Write-Host "  curl $healthUrl"
            return
        }
    } catch {
        # swallow
    }
}
Write-Warning "Hermes API shim did not respond on $healthUrl within 30s. Check $logFile."
