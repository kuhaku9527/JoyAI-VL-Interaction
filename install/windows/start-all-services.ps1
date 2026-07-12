#requires -Version 5.1
<#
.SYNOPSIS
  Start all JoyAI-VL-Interaction services required for Jarvis mode.

.DESCRIPTION
  Orchestrator that brings up:
    1. llama-server (LLM, port 7060)
    2. voice_clone_api (TTS shim, port 8985)

  Uses existing per-service scripts when present; otherwise invokes the
  underlying binaries directly. Each service gets its own timestamped log
  under logs/ and a PID under .pids/ so this script can be re-run safely.

.PARAMETER Stop
  Stop every service this script started (matches the PID files we wrote).

.PARAMETER Status
  Print a short status report for each service without starting anything.

.EXAMPLE
  .\start-all-services.ps1
  .\start-all-services.ps1 -Status
  .\start-all-services.ps1 -Stop
#>
param(
    [switch]$Stop,
    [switch]$Status,
    [int]$LlamaPort = 7060
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$llamaScript = Join-Path $PSScriptRoot "start-llama-server.ps1"

$logDir = Join-Path $repoRoot "logs"
$pidDir = Join-Path $repoRoot ".pids"
New-Item -ItemType Directory -Path $logDir, $pidDir -Force | Out-Null

$services = @(
    @{ Name = "llama-server";     Port = $LlamaPort },
    @{ Name = "voice_clone_api";  Port = 8985 },
    @{ Name = "webui-server";     Port = 8090 }
)

function Get-ServicePidFile($name) { Join-Path $pidDir "$name.pid" }
function Get-ServiceLogFile($name) {
    Join-Path $logDir ($name + "-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
}

function Write-StatusLine($svc) {
    $pidFile = Get-ServicePidFile $svc.Name
    $port    = $svc.Port
    $portOpen = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) -ne $null
    $pidLive  = $false
    $procPid = $null
    if (Test-Path $pidFile) {
        $procPid = Get-Content $pidFile -ErrorAction SilentlyContinue
        $pidLive = $procPid -and (Get-Process -Id $procPid -ErrorAction SilentlyContinue) -ne $null
    }
    $mark = if ($portOpen -and $pidLive) { "[OK]  " } elseif ($portOpen) { "[WARN]" } else { "[STOP]" }
    $info = if ($procPid) { "PID=$procPid" } else { "no pid" }
    $portInfo = if ($portOpen) { "port $port listening" } else { "port $port idle" }
    Write-Host ("{0} {1,-18} {2,-22} {3}" -f $mark, $svc.Name, $info, $portInfo)
}

function Stop-Service($svc) {
    $pidFile = Get-ServicePidFile $svc.Name
    if (Test-Path $pidFile) {
        $procPid = Get-Content $pidFile -ErrorAction SilentlyContinue
        if ($procPid -and (Get-Process -Id $procPid -ErrorAction SilentlyContinue)) {
            Stop-Process -Id $procPid -Force
            Write-Host "[STOP] $($svc.Name) (PID=$procPid)"
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    # Extra: kill any leftover python.exe that we started for voice_clone_api
    if ($svc.Name -eq "voice_clone_api") {
        Get-Process -Name "python" -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowTitle -eq "" -and $_.StartTime -gt (Get-Date).AddMinutes(-30) } |
            ForEach-Object {
                $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
                if ($cmd -and $cmd -match "voice_clone_api\.main:app") {
                    Stop-Process -Id $_.Id -Force
                    Write-Host "[STOP] voice_clone_api (PID=$($_.Id))"
                }
            }
    }
}

if ($Status) {
    Write-Host "=== Service status ===" -ForegroundColor Cyan
    foreach ($svc in $services) { Write-StatusLine $svc }
    return
}

if ($Stop) {
    Write-Host "=== Stopping all services ===" -ForegroundColor Cyan
    foreach ($svc in $services) { Stop-Service $svc }
    return
}

# === 1) llama-server (port $LlamaPort) ===
Write-Host ""
Write-Host "=== 1) llama-server (port $LlamaPort) ===" -ForegroundColor Cyan
if (Test-Path $llamaScript) {
    & $llamaScript -Port $LlamaPort
} else {
    throw "Missing $llamaScript — install-windows.ps1 should have created it."
}

# === 2) voice_clone_api (port 8985) ===
Write-Host ""
Write-Host "=== 2) voice_clone_api (port 8985) ===" -ForegroundColor Cyan
$vcPidFile = Get-ServicePidFile "voice_clone_api"
$vcLogFile = Get-ServiceLogFile "voice_clone_api"

# Refuse to start twice
if (Test-Path $vcPidFile) {
    $existing = Get-Content $vcPidFile -ErrorAction SilentlyContinue
    if ($existing -and (Get-Process -Id $existing -ErrorAction SilentlyContinue)) {
        Write-Host "voice_clone_api already running (PID $existing)."
    } else {
        Remove-Item $vcPidFile -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $vcPidFile)) {
    # Prefer the joyai-sherpa env (has sherpa_onnx, numpy, httpx, uvicorn, fastapi).
    # Other envs work too as long as uvicorn + fastapi + python-multipart are installed.
    $pythonExe = "D:\AI\envs\joyai-sherpa\python.exe"
    if (-not (Test-Path $pythonExe)) {
        $pythonExe = (Get-Command "python" -ErrorAction SilentlyContinue).Source
    }
    if (-not $pythonExe) { throw "No Python interpreter found. Set up joyai-sherpa env first." }

    $vcDir = Join-Path $repoRoot "services\voice-clone"
    $env:PYTHONPATH      = $vcDir
    $env:VOICE_CLONE_HOST = "127.0.0.1"
    $env:VOICE_CLONE_PORT = "8985"
    $env:COSYVOICE_URL   = "http://127.0.0.1:8991"
    $env:VOICES_DIR      = Join-Path $vcDir "voices"

    Write-Host "  python:    $pythonExe"
    Write-Host "  log:       $vcLogFile"
    Write-Host "  voices:    $env:VOICES_DIR"

    $proc = Start-Process -FilePath $pythonExe `
        -ArgumentList @("-m", "uvicorn", "voice_clone_api.main:app", "--host", "127.0.0.1", "--port", "8985", "--no-access-log") `
        -WorkingDirectory $vcDir `
        -RedirectStandardOutput $vcLogFile `
        -RedirectStandardError "$vcLogFile.err" `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $vcPidFile -Value $proc.Id
    Write-Host "voice_clone_api PID: $($proc.Id)"

    # Wait for /health
    $ok = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8985/health" -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -eq 200) { $ok = $true; break }
        } catch { }
        $p2 = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
        if (-not $p2 -or $p2.HasExited) { break }
    }
    if ($ok) {
        Write-Host "[OK] voice_clone_api listening on http://127.0.0.1:8985" -ForegroundColor Green
    } else {
        Write-Host "[TIMEOUT] voice_clone_api did not respond on /health within 30s. Check $vcLogFile.err" -ForegroundColor Yellow
    }
}

# === Final status ===
Write-Host ""
Write-Host "=== Final status ===" -ForegroundColor Cyan
foreach ($svc in $services) { Write-StatusLine $svc }

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  # Quick API smoke test:"
Write-Host "  curl http://127.0.0.1:8090/api/jarvis/status?session_id=demo"
Write-Host "  curl -X POST http://127.0.0.1:8090/api/jarvis/force_state -H \"Content-Type: application/json\" -d '{\"session_id\":\"demo\",\"state\":\"DIALOG_ACTIVE\"}'
Write-Host ""
Write-Host "  # Or run the standalone D3 state machine end-to-end test:"
Write-Host "  & D:\AI\envs\joyai-sherpa\python.exe services\scripts\test_jarvis_state_machine.py"
Write-Host ""
Write-Host "  # Generate wake.wav / goodbye.wav (requires MiniMax plan active)"
Write-Host "  & D:\AI\envs\joyai-sherpa\python.exe services\scripts\generate_event_audio.py --voice-id bt-7274"