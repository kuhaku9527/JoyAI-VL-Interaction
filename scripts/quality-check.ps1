# ---------------------------------------------------------------------------
# quality-check.ps1 — Windows variant of scripts/quality-check.sh.
# Runs locally (Git Bash / PowerShell) and inside any Windows CI runner.
#
# Usage:  .\scripts\quality-check.ps1            # lint + format check
#         .\scripts\quality-check.ps1 -Fix        # also auto-fix lint issues
# ---------------------------------------------------------------------------
param(
    [switch]$Fix
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command ruff -ErrorAction SilentlyContinue)) {
    Write-Error "ruff not found on PATH. Install with: pip install ruff"
    exit 1
}

Write-Host "==> ruff version"
ruff --version

Write-Host "==> ruff check (lint)"
if ($Fix) {
    ruff check . --fix
} else {
    ruff check .
}

Write-Host "==> ruff format --check"
ruff format --check .

Write-Host "==> quality gate passed"
