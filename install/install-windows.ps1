#requires -Version 5.1
<#
.SYNOPSIS
  One-shot installer for JoyAI-VL-Interaction on native Windows (RTX 5060 Ti / sm_120).

.DESCRIPTION
  Sets up:
    - Python 3.12 (winget / manual)
    - uv package manager
    - git, ffmpeg (best-effort via winget)
    - CUDA 12.8 toolchain presence check (does NOT auto-install)
    - Conda env 'cosyvoice' (Python 3.10) - skipped with -SkipConda
    - venv at services\.venv (Python 3.12) and editable installs of all 5 services
    - Optional PyTorch cu128 install into the venv

  This script does NOT install vLLM or vLLM-Omni. The main model is served
  by llama.cpp (see setup-llama-cpp.ps1) and the audio models are served by
  whisper.cpp / CosyVoice directly.

  Reference: docs/lightweight-replacement.md
#>

[CmdletBinding()]
param(
    [switch]$SkipCuda,
    [switch]$SkipConda,
    [switch]$SkipTorch,
    [switch]$SkipEditable,
    [string]$Python312Path,
    [string]$RepoRoot,
    [string]$ModelsRoot = "D:\AI\models",
    [string]$BinRoot    = "D:\AI\bin",
    [string]$ToolsRoot  = "D:\AI\tools"
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "Continue"

# ---------------------------------------------------------------------------
# Resolve repo root
# ---------------------------------------------------------------------------
if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
if (-not (Test-Path $RepoRoot)) {
    throw "Repo root not found: $RepoRoot"
}
$ServicesDir = Join-Path $RepoRoot "services"
$InstallDir  = Join-Path $RepoRoot "install"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " JoyAI-VL-Interaction :: Windows native installer" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " RepoRoot     : $RepoRoot"
Write-Host " ServicesDir  : $ServicesDir"
Write-Host " ModelsRoot   : $ModelsRoot"
Write-Host " BinRoot      : $BinRoot"
Write-Host " ToolsRoot    : $ToolsRoot"
Write-Host " SkipCuda     : $SkipCuda"
Write-Host " SkipConda    : $SkipConda"
Write-Host " SkipTorch    : $SkipTorch"
Write-Host " Python312Path: $(if ($Python312Path) { $Python312Path } else { '<auto>' })"
Write-Host ""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Ok   { param($m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Info { param($m) Write-Host "  [..]   $m" -ForegroundColor DarkGray }
function Write-Warn { param($m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "  [FAIL] $m" -ForegroundColor Red }

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-Dir {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        Write-Info "Creating directory: $Path"
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

# ---------------------------------------------------------------------------
# 1) Sanity: this is Windows, PowerShell 5.1+
# ---------------------------------------------------------------------------
if ($IsWindows -ne $true) {
    throw "This script must run on Windows. Detected: $env:OS"
}
$psv = $PSVersionTable.PSVersion
if ($psv.Major -lt 5) {
    throw "PowerShell 5.1 or newer required (detected $psv). Update with: winget install Microsoft.PowerShell"
}
Write-Ok "PowerShell $psv on Windows"

# ---------------------------------------------------------------------------
# 2) Python 3.12
# ---------------------------------------------------------------------------
function Resolve-Python312 {
    param([string]$Manual)
    if ($Manual -and (Test-Path $Manual)) {
        Write-Ok "Using user-provided Python: $Manual"
        return (Resolve-Path $Manual).Path
    }
    if (Test-Command "py") {
        $py = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null)
        if ($py -and (Test-Path $py)) {
            Write-Ok "Found Python 3.12 via 'py' launcher: $py"
            return $py
        }
    }
    foreach ($cand in @("python3.12", "python")) {
        if (Test-Command $cand) {
            $ver = & $cand -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($ver -eq "3.12") {
                $py = (& $cand -c "import sys; print(sys.executable)" 2>$null)
                Write-Ok "Found Python 3.12 on PATH: $py"
                return $py
            }
        }
    }
    return $null
}

$pythonExe = Resolve-Python312 -Manual $Python312Path
if (-not $pythonExe) {
    Write-Warn "Python 3.12 not found."
    if (Test-Command "winget") {
        Write-Info "Installing Python 3.12 via winget..."
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        $pythonExe = Resolve-Python312 -Manual $Python312Path
    } else {
        Write-Err "Please install Python 3.12 manually from https://www.python.org/downloads/release/python-3128/ and re-run with -Python312Path <path-to-python.exe>"
        throw "Python 3.12 missing"
    }
}
if (-not $pythonExe) {
    throw "Python 3.12 still not found after install attempt"
}
Write-Ok "Python at $pythonExe"
& $pythonExe --version

# ---------------------------------------------------------------------------
# 3) uv
# ---------------------------------------------------------------------------
$uv = $null
if (Test-Command "uv") {
    $uv = (Get-Command "uv").Source
    Write-Ok "uv already installed: $uv"
} else {
    Write-Info "Installing uv via official installer..."
    try {
        Invoke-RestMethod -Uri https://astral.sh/uv/install.ps1 | Invoke-Expression
        $uvHome = Join-Path $env:USERPROFILE ".local\bin"
        if (Test-Path (Join-Path $uvHome "uv.exe")) {
            $env:Path = "$uvHome;$env:Path"
            $uv = (Get-Command "uv").Source
            Write-Ok "uv installed: $uv"
        }
    } catch {
        Write-Warn "uv installer failed: $_"
    }
    if (-not $uv) {
        Write-Err "Failed to install uv. Install manually: irm https://astral.sh/uv/install.ps1 | iex"
        throw "uv missing"
    }
}
& $uv --version

# ---------------------------------------------------------------------------
# 4) git
# ---------------------------------------------------------------------------
if (Test-Command "git") {
    Write-Ok "git: $(& git --version)"
} else {
    if (Test-Command "winget") {
        Write-Info "Installing git via winget..."
        winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    }
    if (Test-Command "git") {
        Write-Ok "git: $(& git --version)"
    } else {
        Write-Warn "git not found. Some scripts (setup-cosyvoice) will fail until you install it."
    }
}

# ---------------------------------------------------------------------------
# 5) ffmpeg (used by webui / CosyVoice / whisper)
# ---------------------------------------------------------------------------
if (Test-Command "ffmpeg") {
    Write-Ok "ffmpeg: $(& ffmpeg -version | Select-Object -First 1)"
} else {
    if (Test-Command "winget") {
        Write-Info "Installing ffmpeg via winget..."
        winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    }
    if (Test-Command "ffmpeg") {
        Write-Ok "ffmpeg: $(& ffmpeg -version | Select-Object -First 1)"
    } else {
        Write-Warn "ffmpeg not found. The webui video pipeline needs it; install Gyan.FFmpeg manually."
    }
}

# ---------------------------------------------------------------------------
# 6) CUDA 12.8 toolchain (informational; do NOT auto-install the multi-GB toolkit)
# ---------------------------------------------------------------------------
if ($SkipCuda) {
    Write-Info "Skipping CUDA check (-SkipCuda)."
} else {
    Write-Info "Checking for CUDA / NVIDIA driver / cu128 runtime..."
    $cudaRoot = $env:CUDA_PATH_V12_8
    if (-not $cudaRoot) { $cudaRoot = $env:CUDA_PATH }
    $hasNvidiaSmi = Test-Command "nvidia-smi"
    if ($hasNvidiaSmi) {
        $smi = (& nvidia-smi --query-gpu=name,driver_version --format=csv,noheader) 2>$null
        if ($smi) {
            Write-Ok "nvidia-smi: $smi"
        } else {
            Write-Warn "nvidia-smi present but returned no output"
        }
    } else {
        Write-Warn "nvidia-smi not found. Install NVIDIA driver >= 560 first."
    }
    if ($cudaRoot -and (Test-Path $cudaRoot)) {
        Write-Ok "CUDA toolkit at $cudaRoot"
    } else {
        Write-Warn "CUDA toolkit not detected at %CUDA_PATH%. For PyTorch cu128 wheel you only need the driver; for building llama.cpp from source you'd need the toolkit."
    }
}

# ---------------------------------------------------------------------------
# 7) Create D:\AI directory tree
# ---------------------------------------------------------------------------
foreach ($d in @($ModelsRoot, $BinRoot, $ToolsRoot, (Join-Path $ModelsRoot "main"), (Join-Path $ModelsRoot "summary"), (Join-Path $ModelsRoot "asr"), (Join-Path $ModelsRoot "tts"))) {
    Ensure-Dir $d
}
Write-Ok "ModelsRoot/BinRoot/ToolsRoot ready"

# ---------------------------------------------------------------------------
# 8) Conda env 'cosyvoice' (Python 3.10) - optional
# ---------------------------------------------------------------------------
function Get-CondaExe {
    $candidates = @(
        (Join-Path $env:USERPROFILE "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:USERPROFILE "anaconda3\Scripts\conda.exe"),
        "C:\ProgramData\miniconda3\Scripts\conda.exe",
        (Get-Command "conda" -ErrorAction SilentlyContinue).Source
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    return $candidates
}

if ($SkipConda) {
    Write-Info "Skipping conda env creation (-SkipConda)."
    $condaExe = Get-CondaExe
    if ($condaExe) { Write-Info "(Conda detected at $condaExe; not creating env.)" }
} else {
    $condaExe = Get-CondaExe
    if (-not $condaExe) {
        Write-Warn "conda not found. Install Miniconda3 from https://docs.conda.io/en/latest/miniconda.html, then re-run with the same flags. Skipping cosyvoice env creation for now."
    } else {
        Write-Ok "conda: $condaExe"
        $envList = (& $condaExe env list 2>$null) -join "`n"
        if ($envList -match "(?m)^cosyvoice\s") {
            Write-Ok "conda env 'cosyvoice' already exists"
        } else {
            Write-Info "Creating conda env 'cosyvoice' (Python 3.10)..."
            & $condaExe create -n cosyvoice -y python=3.10
            if ($LASTEXITCODE -ne 0) { throw "conda env creation failed" }
            Write-Ok "conda env 'cosyvoice' created"
        }
    }
}

# ---------------------------------------------------------------------------
# 9) venv at services\.venv with Python 3.12
# ---------------------------------------------------------------------------
$venvDir = Join-Path $ServicesDir ".venv"
if (Test-Path $venvDir) {
    Write-Ok "venv already exists at $venvDir (will reuse)"
} else {
    Write-Info "Creating venv at $venvDir (Python 3.12)..."
    & $uv venv --python $pythonExe $venvDir
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed" }
    Write-Ok "venv created"
}
$venvPy = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    throw "venv python missing at $venvPy"
}
Write-Ok "venv python: $venvPy"

# ---------------------------------------------------------------------------
# 10) PyTorch cu128 (into venv) - optional
# ---------------------------------------------------------------------------
if ($SkipTorch) {
    Write-Info "Skipping PyTorch install (-SkipTorch)."
} else {
    Write-Info "Installing PyTorch cu128 into venv..."
    & $uv pip install --python $venvPy -U torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "PyTorch cu128 install failed. You can re-run with -SkipTorch and install manually."
    } else {
        Write-Ok "PyTorch cu128 installed"
        & $venvPy -c "import torch; print('  torch', torch.__version__, 'cuda', torch.version.cuda, 'avail', torch.cuda.is_available())"
    }
}

# ---------------------------------------------------------------------------
# 11) Editable installs of the services (memory-store included: run-windows.ps1
#     launches it via $VenvPy, so it must be installed here too)
# ---------------------------------------------------------------------------
if ($SkipEditable) {
    Write-Info "Skipping editable installs (-SkipEditable)."
} else {
    $servicePackages = @("webinfer", "webui", "background-agent", "voice-clone", "asr", "tts", "memory-store")
    foreach ($pkg in $servicePackages) {
        $pkgDir = Join-Path $ServicesDir $pkg
        if (-not (Test-Path $pkgDir)) {
            Write-Warn "Skipping $pkg (directory not found: $pkgDir)"
            continue
        }
        Write-Info "Editable install: $pkg"
        & $uv pip install --python $venvPy -e $pkgDir
        if ($LASTEXITCODE -ne 0) {
            throw "Editable install of $pkg failed"
        }
    }
    Write-Ok "Editable installs complete"
}

# ---------------------------------------------------------------------------
# 12) Persist helpful env hints
# ---------------------------------------------------------------------------
$envHint = Join-Path $ServicesDir ".install-windows.env"
$llamaServerExe = Join-Path $BinRoot "llama.cpp\llama-server.exe"
$whisperServerExe = Join-Path $BinRoot "whisper.cpp\whisper-server.exe"
$llamaHint = if (Test-Path $llamaServerExe) { $llamaServerExe } else { "" }
$whisperHint = if (Test-Path $whisperServerExe) { $whisperServerExe } else { "" }
$hintLines = @(
    "# Generated by install-windows.ps1 on $(Get-Date -Format o)"
    "JOYAI_REPO_ROOT=$RepoRoot"
    "JOYAI_MODELS_ROOT=$ModelsRoot"
    "JOYAI_BIN_ROOT=$BinRoot"
    "JOYAI_TOOLS_ROOT=$ToolsRoot"
    "JOYAI_VENV_PY=$venvPy"
    "LLAMA_SERVER=$llamaHint"
    "WHISPER_SERVER=$whisperHint"
    "COSYVOICE_DIR=$(Join-Path $ToolsRoot 'CosyVoice')"
    "COSYVOICE_MODEL_DIR=$(Join-Path $ModelsRoot 'tts\CosyVoice3-0.5B')"
)
Set-Content -Path $envHint -Value $hintLines -Encoding UTF8
Write-Ok "Wrote env hints to $envHint"

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " install-windows.ps1 :: done" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Verified:" -ForegroundColor Yellow
Write-Host "  python : $(& $pythonExe --version 2>&1)"
Write-Host "  uv     : $(& $uv --version 2>&1)"
if (Test-Command "git")    { Write-Host "  git    : $(& git --version 2>&1)" } else { Write-Host "  git    : <missing>" }
if (Test-Command "ffmpeg") { Write-Host "  ffmpeg : $(& ffmpeg -version | Select-Object -First 1)" } else { Write-Host "  ffmpeg : <missing>" }
if (Test-Command "nvidia-smi") { Write-Host "  gpu    : $(& nvidia-smi --query-gpu=name --format=csv,noheader)" } else { Write-Host "  gpu    : <nvidia-smi missing>" }
Write-Host "  venv   : $venvPy"
Write-Host ""
Write-Host "Next steps (copy/paste):" -ForegroundColor Yellow
Write-Host "  1) Download GGUF models:" -ForegroundColor White
Write-Host "       powershell -ExecutionPolicy Bypass -File .\install\download-gguf-models.ps1 -Component all" -ForegroundColor Gray
Write-Host "  2) Install llama.cpp:" -ForegroundColor White
Write-Host "       powershell -ExecutionPolicy Bypass -File .\install\setup-llama-cpp.ps1" -ForegroundColor Gray
Write-Host "  3) Install whisper.cpp:" -ForegroundColor White
Write-Host "       powershell -ExecutionPolicy Bypass -File .\install\setup-whisper-cpp.ps1" -ForegroundColor Gray
Write-Host "  4) Install CosyVoice (conda env 'cosyvoice', Python 3.10):" -ForegroundColor White
Write-Host "       powershell -ExecutionPolicy Bypass -File .\install\setup-cosyvoice.ps1" -ForegroundColor Gray
Write-Host "  5) Install hermes-agent:" -ForegroundColor White
Write-Host "       powershell -ExecutionPolicy Bypass -File .\install\setup-hermes.ps1" -ForegroundColor Gray
Write-Host "  6) Launch everything:" -ForegroundColor White
Write-Host "       cd services; powershell -ExecutionPolicy Bypass -File .\scripts\run-windows.ps1" -ForegroundColor Gray
Write-Host ""