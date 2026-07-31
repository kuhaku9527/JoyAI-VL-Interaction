#requires -Version 5.1
<#
.SYNOPSIS
  Mirror of stop-joyai.ps1: launch the JoyAI-VL service stack.

.DESCRIPTION
  Thin wrapper around services\scripts\run-windows.ps1 with sensible
  defaults. Equivalent to the long PowerShell command but easy to
  remember and alias.

  Modes are passed straight through to run-windows.ps1 (default | minimal
  | voice | gaming). Use -Stop to forward to run-windows.ps1 -Stop.

  Usage:
    powershell -ExecutionPolicy Bypass -File start-joyai.ps1
    powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Mode voice
    powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Mode minimal
    powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Restart llama-main
    powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Stop
#>

[CmdletBinding()]
param(
    [ValidateSet("default","minimal","voice","gaming")]
    [string]$Mode = "default",
    [string]$Restart = "",
    [switch]$Stop,
    [string]$RepoRoot = ""
)

$ScriptDir = $PSScriptRoot
if (-not $RepoRoot) { $RepoRoot = $ScriptDir }
$RunScript = Join-Path $RepoRoot "services\scripts\run-windows.ps1"
if (-not (Test-Path $RunScript)) {
    Write-Host "[ERR] Cannot find $RunScript" -ForegroundColor Red
    exit 2
}

$args = @()
if ($Mode)     { $args += @("-Mode", $Mode) }
if ($Restart)  { $args += @("-Restart", $Restart) }
if ($Stop)     { $args += @("-Stop") }
Write-Host "Forwarding to: $RunScript $($args -join ' ')" -ForegroundColor DarkGray

# 2026-07-31: capture the entire launcher session (banner + service
# status + post-launch messages) to logs/launcher-<UTC-ISO>.log via
# Start-Transcript. Without this, the launcher output only lives in
# the parent shell stdout and is lost if launched detached / via schtasks.
$launchLogDir = Join-Path $RepoRoot "logs"
if (-not (Test-Path $launchLogDir)) { New-Item -ItemType Directory -Path $launchLogDir -Force | Out-Null }
$launchTs = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH-mm-ssZ")
$launchLog = Join-Path $launchLogDir ("launcher-" + $launchTs + ".log")
Start-Transcript -Path $launchLog
Write-Host ("[transcript] " + $launchLog) -ForegroundColor DarkGray
& powershell -ExecutionPolicy Bypass -File $RunScript @args
$rc = $LASTEXITCODE
Stop-Transcript | Out-Null
exit $rc
