#requires -Version 5.1
<#
.SYNOPSIS
  Install llama.cpp Windows sm_120 prebuilt into D:\AI\bin\llama.cpp\.

.DESCRIPTION
  Prefers the official ggml-org/llama.cpp CUDA 13.1 release (b9330+) which includes the sm_120 (Blackwell) fixes the older Andgihat b9150 build lacks (mmq.cuh + flash_attn sm_120 issues). Falls back to CUDA 12.4 if 13.1 unavailable. b9150 / Andgihat is intentionally not used (sm_120 crash, see llama.cpp #24218).

  Exposes $env:LLAMA_SERVER pointing at llama-server.exe.
#>

[CmdletBinding()]
param(
    [string]$BinRoot = "D:\AI\bin",
    [string]$ToolsRoot = "D:\AI\tools",
    [switch]$ForceRedownload
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "Continue"

function Write-Ok   { param($m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Info { param($m) Write-Host "  [..]   $m" -ForegroundColor DarkGray }
function Write-Warn { param($m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "  [FAIL] $m" -ForegroundColor Red }

$dest = Join-Path $BinRoot "llama.cpp"
$serverExe = Join-Path $dest "llama-server.exe"

# ---------------------------------------------------------------------------
# Idempotency: if llama-server.exe is already there and the user did not
# ask for a redownload, we just verify it.
# ---------------------------------------------------------------------------
if ((Test-Path $serverExe) -and -not $ForceRedownload) {
    Write-Ok "llama.cpp already installed at $dest"
    & $serverExe --version
    $env:LLAMA_SERVER = $serverExe
    Write-Ok "LLAMA_SERVER=$serverExe"
    return
}

if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest -Force | Out-Null }

# ---------------------------------------------------------------------------
# 1) Try ggml-org/llama.cpp b9330+ (CUDA 13.1 / 12.4 fallback)
#    Latest release is queried from GitHub API.
# ---------------------------------------------------------------------------
function Try-Download {
    param(
        [string]$Url,
        [string]$ZipPath,
        [string]$ExtractDir,
        [string]$StripPrefix = ""
    )
    Write-Info "GET $Url"
    $wc = New-Object System.Net.WebClient
    try {
        $wc.DownloadFile($Url, $ZipPath)
    } catch {
        throw "Download failed: $_"
    } finally {
        $wc.Dispose()
    }
    if (-not (Test-Path $ZipPath) -or (Get-Item $ZipPath).Length -lt 1MB) {
        throw "Downloaded file is too small: $ZipPath"
    }
    Write-Ok "Saved $ZipPath ($([math]::Round((Get-Item $ZipPath).Length / 1MB, 1)) MB)"

    Write-Info "Extracting to $ExtractDir"
    if (Test-Path $ExtractDir) { Remove-Item -Recurse -Force $ExtractDir }
    New-Item -ItemType Directory -Path $ExtractDir -Force | Out-Null
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractDir -Force

    if ($StripPrefix -and (Test-Path (Join-Path $ExtractDir $StripPrefix))) {
        Get-ChildItem (Join-Path $ExtractDir $StripPrefix) -Force | ForEach-Object {
            Move-Item -Path $_.FullName -Destination $ExtractDir -Force
        }
        Remove-Item (Join-Path $ExtractDir $StripPrefix) -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$tmpRoot = Join-Path $env:TEMP "llama_cpp_install"
if (-not (Test-Path $tmpRoot)) { New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null }

$workDir = Join-Path $tmpRoot ("work_" + (Get-Date).Ticks)
New-Item -ItemType Directory -Path $workDir -Force | Out-Null

$downloaded = $false
$labels = @(
    @{ Name = "Official CUDA 13.1 (b9330+, sm_120 fix)"; Owner = "ggml-org"; Repo = "llama.cpp"; AssetPattern = "llama-b9[3-9][0-9][0-9]-bin-win-cuda-13\.1-x64\.zip$" }
    @{ Name = "Official CUDA 12.4 (fallback)"; Owner = "ggml-org"; Repo = "llama.cpp"; AssetPattern = "llama-b9[3-9][0-9][0-9]-bin-win-cuda-12\.4-x64\.zip$" }
)

foreach ($lbl in $labels) {
    try {
        Write-Host ""
        Write-Host "== Trying $($lbl.Name) ==" -ForegroundColor Cyan
        $api = "https://api.github.com/repos/$($lbl.Owner)/$($lbl.Repo)/releases/latest"
        Write-Info "Querying $api"
        $headers = @{ "User-Agent" = "joyai-windows-installer" }
        $release = Invoke-RestMethod -Uri $api -Headers $headers -TimeoutSec 30
        if (-not $release.assets) { throw "no assets in latest release" }
        $asset = $release.assets | Where-Object { $_.name -match $lbl.AssetPattern } | Select-Object -First 1
        if (-not $asset) { throw "no asset matching $($lbl.AssetPattern)" }
        Write-Info "Asset: $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB)"
        $zipPath = Join-Path $workDir $asset.name
        Try-Download -Url $asset.browser_download_url -ZipPath $zipPath -ExtractDir $dest -StripPrefix ""
        $downloaded = $true
        break
    } catch {
        Write-Warn "$($lbl.Name) failed: $_"
    }
}

if (-not $downloaded) {
    throw "All llama.cpp download sources failed. Re-run with -ForceRedownload or check connectivity."
}

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
if (-not (Test-Path $serverExe)) {
    $found = Get-ChildItem -Path $dest -Recurse -Filter "llama-server.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) {
        Write-Info "llama-server.exe was extracted to $($found.FullName); moving to $dest"
        Move-Item -Path $found.FullName -Destination $serverExe -Force
    } else {
        throw "llama-server.exe not found in extracted tree at $dest"
    }
}

# Clean up
Remove-Item -Recurse -Force $workDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $tmpRoot -ErrorAction SilentlyContinue

# Show version
Write-Info "llama-server --version"
& $serverExe --version

# Persist env hint
$env:LLAMA_SERVER = $serverExe
$envHint = Join-Path (Split-Path $PSScriptRoot -Parent) "services\.install-windows.env"
if (Test-Path $envHint) {
    $existing = Get-Content $envHint
    $replaced = $false
    $new = foreach ($line in $existing) {
        if ($line -match "^LLAMA_SERVER=") { $replaced = $true; "LLAMA_SERVER=$serverExe" } else { $line }
    }
    if (-not $replaced) { $new += "LLAMA_SERVER=$serverExe" }
    Set-Content -Path $envHint -Value $new -Encoding UTF8
}

Write-Host ""
Write-Ok "llama.cpp installed at $dest"
Write-Ok "LLAMA_SERVER=$serverExe"
Write-Host ""
Write-Host "Next step:" -ForegroundColor Yellow
Write-Host "  Test manually: `"$serverExe`" --version" -ForegroundColor Gray


