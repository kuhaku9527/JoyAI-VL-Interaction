#requires -Version 5.1
<#
.SYNOPSIS
  Install whisper.cpp Windows cublas prebuilt + the ggml-large-v3-turbo-q5_0
  ASR model into D:\AI\bin\whisper.cpp\ and D:\AI\models\asr\.

.DESCRIPTION
  Downloads:
    - whisper-cublas-12.4.0-bin-x64.zip from ggml-org/whisper.cpp v1.7.6
    - ggml-large-v3-turbo-q5_0.bin (~547 MB) from ggerganov/whisper.cpp

  Exposes $env:WHISPER_SERVER pointing at whisper-server.exe.
#>

[CmdletBinding()]
param(
    [string]$BinRoot    = "D:\AI\bin",
    [string]$ModelsRoot = "D:\AI\models",
    [string]$AsrModel   = "ggml-large-v3-turbo-q5_0.bin",
    [switch]$ForceRedownload
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "Continue"

function Write-Ok   { param($m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Info { param($m) Write-Host "  [..]   $m" -ForegroundColor DarkGray }
function Write-Warn { param($m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "  [FAIL] $m" -ForegroundColor Red }

$dest       = Join-Path $BinRoot "whisper.cpp"
$serverExe  = Join-Path $dest "whisper-server.exe"
$modelDir   = Join-Path $ModelsRoot "asr"
$modelPath  = Join-Path $modelDir $AsrModel

# Idempotent early-out
if ((Test-Path $serverExe) -and (Test-Path $modelPath) -and -not $ForceRedownload) {
    Write-Ok "whisper.cpp already installed at $dest"
    Write-Ok "ASR model already at $modelPath"
    $env:WHISPER_SERVER = $serverExe
    Write-Ok "WHISPER_SERVER=$serverExe"
    return
}

if (-not (Test-Path $dest))     { New-Item -ItemType Directory -Path $dest     -Force | Out-Null }
if (-not (Test-Path $modelDir)) { New-Item -ItemType Directory -Path $modelDir -Force | Out-Null }

# ---------------------------------------------------------------------------
# 1) whisper.cpp Windows cublas prebuilt
# ---------------------------------------------------------------------------
$version   = "v1.7.6"
$assetName = "whisper-cublas-12.4.0-bin-x64.zip"
$url       = "https://github.com/ggml-org/whisper.cpp/releases/download/$version/$assetName"

$tmp = Join-Path $env:TEMP ("whisper_cpp_install_" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$zip = Join-Path $tmp $assetName

try {
    Write-Info "GET $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "joyai-windows-installer")
    $wc.DownloadFile($url, $zip)
    $wc.Dispose()
    $size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
    if ($size -lt 5) { throw "Downloaded file is suspiciously small ($size MB)" }
    Write-Ok "Saved $zip ($size MB)"

    Write-Info "Extracting to $dest"
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    Expand-Archive -Path $zip -DestinationPath $dest -Force
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

if (-not (Test-Path $serverExe)) {
    $found = Get-ChildItem -Path $dest -Recurse -Filter "whisper-server.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { Move-Item -Path $found.FullName -Destination $serverExe -Force }
    else { throw "whisper-server.exe not found in extracted tree at $dest" }
}

# ---------------------------------------------------------------------------
# 2) ASR model
# ---------------------------------------------------------------------------
if (-not (Test-Path $modelPath) -or $ForceRedownload) {
    $modelUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$AsrModel"
    Write-Info "GET $modelUrl"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "joyai-windows-installer")
    $wc.DownloadFile($modelUrl, $modelPath)
    $wc.Dispose()
    $size = [math]::Round((Get-Item $modelPath).Length / 1MB, 1)
    if ($size -lt 400) { throw "ASR model too small ($size MB)" }
    Write-Ok "ASR model $modelPath ($size MB)"
} else {
    Write-Ok "ASR model already at $modelPath"
}

# ---------------------------------------------------------------------------
# Persist env hint
# ---------------------------------------------------------------------------
$env:WHISPER_SERVER = $serverExe
$envHint = Join-Path (Split-Path $PSScriptRoot -Parent) "services\.install-windows.env"
if (Test-Path $envHint) {
    $existing = Get-Content $envHint
    $replaced = $false
    $new = foreach ($line in $existing) {
        if ($line -match "^WHISPER_SERVER=") { $replaced = $true; "WHISPER_SERVER=$serverExe" } else { $line }
    }
    if (-not $replaced) { $new += "WHISPER_SERVER=$serverExe" }
    Set-Content -Path $envHint -Value $new -Encoding UTF8
}

Write-Host ""
Write-Ok "whisper.cpp installed at $dest"
Write-Ok "ASR model at $modelPath"
Write-Ok "WHISPER_SERVER=$serverExe"
Write-Host ""
Write-Host "Next step (manual test):" -ForegroundColor Yellow
Write-Host "  `"$serverExe`" -m `"$modelPath`" --port 8993 --host 127.0.0.1 --inference-path /v1/audio/transcriptions --request-path /v1 --convert -l auto" -ForegroundColor Gray