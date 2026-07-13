#requires -Version 5.1
<#
.SYNOPSIS
  Start llama.cpp server (JoyAI-VL-Interaction) on Windows in background.

.DESCRIPTION
  - Uses D:\AI\bin\llama.cpp (b9330 CUDA 13.1 sm_120 build)
  - Loads IQ4_NL GGUF + F16 mmproj
  - Writes PID file to .pids/ and timestamped log to logs/
  - Defaults: port 7060, ctx 4096, ngl 999
  - -NoMmproj to run text-only LLM (smaller memory)

.EXAMPLE
  .\start-llama-server.ps1                      # multimodal, port 7060
  .\start-llama-server.ps1 -Port 8080 -CtxSize 8192
  .\start-llama-server.ps1 -NoMmproj            # text only, faster
  .\start-llama-server.ps1 -Status              # just check status
  .\start-llama-server.ps1 -Stop                # stop running server
#>
param(
    [string]$ModelPath  = "D:\AI\models\main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\joyai-vl-interaction-preview-iq4_nl-imat.gguf",
    [string]$MmprojPath = "D:\AI\models\main\mmproj\mmproj-joyai-vl-interaction-preview-f16.gguf",
    [int]$Port          = 7060,
    [int]$CtxSize       = 16384,  # v3.34: 4096 -> 16384 to match MAIN_CONTEXT + webinfer prompt guard
    [int]$Ngl           = 999,
    [string]$BindHost       = "127.0.0.1",
    [switch]$NoMmproj,
    [switch]$Status,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$llamaCpp = "D:\AI\bin\llama.cpp"
$serverExe = Join-Path $llamaCpp "llama-server.exe"
$pidDir = Join-Path $repoRoot ".pids"
$logDir = Join-Path $repoRoot "logs"
$pidFile = Join-Path $pidDir "llama-server.pid"
New-Item -ItemType Directory -Path $pidDir, $logDir -Force | Out-Null

function Write-Status {
    if (Test-Path $pidFile) {
        $procId = Get-Content $pidFile -ErrorAction SilentlyContinue
        $p = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($p) { Write-Host ("[OK] llama-server PID={0}, RSS={1} MB" -f $pid, [math]::Round($p.WorkingSet64/1MB,0)) }
        else { Write-Host "[DEAD] pid $pid not alive" }
    } else { Write-Host "[NO PID file]" }
    $port = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($port) { Write-Host "[OK] listening on :$Port" } else { Write-Host "[NO] :$Port not listening" }
}

if ($Status) { Write-Status; return }

if ($Stop) {
    if (Test-Path $pidFile) {
        $procId = Get-Content $pidFile -ErrorAction SilentlyContinue
        $p = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($p) { Stop-Process -Id $pid -Force; Write-Host "[STOPPED] PID=$pid" }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | Stop-Process -Force
    return
}

if (-not (Test-Path $serverExe)) { throw "llama-server.exe not found at $serverExe. Run install-windows.ps1 first." }
if (-not (Test-Path $ModelPath)) { throw "Model not found: $ModelPath" }
if (-not $NoMmproj -and -not (Test-Path $MmprojPath)) { throw "mmproj not found: $MmprojPath (use -NoMmproj to skip)" }

Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

$env:PATH = "$llamaCpp;$env:PATH"
$logFile = Join-Path $logDir ("llama-server-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

$args = @("-m", $ModelPath, "-c", "$CtxSize", "-ngl", "$Ngl", "--port", "$Port", "--host", $BindHost, "-fit", "off", "--jinja")
if (-not $NoMmproj) { $args += @("--mmproj", $MmprojPath) }

Write-Host "=== llama-server (b9330, sm_120) ===" -ForegroundColor Cyan
Write-Host "  model:  $ModelPath"
if (-not $NoMmproj) { Write-Host "  mmproj: $MmprojPath" }
Write-Host "  port:   $Port   ctx: $CtxSize   ngl: $Ngl"
Write-Host "  log:    $logFile"

$proc = Start-Process -FilePath $serverExe -ArgumentList $args -WorkingDirectory $llamaCpp -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err" -WindowStyle Hidden -PassThru
Set-Content -Path $pidFile -Value $proc.Id

$ok = $false
for ($i=0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $pp = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($pp) { $ok = $true; break }
    $proc2 = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if (-not $proc2 -or $proc2.HasExited) { Write-Host "[FAIL] exit=$($proc2.ExitCode). Check $logFile.err" -ForegroundColor Red; return }
}
if ($ok) {
    Write-Host "[OK] listening on http://$BindHost`:$Port (PID=$($proc.Id))" -ForegroundColor Green
} else {
    Write-Host "[TIMEOUT] not listening after 30s. Check $logFile.err" -ForegroundColor Yellow
}


