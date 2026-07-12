#requires -Version 5.1
<#
.SYNOPSIS
  Download all GGUF model artefacts required by the Windows-native JoyAI-VL-Interaction
  deployment into D:\AI\models\ (or $ModelsRoot).

.DESCRIPTION
  Layout produced under $ModelsRoot:

      main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\
          joyai-vl-interaction-preview-iq4_nl-imat.gguf   (4.79 GB)
          imatrix.dat                                      (5.1 MB)
          README.md

      main\mmproj\
          mmproj-joyai-vl-interaction-preview-f16.gguf     (generated from
                                                           convert_hf_to_gguf.py --mmproj)

      summary\Qwen2.5-VL-3B-Instruct-GGUF\
          Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf               (1.80 GB)
          Qwen2.5-VL-3B-Instruct-mmproj-f16.gguf           (1.25 GB)

  -Component main|summary|all    (default 'all')
  -HfToken <token>               (only needed for private models)
  -SkipMmproj                    (skip the in-place mmproj generation step)

  Reference: docs/lightweight-replacement.md
#>

[CmdletBinding()]
param(
    [ValidateSet("main","summary","all")]
    [string]$Component = "all",
    [string]$HfToken,
    [switch]$SkipMmproj,
    [string]$ModelsRoot = "D:\AI\models",
    [string]$BinRoot    = "D:\AI\bin",
    [string]$VenvPy     = ""   # path to services\.venv\Scripts\python.exe
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "Continue"

# ---------------------------------------------------------------------------
# Pretty logging
# ---------------------------------------------------------------------------
function Write-Ok   { param($m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Info { param($m) Write-Host "  [..]   $m" -ForegroundColor DarkGray }
function Write-Warn { param($m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "  [FAIL] $m" -ForegroundColor Red }

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# ---------------------------------------------------------------------------
# Resolve venv python
# ---------------------------------------------------------------------------
if (-not $VenvPy) {
    $candidate = Join-Path (Join-Path (Split-Path $PSScriptRoot -Parent) "services") ".venv\Scripts\python.exe"
    if (Test-Path $candidate) { $VenvPy = $candidate }
}
if (-not $VenvPy -or -not (Test-Path $VenvPy)) {
    Write-Warn "services\.venv\Scripts\python.exe not found. Run install\install-windows.ps1 first."
    Write-Warn "Continuing with whichever 'python' is on PATH (mmproj generation may fail)."
    $VenvPy = (Get-Command "python" -ErrorAction SilentlyContinue).Source
}

# ---------------------------------------------------------------------------
# 1) Ensure huggingface-cli is available
# ---------------------------------------------------------------------------
$hf = $null
if (Test-Command "huggingface-cli") {
    $hf = "huggingface-cli"
} elseif (Test-Command "hf") {
    $hf = "hf"
} elseif ($VenvPy -and (Test-Path $VenvPy)) {
    Write-Info "Installing huggingface_hub into venv..."
    & $VenvPy -m pip install -U "huggingface_hub[cli]"
    if ($LASTEXITCODE -eq 0) { $hf = "$VenvPy -m huggingface_hub.cli.huggingface_cli" }
}
if (-not $hf) {
    throw "huggingface-cli (or hf) not available. Install with: pip install -U 'huggingface_hub[cli]'"
}
Write-Ok "hf cli: $hf"

# ---------------------------------------------------------------------------
# 2) Auth (only if a token was provided; public repos do not need it)
# ---------------------------------------------------------------------------
function Invoke-Hf {
    param([string[]]$Args)
    if ($hf -like "*python*") {
        & $VenvPy -m huggingface_hub.cli.huggingface_cli @Args
        return $LASTEXITCODE
    } else {
        & $hf @Args
        return $LASTEXITCODE
    }
}

if ($HfToken) {
    $env:HF_TOKEN = $HfToken
    $env:HUGGING_FACE_HUB_TOKEN = $HfToken
    Write-Info "hf token set in env for this session"
}

# ---------------------------------------------------------------------------
# 3) Target layout
# ---------------------------------------------------------------------------
$mainDir    = Join-Path $ModelsRoot "main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF"
$mmprojDir  = Join-Path $ModelsRoot "main\mmproj"
$summaryDir = Join-Path $ModelsRoot "summary\Qwen2.5-VL-3B-Instruct-GGUF"

foreach ($d in @($mainDir, $mmprojDir, $summaryDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

# ---------------------------------------------------------------------------
# 4) Expected file sizes (min, in bytes) for sanity checks
# ---------------------------------------------------------------------------
$ExpectedSizes = @{
    "joyai-vl-interaction-preview-iq4_nl-imat.gguf" = 4500MB
    "imatrix.dat"                                   = 4MB
    "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"            = 1700MB
    "Qwen2.5-VL-3B-Instruct-mmproj-f16.gguf"        = 1100MB
}

function Assert-FileSize {
    param([string]$Path, [string]$Label, [double]$MinMB)
    if (-not (Test-Path $Path)) {
        throw "File missing: $Path"
    }
    $size = (Get-Item $Path).Length
    $sizeMB = [math]::Round($size / 1MB, 1)
    if ($size -lt ($MinMB * 1MB * 0.95)) {
        throw "File too small: $Path (${sizeMB} MB, expected >= ${MinMB} MB)"
    }
    Write-Ok "$Label  ${sizeMB} MB"
}

# ---------------------------------------------------------------------------
# 5) MAIN: JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF
# ---------------------------------------------------------------------------
function Download-MainModel {
    Write-Host ""
    Write-Host "== MAIN MODEL ==" -ForegroundColor Cyan
    Write-Host "Target: $mainDir"
    $repo = "Nasa1423/JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF"
    Write-Info "Downloading $repo -> $mainDir"
    $rc = Invoke-Hf @("download", $repo,
        "--local-dir", $mainDir,
        "--include", "joyai-vl-interaction-preview-iq4_nl-imat.gguf",
        "--include", "imatrix.dat",
        "--include", "README.md"
    )
    if ($rc -ne 0) { throw "huggingface-cli download failed for main repo" }
    Assert-FileSize (Join-Path $mainDir "joyai-vl-interaction-preview-iq4_nl-imat.gguf") "main gguf"   4500
    Assert-FileSize (Join-Path $mainDir "imatrix.dat")                                "imatrix"      4
}

# ---------------------------------------------------------------------------
# 6) MAIN mmproj: generated from convert_hf_to_gguf.py --mmproj
# ---------------------------------------------------------------------------
function Build-Mmproj {
    Write-Host ""
    Write-Host "== MAIN mmproj (in-place convert_hf_to_gguf.py --mmproj) ==" -ForegroundColor Cyan
    if ($SkipMmproj) {
        Write-Warn "SkipMmproj: skipping mmproj generation."
        return
    }
    if (-not $VenvPy -or -not (Test-Path $VenvPy)) {
        throw "venv python missing. Run install\install-windows.ps1 first, or pass -VenvPy."
    }
    # Need the upstream HF model on disk to run --mmproj against.
    # The upstream repo (jdopensource/JoyAI-VL-Interaction-Preview) ships the
    # vision tower under config.json / preprocessor_config.json.
    $upstreamDir = Join-Path $ModelsRoot "main\JoyAI-VL-Interaction-Preview-src"
    if (-not (Test-Path (Join-Path $upstreamDir "config.json"))) {
        Write-Info "Fetching upstream model files for mmproj conversion..."
        if (-not (Test-Path $upstreamDir)) { New-Item -ItemType Directory -Path $upstreamDir -Force | Out-Null }
        $rc = Invoke-Hf @("download", "jdopensource/JoyAI-VL-Interaction-Preview",
            "--local-dir", $upstreamDir,
            "--include", "config.json",
            "--include", "preprocessor_config.json",
            "--include", "*.safetensors",
            "--include", "tokenizer*"
        )
        if ($rc -ne 0) {
            Write-Warn "Failed to fetch upstream HF repo for mmproj conversion. Skipping."
            return
        }
    }
    # Need llama.cpp's convert_hf_to_gguf.py
    $convertScript = $null
    if (Test-Path (Join-Path $BinRoot "llama.cpp\convert_hf_to_gguf.py")) {
        $convertScript = Join-Path $BinRoot "llama.cpp\convert_hf_to_gguf.py"
    } elseif (Test-Path (Join-Path $BinRoot "llama.cpp\gguf-py\gguf\scripts\gguf_convert_endian.py")) {
        # llama.cpp Windows zip doesn't always ship convert_hf_to_gguf.py at top level.
        # We'll fall back to a venv pip install of 'gguf' and run the script from there.
        Write-Info "convert_hf_to_gguf.py not found in $BinRoot\llama.cpp; installing 'gguf' into venv."
    } else {
        Write-Info "llama.cpp not installed yet; installing 'gguf' package into venv as a fallback."
    }
    if (-not $convertScript) {
        & $VenvPy -m pip install -U gguf | Out-Null
    }
    # Always: install gguf into the venv as a safety net (the official package
    # ships convert_hf_to_gguf.py too).
    & $VenvPy -m pip show gguf | Out-Null
    if ($LASTEXITCODE -ne 0) { & $VenvPy -m pip install -U gguf | Out-Null }

    $outFile = Join-Path $mmprojDir "mmproj-joyai-vl-interaction-preview-f16.gguf"
    Write-Info "Converting mmproj to $outFile"
    & $VenvPy -m gguf.scripts.convert_hf_to_gguf `
        --mmproj `
        --outfile $outFile `
        --outtype f16 `
        $upstreamDir
    if ($LASTEXITCODE -ne 0) {
        throw "convert_hf_to_gguf.py --mmproj failed (exit $LASTEXITCODE)"
    }
    Assert-FileSize $outFile "main mmproj" 1000
}

# ---------------------------------------------------------------------------
# 7) SUMMARY: Qwen2.5-VL-3B-Instruct-GGUF
# ---------------------------------------------------------------------------
function Download-SummaryModel {
    Write-Host ""
    Write-Host "== SUMMARY MODEL ==" -ForegroundColor Cyan
    Write-Host "Target: $summaryDir"
    $repo = "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF"
    Write-Info "Downloading $repo -> $summaryDir"
    $rc = Invoke-Hf @("download", $repo,
        "--local-dir", $summaryDir,
        "--include", "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
        "--include", "Qwen2.5-VL-3B-Instruct-mmproj-f16.gguf"
    )
    if ($rc -ne 0) { throw "huggingface-cli download failed for summary repo" }
    Assert-FileSize (Join-Path $summaryDir "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf")     "summary gguf"   1700
    Assert-FileSize (Join-Path $summaryDir "Qwen2.5-VL-3B-Instruct-mmproj-f16.gguf") "summary mmproj" 1100
}

# ---------------------------------------------------------------------------
# 8) SHA256 (main model) - only if the file exists
# ---------------------------------------------------------------------------
function Print-Sha256 {
    param([string]$Path, [string]$Label)
    if (Test-Path $Path) {
        Write-Info "SHA256 ($Label):"
        $h = (Get-FileHash -Algorithm SHA256 $Path).Hash
        Write-Host "        $h"
    }
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " download-gguf-models.ps1" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " ModelsRoot  : $ModelsRoot"
Write-Host " BinRoot     : $BinRoot"
Write-Host " VenvPy      : $VenvPy"
Write-Host " Component   : $Component"
Write-Host " SkipMmproj  : $SkipMmproj"
Write-Host ""

if ($Component -in @("main","all")) {
    Download-MainModel
    Build-Mmproj
    Print-Sha256 (Join-Path $mainDir "joyai-vl-interaction-preview-iq4_nl-imat.gguf") "main gguf"
}
if ($Component -in @("summary","all")) {
    Download-SummaryModel
}

Write-Host ""
Write-Ok "Done. Models under $ModelsRoot"
Write-Host ""
Write-Host "Layout:" -ForegroundColor Yellow
Write-Host "  $mainDir"
Write-Host "  $mmprojDir"
Write-Host "  $summaryDir"
Write-Host ""