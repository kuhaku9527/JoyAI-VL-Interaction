#requires -Version 5.1
<#
.SYNOPSIS
  Install NousResearch/hermes-agent v0.17.0 on Windows and configure it for
  the JoyAI-VL-Interaction background-agent shim.

.DESCRIPTION
  - Runs the official PowerShell installer: iex (irm .../install.ps1)
  - Ensures API_SERVER_ENABLED=true and a random API_SERVER_KEY in
    $env:LOCALAPPDATA\hermes\.env
  - Runs 'hermes doctor' for a final sanity check.

  Reference: services/background-agent/README.md
#>

[CmdletBinding()]
param(
    [string]$HermesRepo = "NousResearch/hermes-agent",
    [string]$HermesVersion = "v0.17.0",
    [string]$InstallScriptUrl = "",
    [string]$HermesHome = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "Continue"

function Write-Ok   { param($m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Info { param($m) Write-Host "  [..]   $m" -ForegroundColor DarkGray }
function Write-Warn { param($m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "  [FAIL] $m" -ForegroundColor Red }

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not $InstallScriptUrl) {
    $InstallScriptUrl = "https://raw.githubusercontent.com/$HermesRepo/main/scripts/install.ps1"
}
if (-not $HermesHome) {
    $HermesHome = Join-Path $env:LOCALAPPDATA "hermes"
}

# ---------------------------------------------------------------------------
# 1) Run the official installer if 'hermes' is not on PATH
# ---------------------------------------------------------------------------
$hermesCmd = Get-Command "hermes.cmd" -ErrorAction SilentlyContinue
$hermes    = Get-Command "hermes"     -ErrorAction SilentlyContinue
if (-not $hermesCmd -and -not $hermes) {
    Write-Info "Running official hermes installer: $InstallScriptUrl"
    try {
        $irmArgs = @{ Uri = $InstallScriptUrl; UseBasicParsing = $true }
        $script = Invoke-RestMethod @irmArgs
        Invoke-Expression $script
    } catch {
        throw "hermes installer failed: $_"
    }
}

# Re-resolve
$hermesExe = $null
foreach ($cand in @(
    (Join-Path $env:LOCALAPPDATA "hermes\bin\hermes.cmd"),
    (Get-Command "hermes.cmd" -ErrorAction SilentlyContinue).Source,
    (Get-Command "hermes" -ErrorAction SilentlyContinue).Source
)) {
    if ($cand -and (Test-Path $cand)) { $hermesExe = $cand; break }
}
if (-not $hermesExe) {
    throw "hermes CLI not found after install. Looked in %LOCALAPPDATA%\hermes\bin and on PATH."
}
Write-Ok "hermes: $hermesExe"

# Show version
try { & $hermesExe --version } catch { Write-Warn "Could not run --version" }

# ---------------------------------------------------------------------------
# 2) Configure $env:LOCALAPPDATA\hermes\.env
# ---------------------------------------------------------------------------
$hermesDir = $HermesHome
if (-not (Test-Path $hermesDir)) { New-Item -ItemType Directory -Path $hermesDir -Force | Out-Null }
$envFile   = Join-Path $hermesDir ".env"

function Set-Or-Append-Env {
    param([string]$Path, [string]$Key, [string]$Value)
    $lines = if (Test-Path $Path) { Get-Content $Path } else { @() }
    $found = $false
    $new = foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Key))\s*=") { $found = $true; "$Key=$Value" } else { $line }
    }
    if (-not $found) { $new += "$Key=$Value" }
    Set-Content -Path $Path -Value $new -Encoding UTF8
}

# Generate a random API key
$key = -join ((1..32) | ForEach-Object { [char[]]([char]'a'..[char]'z' + [char]'A'..[char]'Z' + [char]'0'..[char]'9') | Get-Random })
Set-Or-Append-Env $envFile "API_SERVER_ENABLED" "true"
Set-Or-Append-Env $envFile "API_SERVER_KEY"      $key
Set-Or-Append-Env $envFile "API_SERVER_HOST"     "127.0.0.1"
Set-Or-Append-Env $envFile "API_SERVER_PORT"     "8642"
Set-Or-Append-Env $envFile "API_SERVER_CORS_ORIGINS" "http://127.0.0.1:8079"

Write-Ok "Wrote $envFile"
Write-Ok "API_SERVER_KEY: $key"

# Reflect into the current session
$env:API_SERVER_ENABLED = "true"
$env:API_SERVER_KEY     = $key

# ---------------------------------------------------------------------------
# 3) Hermes doctor
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "== hermes doctor ==" -ForegroundColor Cyan
try {
    & $hermesExe doctor
    if ($LASTEXITCODE -ne 0) { Write-Warn "hermes doctor returned $LASTEXITCODE" }
} catch {
    Write-Warn "hermes doctor failed: $_"
}

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " Hermes-agent setup complete" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Hermes home  : $hermesDir"
Write-Host "  Hermes exe   : $hermesExe"
Write-Host "  .env         : $envFile"
Write-Host "  API key      : $key"
Write-Host "  Gateway port : 8642"
Write-Host ""
Write-Host "IMPORTANT: copy the API key above into your background-agent.env:" -ForegroundColor Yellow
Write-Host "    HERMES_API_KEY=$key" -ForegroundColor Gray
Write-Host "    HERMES_GATEWAY_URL=http://127.0.0.1:8642" -ForegroundColor Gray
Write-Host ""
Write-Host "Test:" -ForegroundColor Yellow
Write-Host "  hermes gateway        # foreground gateway on :8642" -ForegroundColor Gray
Write-Host "  curl http://127.0.0.1:8642/health" -ForegroundColor Gray