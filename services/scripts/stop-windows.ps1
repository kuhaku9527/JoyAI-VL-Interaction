#requires -Version 5.1
<#
.SYNOPSIS
  Stop every JoyAI-VL-Interaction service started by run-windows.ps1.

.DESCRIPTION
  Two passes:
    1. Read every services\.pids\*.pid and Stop-Process that PID.
    2. Fall back: for every managed port, kill any process in LISTEN state.

  Idempotent. Safe to run when nothing is up.

  Usage:
    powershell -ExecutionPolicy Bypass -File services\scripts\stop-windows.ps1
    powershell -ExecutionPolicy Bypass -File services\scripts\stop-windows.ps1 -Only llama-main,whisper
    powershell -ExecutionPolicy Bypass -File services\scripts\stop-windows.ps1 -AllPorts
#>

[CmdletBinding()]
param(
    [string[]]$Only = @(),
    [switch]$AllPorts = $true,
    [int]$GraceSeconds = 5,
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
if (-not $RepoRoot) { $RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path }
$ServicesDir = Join-Path $RepoRoot "services"
$PidDir      = Join-Path $ServicesDir ".pids"

function Write-Ok   { param($m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Info { param($m) Write-Host "  [..]   $m" -ForegroundColor DarkGray }
function Write-Warn { param($m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "  [FAIL] $m" -ForegroundColor Red }

# Port map matches run-windows.ps1
$PortMap = [ordered]@{
    "llama-main"        = 7060
    "llama-summary"     = 8065
    "webinfer"          = 8070
    "background-agent"  = 8079
    "webui"             = 8099
    # voice-ui removed 2026-07-12: see jarvis-mode.md v3.4
    "hermes-gateway"    = 8642
    "voice-clone"       = 8985
    "cosyvoice"         = 8991
    "tts-adapter"       = 8992
    "whisper"           = 8993
    "asr-adapter"       = 8994
}

function Test-ProcessAlive {
    param([int]$ProcPid)
    if ($ProcPid -le 0) { return $false }
    return $null -ne (Get-Process -Id $ProcPid -ErrorAction SilentlyContinue)
}

function Stop-One {
    param([string]$Name, [int]$ProcPid, [int]$Grace = $GraceSeconds)
    if (-not (Test-ProcessAlive $ProcPid)) { Write-Info "$Name (PID $ProcPid) not running"; return }
    Write-Host "  Stopping $Name (PID $ProcPid) ..." -ForegroundColor White
    try { Stop-Process -Id $ProcPid -Force -ErrorAction SilentlyContinue } catch {}
    $deadline = (Get-Date).AddSeconds($Grace)
    while ((Get-Date) -lt $deadline -and (Test-ProcessAlive $ProcPid)) {
        Start-Sleep -Milliseconds 200
    }
    if (Test-ProcessAlive $ProcPid) {
        Write-Warn "$Name still alive; force-killing"
        try { Stop-Process -Id $ProcPid -Force -ErrorAction SilentlyContinue } catch {}
    }
}

function Stop-Port {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $p = $c.OwningProcess
        if ($p -and (Test-ProcessAlive $p)) {
            Write-Info "Killing listener on port $Port (PID $p)"
            try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " stop-windows.ps1" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " RepoRoot    : $RepoRoot"
Write-Host " PidsDir     : $PidDir"
Write-Host " Only        : $($Only -join ',')"
Write-Host " AllPorts    : $AllPorts"
Write-Host ""

# ---------------------------------------------------------------------------
# 1) PID-file pass
# ---------------------------------------------------------------------------
$stoppedCount = 0
if (Test-Path $PidDir) {
    $ProcPidFiles = Get-ChildItem $PidDir -Filter "*.pid" -ErrorAction SilentlyContinue
    foreach ($f in $ProcPidFiles) {
        $name = $f.BaseName
        if ($Only -and ($Only -notcontains $name)) { continue }
        $ProcPidV = Get-Content $f.FullName -ErrorAction SilentlyContinue
        if ($ProcPidV -and ($ProcPidV -as [int])) {
            Stop-One -Name $name -Pid ([int]$ProcPidV)
            Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue
            $stoppedCount++
        } else {
            Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue
        }
    }
} else {
    Write-Info "No .pids directory found; skipping PID pass"
}

# ---------------------------------------------------------------------------
# 2) Port-fallback pass
# ---------------------------------------------------------------------------
if ($AllPorts) {
    foreach ($name in $PortMap.Keys) {
        if ($Only -and ($Only -notcontains $name)) { continue }
        $port = $PortMap[$name]
        Stop-Port -Port $port
    }
}

# ---------------------------------------------------------------------------
# Final wait + summary
# ---------------------------------------------------------------------------
Start-Sleep -Seconds 1
$stillUp = @()
foreach ($name in $PortMap.Keys) {
    if ($Only -and ($Only -notcontains $name)) { continue }
    $port = $PortMap[$name]
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { $stillUp += $name }
}

Write-Host ""
if ($stillUp.Count -gt 0) {
    Write-Warn "Still listening: $($stillUp -join ', '). You may need to close the owning processes manually."
} else {
    Write-Ok "All managed services stopped."
}
Write-Host ""