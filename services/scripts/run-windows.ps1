#requires -Version 5.1
<#
.SYNOPSIS
  One-shot orchestrator for the native Windows + RTX 5060 Ti JoyAI-VL-Interaction
  stack.

.DESCRIPTION
  Modes:
    default  ->  main + voice-clone + webinfer + webui (current production path)
    minimal  ->  main + webinfer + webui (smallest end-to-end smoke)
    voice    ->  same as default; KWS/ASR run inside webui via sherpa-onnx
    gaming   ->  default + FORCE_SILENCE_BEFORE_QUERY=false + LOG_LEVEL=WARNING

  Usage:
    powershell -ExecutionPolicy Bypass -File services\scripts\run-windows.ps1
    powershell -ExecutionPolicy Bypass -File services\scripts\run-windows.ps1 -Mode minimal
    powershell -ExecutionPolicy Bypass -File services\scripts\run-windows.ps1 -Restart llama-main
    powershell -ExecutionPolicy Bypass -File services\scripts\run-windows.ps1 -Restart all
    powershell -ExecutionPolicy Bypass -File services\scripts\run-windows.ps1 -Stop

  -Restart <name|all>  kill just that service and re-launch it.
  -Stop                stop everything that this script manages.

  The script is idempotent: it will not start a process that is already
  bound to the expected port. It writes PIDs to <services>\.pids\<name>.pid
  and removes them on clean shutdown (Ctrl+C or -Stop).
#>

[CmdletBinding()]
param(
    [ValidateSet("default","minimal","voice","gaming")]
    [string]$Mode = "default",
    [string]$Restart = "",
    [switch]$Stop,
    [switch]$DryRun,
    [string]$RepoRoot = "",
    [string]$EnvFile  = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "Continue"

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
$ScriptDir = $PSScriptRoot
if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
}
$ServicesDir = Join-Path $RepoRoot "services"
$PidDir      = Join-Path $ServicesDir ".pids"
$LogDir      = Join-Path $ServicesDir ".logs"
if (-not (Test-Path $PidDir)) { New-Item -ItemType Directory -Path $PidDir -Force | Out-Null }
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }


$BinRoot       = if ($env:JOYAI_BIN_ROOT)    { $env:JOYAI_BIN_ROOT }    else { "D:\AI\bin" }
$ModelsRoot    = if ($env:JOYAI_MODELS_ROOT) { $env:JOYAI_MODELS_ROOT } else { "D:\AI\models" }
$ToolsRoot     = if ($env:JOYAI_TOOLS_ROOT)  { $env:JOYAI_TOOLS_ROOT }  else { "D:\AI\tools" }
$LlamaServer   = if ($env:LLAMA_SERVER)   { $env:LLAMA_SERVER }   else { Join-Path $BinRoot "llama.cpp\llama-server.exe" }
$WhisperServer = if ($env:WHISPER_SERVER) { $env:WHISPER_SERVER } else { Join-Path $BinRoot "whisper.cpp\whisper-server.exe" }
$HermesHome    = if ($env:HERMES_HOME)    { $env:HERMES_HOME }    else { Join-Path $env:LOCALAPPDATA "hermes" }
$HermesExe     = if ($env:HERMES_EXE)     { $env:HERMES_EXE }     else { Join-Path $HermesHome "bin\hermes.cmd" }
$VenvPy        = if ($env:JOYAI_VENV_PY)  { $env:JOYAI_VENV_PY }  else { Join-Path $ServicesDir ".venv\Scripts\python.exe" }

$MainGguf       = Join-Path $ModelsRoot "main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\joyai-vl-interaction-preview-iq4_nl-imat.gguf"
$MainMmproj     = Join-Path $ModelsRoot "main\mmproj\mmproj-joyai-vl-interaction-preview-f16.gguf"
$SummaryGguf    = Join-Path $ModelsRoot "summary\Qwen2.5-VL-3B-Instruct-GGUF\Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
$SummaryMmproj  = Join-Path $ModelsRoot "summary\Qwen2.5-VL-3B-Instruct-GGUF\Qwen2.5-VL-3B-Instruct-mmproj-f16.gguf"
$AsrModel       = Join-Path $ModelsRoot "asr\ggml-large-v3-turbo-q5_0.bin"

# run-windows.env
if (-not $EnvFile) { $EnvFile = Join-Path $ScriptDir "run-windows.env" }
if (Test-Path $EnvFile) {
    Write-Host "Loading env: $EnvFile" -ForegroundColor DarkGray
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $eq = $line.IndexOf("=")
        if ($eq -le 0) { return }
        $name  = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
        if ($name) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

$BinRoot       = if ($env:JOYAI_BIN_ROOT)    { $env:JOYAI_BIN_ROOT }    else { "D:\AI\bin" }
$ModelsRoot    = if ($env:JOYAI_MODELS_ROOT) { $env:JOYAI_MODELS_ROOT } else { "D:\AI\models" }
$ToolsRoot     = if ($env:JOYAI_TOOLS_ROOT)  { $env:JOYAI_TOOLS_ROOT }  else { "D:\AI\tools" }
$LlamaServer   = if ($env:LLAMA_SERVER)      { $env:LLAMA_SERVER }      else { Join-Path $BinRoot "llama.cpp\llama-server.exe" }
$WhisperServer = if ($env:WHISPER_SERVER)    { $env:WHISPER_SERVER }    else { Join-Path $BinRoot "whisper.cpp\whisper-server.exe" }
$HermesHome    = if ($env:HERMES_HOME)       { $env:HERMES_HOME }       else { Join-Path $env:LOCALAPPDATA "hermes" }
$HermesExe     = if ($env:HERMES_EXE)        { $env:HERMES_EXE }        else { Join-Path $HermesHome "bin\hermes.cmd" }
$VenvPy        = if ($env:JOYAI_VENV_PY)     { $env:JOYAI_VENV_PY }     else { Join-Path $ServicesDir ".venv\Scripts\python.exe" }

$MainGguf       = Join-Path $ModelsRoot "main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\joyai-vl-interaction-preview-iq4_nl-imat.gguf"
$MainMmproj     = Join-Path $ModelsRoot "main\mmproj\mmproj-joyai-vl-interaction-preview-f16.gguf"
$SummaryGguf    = Join-Path $ModelsRoot "summary\Qwen2.5-VL-3B-Instruct-GGUF\Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
$SummaryMmproj  = Join-Path $ModelsRoot "summary\Qwen2.5-VL-3B-Instruct-GGUF\Qwen2.5-VL-3B-Instruct-mmproj-f16.gguf"
$AsrModel       = Join-Path $ModelsRoot "asr\ggml-large-v3-turbo-q5_0.bin"

$P = @{
    Main        = if ($env:MAIN_MODEL_PORT)       { [int]$env:MAIN_MODEL_PORT }       else { 7060 }
    Summary     = if ($env:SUMMARY_PORT)          { [int]$env:SUMMARY_PORT }          else { 8065 }
    Webinfer    = if ($env:ADAPTER_PORT)          { [int]$env:ADAPTER_PORT }          else { 8070 }
    BgAgent     = if ($env:CODEX_API_PORT)        { [int]$env:CODEX_API_PORT }        else { 8079 }
    Webui       = if ($env:WEBUI_PORT)            { [int]$env:WEBUI_PORT            } else { 8099 }
    Hermes      = if ($env:HERMES_GATEWAY_PORT)   { [int]$env:HERMES_GATEWAY_PORT }   else { 8642 }
    VoiceClone  = if ($env:VOICE_CLONE_PORT)      { [int]$env:VOICE_CLONE_PORT }      else { 8985 }
    AsrModel    = if ($env:ASR_MODEL_PORT)        { [int]$env:ASR_MODEL_PORT }        else { 8993 }
    AsrAdapter  = if ($env:ASR_ADAPTER_PORT)      { [int]$env:ASR_ADAPTER_PORT }      else { 8994 }
    MemoryStore = if ($env:MEMORY_PORT) { [int]$env:MEMORY_PORT } else { 8996 }
}
# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
function Write-Ok   { param($m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Info { param($m) Write-Host "  [..]   $m" -ForegroundColor DarkGray }
function Write-Warn { param($m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Write-Sec  { param($m) Write-Host ""; Write-Host "== $m ==" -ForegroundColor Cyan }

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# ---------------------------------------------------------------------------
# PID helpers
# ---------------------------------------------------------------------------
$PortMap = @{
    "llama-main"        = $P.Main
    "llama-summary"     = $P.Summary
    "whisper"           = $P.AsrModel
    "voice-clone"       = $P.VoiceClone
    "hermes-gateway"    = $P.Hermes
    "background-agent"  = $P.BgAgent
    "webinfer"          = $P.Webinfer
    "asr-adapter"       = $P.AsrAdapter
    "webui"             = $P.Webui
    "memory-store"      = $P.MemoryStore
}

function Save-Pid {
    param([string]$Name, [int]$ProcPid)
    Set-Content -Path (Join-Path $PidDir "$Name.pid") -Value $ProcPid -Encoding ASCII
}

function Get-Pid {
    param([string]$Name)
    $f = Join-Path $PidDir "$Name.pid"
    if (Test-Path $f) {
        $v = Get-Content $f -ErrorAction SilentlyContinue
        if ($v -and ($v -as [int])) { return [int]$v }
    }
    return $null
}

function Remove-Pid {
    param([string]$Name)
    $f = Join-Path $PidDir "$Name.pid"
    if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
}

function Test-Pid-Alive {
    param([int]$ProcPid)
    if ($ProcPid -le 0) { return $false }
    return $null -ne (Get-Process -Id $ProcPid -ErrorAction SilentlyContinue)
}

# Reap stale PID files only after Test-Pid-Alive and Write-Warn are defined.
if (Test-Path $PidDir) {
    Get-ChildItem $PidDir -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
        $alive = $false
        $v = Get-Content $_.FullName -ErrorAction SilentlyContinue
        if ($v -and ($v -as [int]) -and (Test-Pid-Alive ([int]$v))) { $alive = $true }
        if (-not $alive) {
            Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
            Write-Warn "Removed stale pid file: $($_.Name)"
        }
    }
}

function Stop-Port {
    param([int]$Port, [string]$Label = "port $Port")
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $p = $c.OwningProcess
        if ($p -and (Test-Pid-Alive $p)) {
            Write-Info "Killing $Label -> PID $p"
            try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
}

function Stop-ByName {
    param([string]$Name, [int]$GraceSec = 5)
    $pidV = Get-Pid $Name
    if ($pidV -and (Test-Pid-Alive $pidV)) {
        Write-Info "Stopping $Name (PID $pidV)"
        Emit-Event launcher service_down -Extra @{ name = $Name }
        if ($Name -eq "llama-main") { Emit-Event vllm-llama shutdown }
        try { Stop-Process -Id $pidV -Force -ErrorAction SilentlyContinue } catch {}
        $deadline = (Get-Date).AddSeconds($GraceSec)
        while ((Get-Date) -lt $deadline -and (Test-Pid-Alive $pidV)) {
            Start-Sleep -Milliseconds 200
        }
        if (Test-Pid-Alive $pidV) {
            Write-Warn "$Name still alive; force-killing"
            try { Stop-Process -Id $pidV -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
    Remove-Pid $Name
    $port = $PortMap[$Name]
    if ($port) { Stop-Port $port $Name }
}

$script:Started = @{}
function Get-AllStarted { return ($script:Started.Values | Where-Object { $_ }) }

# --- Q2 JSONL event emission (ADR-0014) ----------------------------------
# Appends one JSON object per event to logs/events/<service>-<UTC-date>.jsonl,
# mirroring the schema produced by services/common/event_json.py (Python side).
# Best-effort: any failure is swallowed so event logging never breaks launch.
function Emit-Event {
    param(
        [string]$Service,
        [string]$Event,
        [string]$Level = "info",
        [hashtable]$Extra = @{}
    )
    try {
        $eventsDir = Join-Path $RepoRoot "logs" "events"
        if (-not (Test-Path $eventsDir)) { New-Item -ItemType Directory -Path $eventsDir -Force | Out-Null }
        $now = (Get-Date).ToUniversalTime()
        $ts = $now.ToString("yyyy-MM-ddTHH:mm:ss.") + "{0:000}Z" -f $now.Millisecond
        $obj = [ordered]@{
            ts      = $ts
            level   = $Level
            service = $Service
            event   = $Event
        }
        if ($Extra -and $Extra.Count -gt 0) { $obj["extra"] = $Extra }
        $date = $now.ToString("yyyy-MM-dd")
        $file = Join-Path $eventsDir ("{0}-{1}.jsonl" -f $Service, $date)
        Add-Content -Path $file -Value ($obj | ConvertTo-Json -Compress -Depth 4) -Encoding utf8
    } catch { }
}

function Wait-Http {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSec = 600,
        [int]$IntervalSec = 5
    )
    Write-Host "  Waiting for $Name at $Url ..."
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -Method GET
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                Write-Ok "$Name is up (HTTP $($resp.StatusCode))"
                Emit-Event launcher service_up -Extra @{ name = $Name; status = $resp.StatusCode }
                return $true
            }
        } catch { }
        foreach ($pidV in (Get-AllStarted)) {
            if (-not (Test-Pid-Alive $pidV)) {
                Write-Err "A backend process (PID $pidV) exited before $Name became ready."
                return $false
            }
        }
        Start-Sleep -Seconds $IntervalSec
    }
    Write-Err "$Name did not become ready within ${TimeoutSec}s ($Url)"
    return $false
}

function Join-ProcessArgs {
    param([string[]]$Items)
    $parts = @()
    foreach ($a in $Items) {
        if ($null -eq $a) { continue }
        $s = [string]$a
        if ($s -eq "") { $parts += '""'; continue }
        if ($s -match '[\s"]') {
            $parts += '"' + ($s -replace '"', '\"') + '"'
        } else {
            $parts += $s
        }
    }
    return ($parts -join " ")
}

function Start-Background {
    param(
        [string]$Name,
        [string]$Exe,
        [string[]]$ArgList,
        [string]$Workdir = "",
        [string]$LogBase = "",
        [hashtable]$ExtraEnv = @{}
    )
    Write-Host "  Starting $Name ..." -ForegroundColor White
    Write-Info ("  exe    : " + $Exe)
    Write-Info ("  args   : " + ($ArgList -join " "))
    if ($Workdir) { Write-Info ("  cwd    : " + $Workdir) }
    if ($LogBase) { Write-Info ("  log    : " + $LogBase + ".log") }

    if ($DryRun) { return $true }

    # 2026-07-31: route stdout/stderr to $LogBase + .log / .err.log when set,
    # so drift_gate runtime phase can grep a real file (the previous
    # RedirectStandard* = $false here meant the banner-claimed log path
    # was a lie). Truncate any prior log so stale passes don't fool the gate.
    $logOut = $null
    $logErr = $null
    if ($LogBase) {
        $logDir = Split-Path $LogBase -Parent
        if ($logDir -and -not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
        if (Test-Path ($LogBase + ".log")) { Remove-Item ($LogBase + ".log") -Force -ErrorAction SilentlyContinue }
        if (Test-Path ($LogBase + ".err.log")) { Remove-Item ($LogBase + ".err.log") -Force -ErrorAction SilentlyContinue }
        $logOut = $LogBase + ".log"
        $logErr = $LogBase + ".err.log"
    }
    foreach ($k in $ExtraEnv.Keys) {
        # Set in the current-process environment; the child process launched
        # below inherits it. We intentionally do NOT assign to
        # ProcessStartInfo.EnvironmentVariables: on this PowerShell 5.1 / .NET
        # build its StringDictionary getter returns $null on first access and
        # its indexer setter throws "Cannot index into a null array".
        [Environment]::SetEnvironmentVariable($k, [string]$ExtraEnv[$k])
    }
    # Use Start-Process for the spawn itself so we get the
    # -RedirectStandardOutput / -RedirectStandardError parameters, which
    # are cleaner than ProcessStartInfo's RedirectStandard* (the latter
    # would also need us to drain the stream or the child blocks).
    $spArgs = @{
        FilePath         = $Exe
        ArgumentList     = $ArgList
        WindowStyle      = "Hidden"
        PassThru         = $true
    }
    if ($Workdir -and (Test-Path $Workdir)) { $spArgs["WorkingDirectory"] = $Workdir }
    if ($logOut) { $spArgs["RedirectStandardOutput"] = $logOut }
    if ($logErr) { $spArgs["RedirectStandardError"]  = $logErr }
    $p = Start-Process @spArgs
    Save-Pid $Name $p.Id
    $script:Started[$Name] = $p.Id
    if ($logOut) { Write-Info ("  -> $logOut") }
    return $true
}

# ---------------------------------------------------------------------------
# Service starters
function Start-LlamaMain {
    Write-Sec "llama-server main  (port $($P.Main))"
    if (-not (Test-Path $LlamaServer)) { throw "llama-server missing: $LlamaServer" }
    if (-not (Test-Path $MainGguf)) { throw "main GGUF missing: $MainGguf" }
    if (-not (Test-Path $MainMmproj)) { throw "main mmproj missing: $MainMmproj" }
    Stop-ByName "llama-main"
    $ctx = if ($env:MAIN_CONTEXT) { [int]$env:MAIN_CONTEXT } else { 4096 }
    $args = @(
        "-m", $MainGguf,
        "--mmproj", $MainMmproj,
        "--host", "127.0.0.1",
        "--port", "$($P.Main)",
        "-c", "$ctx",
        "-ngl", "999",
        "--parallel", "1",
        "-fit", "off",
        "--jinja"
    )
    if ($env:MAIN_EXTRA_ARGS) { $args += @($env:MAIN_EXTRA_ARGS -split " ") }
    $llamaDir = Split-Path $LlamaServer -Parent
    $envs = @{
        "PATH" = "$llamaDir;$env:PATH"
    }
    $ok = (Start-Background "llama-main" $LlamaServer $args `
        -Workdir $llamaDir `
        -LogBase (Join-Path $LogDir "llama-main") `
        -ExtraEnv $envs)
    Emit-Event vllm-llama startup
    return $ok
}

function Start-VoiceClone {
    Write-Sec "voice-clone API  (port $($P.VoiceClone))"
    if (-not (Test-Path $VenvPy))  { throw "venv python missing: $VenvPy. Run install\install-windows.ps1" }
    $voiceDir = Join-Path $ServicesDir "voice-clone"
    if (-not (Test-Path $voiceDir)) { throw "voice-clone package not found at $voiceDir" }
    Stop-ByName "voice-clone"
    $args = @(
        "-m", "uvicorn", "voice_clone_api.main:app",
        "--host", "127.0.0.1",
        "--port", "$($P.VoiceClone)"
    )
    if ($env:VOICE_CLONE_EXTRA_ARGS) { $args += @($env:VOICE_CLONE_EXTRA_ARGS -split " ") }
    # As of 2026-07-12 voice-clone is MiniMax-only. CosyVoice3 has been removed
    # from the codebase. Inject TTS_PROVIDER + MiniMax credentials (loaded from
    # run-windows.env or User env) so the service refuses to boot with stub.
    $envs = @{
        "VOICE_CLONE_HOST"     = "127.0.0.1"
        "VOICE_CLONE_PORT"     = "$($P.VoiceClone)"
        "TTS_PROVIDER"         = if ($env:TTS_PROVIDER)         { $env:TTS_PROVIDER }         else { "minimax" }
        "MINIMAX_GROUP_ID"     = if ($env:MINIMAX_GROUP_ID)     { $env:MINIMAX_GROUP_ID }     else { "" }
        "MINIMAX_DEFAULT_MODEL"= if ($env:MINIMAX_DEFAULT_MODEL){ $env:MINIMAX_DEFAULT_MODEL} else { "speech-2.8-hd" }
        "MINIMAX_LANGUAGE_BOOST" = if ($env:MINIMAX_LANGUAGE_BOOST) { $env:MINIMAX_LANGUAGE_BOOST } else { "Chinese" }
        "VOICES_DIR"           = if ($env:VOICES_DIR) { $env:VOICES_DIR } else { (Join-Path $voiceDir "voices") }
    }
    return (Start-Background "voice-clone" $VenvPy $args `
        -Workdir $voiceDir `
        -LogBase (Join-Path $LogDir "voice-clone") `
        -ExtraEnv $envs)
}

function Start-Hermes {
    Write-Sec "hermes-agent gateway  (port $($P.Hermes))"
    if (-not (Test-Path $HermesExe)) { throw "hermes not found at $HermesExe. Run install\setup-hermes.ps1" }
    Stop-ByName "hermes-gateway"
    $args = @("gateway")
    $envs = @{
        "API_SERVER_HOST" = "127.0.0.1"
        "API_SERVER_PORT" = "$($P.Hermes)"
    }
    if ($env:HERMES_API_KEY) { $envs["API_SERVER_KEY"] = $env:HERMES_API_KEY }
    return (Start-Background "hermes-gateway" $HermesExe $args `
        -Workdir (Split-Path $HermesExe -Parent) `
        -LogBase (Join-Path $LogDir "hermes-gateway") `
        -ExtraEnv $envs)
}

function Start-BackgroundAgent {
    Write-Sec "background-agent hermes shim  (port $($P.BgAgent))"
    if (-not (Test-Path $VenvPy)) { throw "venv python missing: $VenvPy" }
    Stop-ByName "background-agent"
    $args = @(
        "-m", "uvicorn", "hermes_api.main:app",
        "--host", "127.0.0.1",
        "--port", "$($P.BgAgent)"
    )
    if ($env:BG_AGENT_EXTRA_ARGS) { $args += @($env:BG_AGENT_EXTRA_ARGS -split " ") }
    $envs = @{
        "CODEX_API_HOST"             = "127.0.0.1"
        "CODEX_API_PORT"             = "$($P.BgAgent)"
        "HERMES_GATEWAY_HOST"        = "127.0.0.1"
        "HERMES_GATEWAY_PORT"        = "$($P.Hermes)"
        "HERMES_API_URL"             = "http://127.0.0.1:$($P.Hermes)/v1"
        "CODEX_API_MAX_SUBAGENTS"    = if ($env:CODEX_API_MAX_SUBAGENTS) { $env:CODEX_API_MAX_SUBAGENTS } else { "6" }
        "BACKGROUND_AGENT_API_URL"   = "http://127.0.0.1:$($P.BgAgent)"
    }
    if ($env:HERMES_API_KEY) { $envs["HERMES_API_KEY"] = $env:HERMES_API_KEY; $envs["API_SERVER_KEY"] = $env:HERMES_API_KEY }
    return (Start-Background "background-agent" $VenvPy $args `
        -Workdir (Join-Path $ServicesDir "background-agent") `
        -LogBase (Join-Path $LogDir "background-agent") `
        -ExtraEnv $envs)
}

function Start-Webinfer {
    Write-Sec "webinfer live adapter  (port $($P.Webinfer))"
    if (-not (Test-Path $VenvPy)) { throw "venv python missing: $VenvPy" }
    Stop-ByName "webinfer"
    $workdir = Join-Path $ServicesDir "webinfer"
    $frameSaveDir = if ($env:FRAME_SAVE_DIR) { $env:FRAME_SAVE_DIR } else { "C:\AI\frames" }
    $args = @(
        "live_adapter.py",
        "--host", "127.0.0.1",
        "--port", "$($P.Webinfer)",
        "--adapter-model", "streaming-infer-adapter",
        "--main-api-base", "http://127.0.0.1:$($P.Main)/v1",
        "--main-model", "joyai-vl-interaction-preview",
        "--summarizer-api-base", "http://127.0.0.1:$($P.Main)/v1",
        "--summarizer-model", "joyai-vl-interaction-preview",
        "--longterm-api-base", "http://127.0.0.1:$($P.Main)/v1",
        "--longterm-model", "joyai-vl-interaction-preview",
        "--frame-save-dir", $frameSaveDir
    )
    if ($env:WEBINFER_EXTRA_ARGS) { $args += @($env:WEBINFER_EXTRA_ARGS -split " ") }
    if ($env:SYSTEM_PROMPT) { $args += @("--system-prompt", $env:SYSTEM_PROMPT) }
    $envs = @{
        "ADAPTER_HOST" = "127.0.0.1"
        "ADAPTER_PORT" = "$($P.Webinfer)"
        "MAIN_API_BASE" = "http://127.0.0.1:$($P.Main)/v1"
        "SUMMARIZER_API_BASE" = "http://127.0.0.1:$($P.Main)/v1"
    }
    if ($env:CHARACTER_PROMPT_PATH) { $envs["CHARACTER_PROMPT_PATH"] = $env:CHARACTER_PROMPT_PATH }
    if ($env:LOG_LEVEL) { $envs["LOG_LEVEL"] = $env:LOG_LEVEL }
    return (Start-Background "webinfer" $VenvPy $args `
        -Workdir $workdir `
        -LogBase (Join-Path $LogDir "webinfer") `
        -ExtraEnv $envs)
}

function Start-AsrAdapter {
    Write-Sec "asr-adapter  (port $($P.AsrAdapter))"
    if (-not (Test-Path $VenvPy)) { throw "venv python missing: $VenvPy" }
    Stop-ByName "asr-adapter"
    $workdir = Join-Path $ServicesDir "asr"
    $args = @(
        "-m", "joyvl_asr_adapter", "serve",
        "--host", "127.0.0.1",
        "--port", "$($P.AsrAdapter)"
    )
    $envs = @{
        "ASR_ADAPTER_HOST" = "127.0.0.1"
        "ASR_ADAPTER_PORT" = "$($P.AsrAdapter)"
        "ASR_UPSTREAM_URL" = "http://127.0.0.1:$($P.AsrModel)/v1/audio/transcriptions"
        "ASR_MODEL"        = "whisper-1"
    }
    if ($env:ASR_ADAPTER_EXTRA_ARGS) { $args += @($env:ASR_ADAPTER_EXTRA_ARGS -split " ") }
    return (Start-Background "asr-adapter" $VenvPy $args `
        -Workdir $workdir `
        -LogBase (Join-Path $LogDir "asr-adapter") `
        -ExtraEnv $envs)
}


function Start-Webui {
    Write-Sec "webui  (port $($P.Webui))"
    if (-not (Test-Path $VenvPy)) { throw "venv python missing: $VenvPy" }
    Stop-ByName "webui"
    $workdir = Join-Path $ServicesDir "webui"
    $args = @(
        "-m", "joy_interaction_webui.server",
        "--no-ssl",
        "--host", "127.0.0.1",
        "--port", "$($P.Webui)",
        "--model", "streaming-infer-adapter",
        "--api-base", "http://127.0.0.1:$($P.Webinfer)/v1"
    )
    if ($env:WEBUI_EXTRA_ARGS) { $args += @($env:WEBUI_EXTRA_ARGS -split " ") }
    $envs = @{
        "PYTHONPATH"   = Join-Path $workdir "src"
        "WEBUI_API_BASE" = "http://127.0.0.1:$($P.Webinfer)/v1"
        # v0.3 (2026-07-29): webui gateway must proxy /v1/{providers/health,settings/network,
        # namespaces,external/sync,external/ingest-text} to the REAL memory-store backend
        # (D-L4-001 port rule). server.py:958 reads JOYAI_MEMORY_STORE_URL and defaults to
        # 8996 (the empty shell) when unset, which is the DRIFT-3 root cause. Injecting it
        # here from run-windows.env (MEMORY_PORT/URL) makes the gateway always talk to
        # 8997 — env wins over the in-code default.
        "JOYAI_MEMORY_STORE_URL" = if ($env:JOYAI_MEMORY_STORE_URL) { $env:JOYAI_MEMORY_STORE_URL } else { "http://127.0.0.1:$($P.MemoryStore)" }
    }
    return (Start-Background "webui" $VenvPy $args `
        -Workdir $workdir `
        -LogBase (Join-Path $LogDir "webui") `
        -ExtraEnv $envs)
}

function Start-MemoryStore {
    Write-Sec "memory-store (port $($P.MemoryStore))"
    Stop-ByName "memory-store"
    $workdir = Join-Path $ServicesDir "memory-store"
    $args = @("-m", "memory_store.app")
    if ($env:MEMORY_EXTRA_ARGS) { $args += @($env:MEMORY_EXTRA_ARGS -split " ") }
    $envs = @{
        "MEMORY_PORT"        = "$($P.MemoryStore)"
        "MEMORY_BACKEND"     = if ($env:MEMORY_BACKEND)     { $env:MEMORY_BACKEND }     else { "sqlite" }
        "MEMORY_SQLITE_PATH" = if ($env:MEMORY_SQLITE_PATH) { $env:MEMORY_SQLITE_PATH } else { (Join-Path $workdir "data\memory.sqlite") }
    }
    return (Start-Background "memory-store" $VenvPy $args `
        -Workdir $workdir `
        -LogBase (Join-Path $LogDir "memory-store") `
        -ExtraEnv $envs)
}

# ---------------------------------------------------------------------------
# Launch metadata (for traceability)
# ---------------------------------------------------------------------------

$script:LaunchTime = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$script:LaunchMode = $Mode
Write-Host "" -ForegroundColor DarkGray
Write-Host "  launcher_at: $script:LaunchTime  mode: $script:LaunchMode" -ForegroundColor DarkGray
$gitHead = (& git -C $RepoRoot rev-parse --short HEAD 2>$null)
if ($gitHead) { Write-Host "  git_head:    $gitHead" -ForegroundColor DarkGray }

# Mode planner
# ---------------------------------------------------------------------------
function Plan-For {
    param([string]$ModeName)
    $plan = [ordered]@{}
    switch ($ModeName) {
        "minimal" {
            $plan["llama-main"] = $true
            $plan["webinfer"]   = $true
            $plan["webui"]      = $true
        }
        "voice" {
            $plan["llama-main"]  = $true
            $plan["voice-clone"] = $true
            $plan["webinfer"]    = $true
            $plan["webui"]       = $true
        }
        default {
            $plan["llama-main"]       = $true
            $plan["voice-clone"]      = $true
            $plan["webinfer"]         = $true
            $plan["webui"]            = $true
        }
    }
    return $plan
}

if ($Mode -eq "gaming") {
    $env:FORCE_SILENCE_BEFORE_QUERY = "false"
    if (-not $env:LOG_LEVEL) { $env:LOG_LEVEL = "WARNING" }
}

# ---------------------------------------------------------------------------
# Plan / print summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " run-windows.ps1 :: $Mode mode" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
$plan = Plan-For $Mode
# memory-store is part of the default plan as of v0.3 (2026-07-29).
# Per DRIFT-2/3 closure: scripts must default to ON so the webui gateway does not
# point at the empty :8996 shell. Operators can opt out by setting
# ``JOYAI_ENABLE_MEMORY_STORE=0`` before invoking run-windows.ps1.
if ($env:JOYAI_ENABLE_MEMORY_STORE -ne "0") {
    $plan["memory-store"] = $true
}

Write-Host (" {0,-22} {1,-7} {2,-7} {3}" -f "Service", "Enabled", "Port", "Source") -ForegroundColor Yellow
foreach ($k in $plan.Keys) {
    $on = if ($plan[$k]) { "Y" } else { "-" }
    $port = if ($PortMap.ContainsKey($k)) { $PortMap[$k] } else { "-" }
    $src = switch ($k) {
        "llama-main"       { "llama.cpp ($LlamaServer)" }
        "llama-summary"    { "llama.cpp ($LlamaServer)" }
        "whisper"          { "whisper.cpp ($WhisperServer)" }
        "voice-clone"      { "uvicorn voice_clone_api" }
        "hermes-gateway"   { "hermes.cmd gateway ($HermesExe)" }
        "background-agent" { "uvicorn hermes_api" }
        "webinfer"         { "live_adapter.py" }
        "asr-adapter"      { "joyvl_asr_adapter serve" }
        "webui"            { "joy_interaction_webui.server" }
        default            { "-" }
        "memory-store"    { "memory_store.app" }
    }
    Write-Host (" {0,-22} {1,-7} {2,-7} {3}" -f $k, $on, $port, $src)
}
Write-Host ""

if ($DryRun) {
    Write-Ok "Dry run complete; no process was started or stopped."
    return
}

# ---------------------------------------------------------------------------
# Stop switch
# ---------------------------------------------------------------------------
if ($Stop) {
    Write-Sec "Stop requested"
    foreach ($k in $plan.Keys) { if ($plan[$k]) { Stop-ByName $k } }
    Write-Ok "All requested services stopped."
    return
}

# ---------------------------------------------------------------------------
# -Restart <name|all>
# ---------------------------------------------------------------------------
if ($Restart) {
    Write-Sec "Restart requested: $Restart"
    $map = @{
        "llama-main"       = "Start-LlamaMain"
        "llama-summary"    = "Start-Llama-Summary"
        "whisper"          = "Start-Whisper"
        "voice-clone"      = "Start-VoiceClone"
        "hermes-gateway"   = "Start-Hermes"
        "background-agent" = "Start-BackgroundAgent"
        "webinfer"         = "Start-Webinfer"
        "asr-adapter"      = "Start-AsrAdapter"
        "webui"            = "Start-Webui"
    "memory-store"         = "Start-MemoryStore"
    }
    $targets = if ($Restart -eq "all") { @($plan.Keys | Where-Object { $plan[$_] }) } else { @($Restart) }
    foreach ($t in $targets) {
        Stop-ByName $t
    }
    foreach ($t in $targets) {
        $fn = $map[$t]
        if (-not $fn) { Write-Warn "Unknown service: $t"; continue }
        & $fn
    }
    $readyMap = @{
        "llama-main"       = "http://127.0.0.1:$($P.Main)/v1/models"
        "llama-summary"    = "http://127.0.0.1:$($P.Summary)/v1/models"
        "whisper"          = "http://127.0.0.1:$($P.AsrModel)/v1/models"
        "voice-clone"      = "http://127.0.0.1:$($P.VoiceClone)/health"
        "hermes-gateway"   = "http://127.0.0.1:$($P.Hermes)/health"
        "background-agent" = "http://127.0.0.1:$($P.BgAgent)/health"
        "webinfer"         = "http://127.0.0.1:$($P.Webinfer)/health"
        "asr-adapter"      = "http://127.0.0.1:$($P.AsrAdapter)/health"
        "webui"            = "http://127.0.0.1:$($P.Webui)/"
        "memory-store"     = "http://127.0.0.1:$($P.MemoryStore)/health"
    }
    foreach ($t in $targets) {
        $u = $readyMap[$t]
        if ($u) { Wait-Http -Name $t -Url $u -TimeoutSec 300 | Out-Null }
    }
    return
}

# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
$script:Stopping = $false
function Stop-All {
    if ($script:Stopping) { return }
    $script:Stopping = $true
    Emit-Event launcher stop
    Write-Host ""
    Write-Host "Stopping services..." -ForegroundColor Yellow
    foreach ($k in $plan.Keys) {
        if ($plan[$k]) { Stop-ByName $k }
    }
    Write-Ok "All services stopped."
}
$consoleCancel = [System.ConsoleCancelEventHandler]{
    param($s, $e)
    Write-Host ""
    Write-Host "Ctrl+C caught; cleaning up..." -ForegroundColor Yellow
    Stop-All
    $e.Cancel = $true
    [System.Environment]::Exit(130)
}
[Console]::add_CancelKeyPress($consoleCancel)

try {
    Emit-Event launcher start -Extra @{ launch_time = $script:LaunchTime; mode = $script:LaunchMode }
    $ordered = @("llama-main", "llama-summary", "whisper", "voice-clone",
                 "hermes-gateway", "background-agent", "webinfer", "asr-adapter", "webui",
                 "memory-store"
    )
    $orderMap = @{
        "llama-main"       = "Start-LlamaMain"
        "llama-summary"    = "Start-Llama-Summary"
        "whisper"          = "Start-Whisper"
        "voice-clone"      = "Start-VoiceClone"
        "hermes-gateway"   = "Start-Hermes"
        "background-agent" = "Start-BackgroundAgent"
        "webinfer"         = "Start-Webinfer"
        "asr-adapter"      = "Start-AsrAdapter"
        "webui"            = "Start-Webui"
        "memory-store"     = "Start-MemoryStore"
    }
    $readyMap = @{
        "llama-main"       = "http://127.0.0.1:$($P.Main)/v1/models"
        "llama-summary"    = "http://127.0.0.1:$($P.Summary)/v1/models"
        "whisper"          = "http://127.0.0.1:$($P.AsrModel)/v1/models"
        "voice-clone"      = "http://127.0.0.1:$($P.VoiceClone)/health"
        "hermes-gateway"   = "http://127.0.0.1:$($P.Hermes)/health"
        "background-agent" = "http://127.0.0.1:$($P.BgAgent)/health"
        "webinfer"         = "http://127.0.0.1:$($P.Webinfer)/health"
        "asr-adapter"      = "http://127.0.0.1:$($P.AsrAdapter)/health"
        "webui"            = "http://127.0.0.1:$($P.Webui)/"
        "memory-store"     = "http://127.0.0.1:$($P.MemoryStore)/health"
    }

    foreach ($name in $ordered) {
        if (-not $plan[$name]) { continue }
        $fn = $orderMap[$name]
        & $fn
        $url = $readyMap[$name]
        if ($url) {
            $ok = Wait-Http -Name $name -Url $url -TimeoutSec 900
            if (-not $ok) {
                Write-Err "Aborting: $name failed to come up. Tearing down..."
                Stop-All
                exit 1
            }
        }
    }

    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Green
    # Auto-refresh the VLM runtime probe so drift_gate runtime phase
    # has a fresh file (not stale from the previous launch).
    $probeScript = Join-Path $RepoRoot "scripts\vlm_runtime_probe.py"
    $probeOut = Join-Path $RepoRoot "logs\vlm-runtime-props.json"
    if ($plan["llama-main"] -and (Test-Path $probeScript)) {
        $py = "D:\AI\envs\joyai-main\python.exe"
        Emit-Event launcher probe_refresh -Extra @{ base_url = ("http://127.0.0.1:" + $P.Main) }
        & $py $probeScript --base-url ("http://127.0.0.1:" + $P.Main) --out $probeOut --wait 5 2>&1 | Out-Null
    }
    Write-Host " All services ready. WebUI is running in the foreground." -ForegroundColor Green
    Write-Host " Open http://127.0.0.1:$($P.Webui)/  in your browser." -ForegroundColor Green
    Write-Host " Press Ctrl+C to stop everything." -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host ""

    $webuiPid = $script:Started["webui"]
    if ($webuiPid) {
        while (Test-Pid-Alive $webuiPid) {
            Start-Sleep -Seconds 2
        }
        Write-Warn "WebUI exited; tearing down backends."
        Stop-All
    } else {
        while ($true) { Start-Sleep -Seconds 60 }
    }
} catch {
    Write-Err "Fatal: $_"
    Stop-All
    exit 1
}

