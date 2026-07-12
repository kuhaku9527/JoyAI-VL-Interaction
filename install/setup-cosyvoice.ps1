#requires -Version 5.1
<#
.SYNOPSIS
  Install CosyVoice3 (Fun-CosyVoice3-0.5B-2512) into a conda env named 'cosyvoice'
  (Python 3.10) under D:\AI\tools\CosyVoice\.

.DESCRIPTION
  Steps:
    1. Ensures conda is on PATH (looks in standard locations).
    2. Creates the 'cosyvoice' env (Python 3.10) if missing.
    3. git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git
    4. pip install -r requirements.txt
    5. pip install -U torch torchvision torchaudio --index-url .../cu128
    6. snapshot_download Fun-CosyVoice3-0.5B-2512
    7. Verifies: python -c "from cosyvoice.cli.cosyvoice import AutoModel; print('ok')"

  Exposes $env:COSYVOICE_DIR and $env:COSYVOICE_MODEL_DIR.

  Reference: docs/lightweight-replacement.md
#>

[CmdletBinding()]
param(
    [string]$ToolsRoot  = "D:\AI\tools",
    [string]$ModelsRoot = "D:\AI\models",
    [string]$CondaExe   = "",
    [string]$EnvName    = "cosyvoice",
    [switch]$ForceReclone
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

# ---------------------------------------------------------------------------
# 1) Resolve conda
# ---------------------------------------------------------------------------
if (-not $CondaExe) {
    $candidates = @(
        (Join-Path $env:USERPROFILE "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:USERPROFILE "anaconda3\Scripts\conda.exe"),
        "C:\ProgramData\miniconda3\Scripts\conda.exe",
        (Get-Command "conda" -ErrorAction SilentlyContinue).Source
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    $CondaExe = $candidates
}
if (-not $CondaExe) {
    throw "conda not found. Install Miniconda3 (https://docs.conda.io/en/latest/miniconda.html) and re-run."
}
Write-Ok "conda: $CondaExe"

# ---------------------------------------------------------------------------
# 2) Ensure git
# ---------------------------------------------------------------------------
if (-not (Test-Command "git")) {
    throw "git not found on PATH. Install Git for Windows first."
}
Write-Ok "git: $(& git --version)"

# ---------------------------------------------------------------------------
# 3) Create 'cosyvoice' env if missing
# ---------------------------------------------------------------------------
$envList = (& $CondaExe env list 2>$null) -join "`n"
if ($envList -notmatch "(?m)^$EnvName\s") {
    Write-Info "Creating conda env '$EnvName' (Python 3.10)..."
    & $CondaExe create -n $EnvName -y python=3.10
    if ($LASTEXITCODE -ne 0) { throw "conda create failed" }
} else {
    Write-Ok "conda env '$EnvName' already exists"
}

# Build the env's python.exe path
$condaRoot = (& $CondaExe info --base 2>$null).Trim()
if (-not $condaRoot) { $condaRoot = Split-Path (Split-Path $CondaExe -Parent) -Parent }
$envPy = Join-Path $condaRoot "envs\$EnvName\python.exe"
if (-not (Test-Path $envPy)) {
    throw "Env python not found at $envPy"
}
Write-Ok "env python: $envPy"

# ---------------------------------------------------------------------------
# 4) git clone CosyVoice --recursive
# ---------------------------------------------------------------------------
$cosyDir = Join-Path $ToolsRoot "CosyVoice"
$marker  = Join-Path $cosyDir "cosyvoice\cli\cosyvoice.py"
if ((Test-Path $marker) -and -not $ForceReclone) {
    Write-Ok "CosyVoice already at $cosyDir"
} else {
    if (Test-Path $cosyDir) { Remove-Item -Recurse -Force $cosyDir }
    Write-Info "Cloning CosyVoice (recursive) into $cosyDir"
    & git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git $cosyDir
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
}
if (-not (Test-Path $marker)) {
    throw "CosyVoice clone looks incomplete (no $marker)"
}
Write-Ok "CosyVoice: $cosyDir"

# ---------------------------------------------------------------------------
# 5) pip install -r requirements.txt  +  torch cu128
# ---------------------------------------------------------------------------
Push-Location $cosyDir
try {
    $reqFile = Join-Path $cosyDir "requirements.txt"
    if (-not (Test-Path $reqFile)) {
        throw "requirements.txt missing at $reqFile"
    }
    Write-Info "pip install -r requirements.txt (in env $EnvName)"
    & $envPy -m pip install -r $reqFile
    if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements.txt failed" }
    Write-Ok "requirements.txt installed"

    Write-Info "pip install torch cu128 (override any cpu wheel)"
    & $envPy -m pip install -U torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
    if ($LASTEXITCODE -ne 0) { throw "torch cu128 install failed" }
    Write-Ok "torch cu128 installed"

    # Verify
    & $envPy -c "import torch; print('  torch', torch.__version__, 'cuda', torch.version.cuda, 'avail', torch.cuda.is_available())"
} finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# 6) snapshot_download Fun-CosyVoice3-0.5B-2512
# ---------------------------------------------------------------------------
$modelDir = Join-Path $ModelsRoot "tts\CosyVoice3-0.5B"
if (-not (Test-Path $modelDir)) { New-Item -ItemType Directory -Path $modelDir -Force | Out-Null }
$sentinel = Join-Path $modelDir "cosyvoice3.yaml"
if (-not (Test-Path $sentinel)) {
    Write-Info "snapshot_download FunAudioLLM/Fun-CosyVoice3-0.5B-2512 -> $modelDir"
    & $envPy -c "from huggingface_hub import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir=r'$($modelDir -replace '\\','\\')')"
    if ($LASTEXITCODE -ne 0) { throw "snapshot_download failed" }
}
if (-not (Test-Path $sentinel)) {
    Write-Warn "Could not find cosyvoice3.yaml at $sentinel. Model snapshot may be incomplete."
} else {
    Write-Ok "CosyVoice3 model: $modelDir"
}

# ---------------------------------------------------------------------------
# 7) Verify
# ---------------------------------------------------------------------------
Write-Info "Verifying cosyvoice import..."
& $envPy -c "from cosyvoice.cli.cosyvoice import AutoModel; print('  AutoModel import ok')"
if ($LASTEXITCODE -ne 0) {
    Write-Warn "AutoModel import failed. The env may need a manual 'pip install -e .' from $cosyDir."
}

# ---------------------------------------------------------------------------
# Persist env hint
# ---------------------------------------------------------------------------
$env:COSYVOICE_DIR       = $cosyDir
$env:COSYVOICE_MODEL_DIR = $modelDir
$env:COSYVOICE_PY        = $envPy
$env:COSYVOICE_CONDA_ENV = $EnvName
$envHint = Join-Path (Split-Path $PSScriptRoot -Parent) "services\.install-windows.env"
$lines = @(
    "COSYVOICE_DIR=$cosyDir"
    "COSYVOICE_MODEL_DIR=$modelDir"
    "COSYVOICE_PY=$envPy"
    "COSYVOICE_CONDA_ENV=$EnvName"
)
if (Test-Path $envHint) {
    $existing = Get-Content $envHint
    foreach ($new in $lines) {
        $key = ($new -split "=", 2)[0]
        $replaced = $false
        $existing = foreach ($line in $existing) {
            if ($line -match "^$key=") { $replaced = $true; $new } else { $line }
        }
        if (-not $replaced) { $existing += $new }
    }
    Set-Content -Path $envHint -Value $existing -Encoding UTF8
} else {
    Set-Content -Path $envHint -Value $lines -Encoding UTF8
}

Write-Host ""
Write-Ok "CosyVoice installed at $cosyDir"
Write-Ok "Model at $modelDir"
Write-Ok "Python: $envPy"
Write-Host ""
Write-Host "Next step (manual test):" -ForegroundColor Yellow
Write-Host "  conda activate $EnvName ; cd `"$cosyDir\runtime\python\fastapi`"" -ForegroundColor Gray
Write-Host "  python server.py --port 8991 --model_dir `"$modelDir`"" -ForegroundColor Gray