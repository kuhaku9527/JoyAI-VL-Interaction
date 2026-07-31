#!/usr/bin/env powershell
# Log + runtime-probe cleanup. Run manually, or schedule via
# Windows Task Scheduler (one-liner example at the bottom).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/log_maintenance.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/log_maintenance.ps1 -LogRetentionDays 7 -ProbeRetentionDays 1 -Apply
#
# Defaults: log files older than 14 days, probe JSON older than 1 day.
# Dry-run by default; pass -Apply to actually delete.

[CmdletBinding()]
param(
    [int]$LogRetentionDays = 14,
    [int]$ProbeRetentionDays = 1,
    [switch]$Apply,
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = $PSScriptRoot | Split-Path -Parent }

$logsDir   = Join-Path $RepoRoot "logs"
$svcLogs   = Join-Path $RepoRoot "services\.logs"
$probe     = Join-Path $RepoRoot "logs\vlm-runtime-props.json"
$now       = Get-Date
$cutoffLog   = $now.AddDays(-$LogRetentionDays)
$cutoffProbe = $now.AddDays(-$ProbeRetentionDays)
$isApply   = [bool]$Apply
$verb      = if ($isApply) { "DELETE" } else { "DRY-RUN" }

Write-Host "[$verb] log retention: $LogRetentionDays days, probe retention: $ProbeRetentionDays days" -ForegroundColor Cyan

function Get-OldFiles($dir, $cutoff) {
    if (-not (Test-Path $dir)) { return @() }
    Get-ChildItem $dir -File -ErrorAction SilentlyContinue |
        Where-Object { [DateTime]$_.LastWriteTime -lt [DateTime]$cutoff }
}

$oldSvc = @(Get-OldFiles $svcLogs $cutoffLog)
$oldTop = @(Get-OldFiles $logsDir $cutoffLog | Where-Object { $_.Name -match '\.(log|err\.log)$' })
$allOld = @($oldSvc + $oldTop)

Write-Host ""
Write-Host "Service log files (services\.logs + logs/*.log):" -ForegroundColor Cyan
$svcTotalSize = 0
if ($allOld.Count -gt 0) {
    foreach ($f in $allOld) {
        $age = $now - [DateTime]$f.LastWriteTime
        $sizeKB = [math]::Round($f.Length / 1KB, 1)
        $svcTotalSize += $f.Length
        $what = if ($isApply) { "DELETE" } else { "would delete" }
        $rel = $f.FullName.Substring($RepoRoot.Length + 1)
        Write-Host ("  [{0}] {1}  {2} KB  age={3:N1}d" -f $what, $rel, $sizeKB, $age.TotalDays)
    }
} else {
    Write-Host "  [keep] no service log files older than $LogRetentionDays days"
}

Write-Host ""
Write-Host "Runtime probe JSON:" -ForegroundColor Cyan
$probeAction = "KEEP"
if (Test-Path $probe) {
    $probeMtime = [DateTime](Get-Item $probe).LastWriteTime
    $age = $now - $probeMtime
    if ($probeMtime -lt $cutoffProbe) {
        $sizeKB = [math]::Round((Get-Item $probe).Length / 1KB, 1)
        $what = if ($isApply) { "DELETE" } else { "would delete" }
        Write-Host ("  [{0}] {1}  {2} KB  age={3:N1}d" -f $what, "logs/vlm-runtime-props.json", $sizeKB, $age.TotalDays)
        $probeAction = "DELETE"
    } else {
        Write-Host ("  [keep] logs/vlm-runtime-props.json  age={0:N1}d  (cutoff: {1}d)" -f $age.TotalDays, $ProbeRetentionDays)
    }
} else {
    Write-Host "  [skip] logs/vlm-runtime-props.json does not exist"
}

if ($isApply) {
    Write-Host ""
    foreach ($f in $allOld) { Remove-Item $f.FullName -Force }
    if ($probeAction -eq "DELETE") { Remove-Item $probe -Force }
    Write-Host ("[applied] freed ~{0} KB" -f [math]::Round($svcTotalSize / 1KB, 1)) -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[dry-run] pass -Apply to actually delete." -ForegroundColor DarkGray
    Write-Host "Schedule hint (optional):" -ForegroundColor DarkGray
    Write-Host "  schtasks /create /tn joyai-log-cleanup /sc daily /st 03:00 " -ForegroundColor DarkGray
    Write-Host "          /tr 'powershell -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\log_maintenance.ps1`" -Apply'" -ForegroundColor DarkGray
}
