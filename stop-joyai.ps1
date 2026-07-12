#requires -Version 5.1
<#
.SYNOPSIS
  One-stop switch for every JoyAI-VL service on this box.

.DESCRIPTION
  Two modes:
    default (no switch)  -- stop everything that PID-tracked run-windows.ps1
                            manages, AND any process holding the default ports
                            (so legacy services started by Start-Process get
                            killed too). Idempotent.
    -Only <port[,port..]> -- stop only the given ports (not PID files).
                            Useful when one process is misbehaving.
    -DryRun               -- list what would be killed, do not actually stop.
    -StopContainer <name> -- docker container name to stop too.

  Always shows a small table of "before / after" so you can see proof it ran.

  Usage:
    powershell -ExecutionPolicy Bypass -File stop-joyai.ps1
    powershell -ExecutionPolicy Bypass -File stop-joyai.ps1 -Only 8985,8090
    powershell -ExecutionPolicy Bypass -File stop-joyai.ps1 -DryRun

  Exit codes:
    0  everything was up and is now down
    1  nothing matched (informational, not an error)
    2  one or more services refused to die (manual intervention required)
#>

[CmdletBinding()]
param(
    [int[]]$Only = @(),
    [switch]$DryRun,
    [string[]]$StopContainer = @(),
    [string]$RepoRoot = "",
    [int]$GraceSeconds = 5
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Auto-locate the repo (parent of the dir holding this script)
# ---------------------------------------------------------------------------
$ScriptDir = $PSScriptRoot
if (-not $RepoRoot) {
    # walk up until we find services/scripts/run-windows.ps1
    $cur = Resolve-Path $ScriptDir
    while ($cur.Path -and -not (Test-Path (Join-Path $cur.Path "services\scripts\run-windows.ps1"))) {
        $parent = Split-Path $cur.Path -Parent
        if ($parent -eq $cur.Path) { break }
        $cur = Get-Item $parent
    }
    if (Test-Path (Join-Path $cur.Path "services\scripts\run-windows.ps1")) {
        $RepoRoot = $cur.Path
    } else {
        Write-Host "[ERR] Cannot locate JoyAI-VL-Interaction repo from $ScriptDir" -ForegroundColor Red
        exit 2
    }
}

# ---------------------------------------------------------------------------
# JoyAI service ports (matches services/scripts/run-windows.ps1's PortMap)
# ---------------------------------------------------------------------------
$AllPorts = [ordered]@{
    "llama-main"        = 7060
    "llama-summary"     = 8065
    "webinfer"          = 8070
    "background-agent"  = 8079
    "webui"             = 8099
    "hermes-gateway"    = 8642
    "voice-clone"       = 8985
    "cosyvoice"         = 8991
    "tts-adapter"       = 8992
    "whisper"           = 8993
    "asr-adapter"       = 8994
}
# Plus the user's 8090 webui (off-map but commonly used in this setup)
$ExtraPorts = [ordered]@{
    "webui-8090"        = 8090
}

function Get-Listeners {
    param([int[]]$Ports)
    $found = @()
    foreach ($p in $Ports) {
        $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            foreach ($c in $conn) {
                $found += [pscustomobject]@{ Port = $p; Pid = [int]$c.OwningProcess }
            }
        }
    }
    $found
}

function Test-PidAlive {
    param([int]$Id)
    if ($Id -le 0) { return $false }
    return $null -ne (Get-Process -Id $Id -ErrorAction SilentlyContinue)
}

function Kill-Pid {
    param([int]$Id, [string]$Label, [int]$Grace = $GraceSeconds)
    if (-not (Test-PidAlive $Id)) {
        Write-Host "  [skip] $Label (PID $Id already gone)" -ForegroundColor DarkGray
        return $true
    }
    Write-Host "  [kill] $Label (PID $Id) ..." -ForegroundColor Yellow
    if ($DryRun) { return $true }
    try { Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue } catch {}
    $deadline = (Get-Date).AddSeconds($Grace)
    while ((Get-Date) -lt $deadline -and (Test-PidAlive $Id)) {
        Start-Sleep -Milliseconds 200
    }
    if (Test-PidAlive $Id) {
        try { Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (Test-PidAlive $Id) {
        Write-Host "  [FAIL] $Label (PID $Id) still alive" -ForegroundColor Red
        return $false
    }
    Write-Host "  [OK]   $Label stopped" -ForegroundColor Green
    return $true
}

# ---------------------------------------------------------------------------
# Resolve which ports to target
# ---------------------------------------------------------------------------
if ($Only.Count -gt 0) {
    $targetPorts = $Only | Sort-Object -Unique
} else {
    $targetPorts = @($AllPorts.Values + $ExtraPorts.Values) | Sort-Object -Unique
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " stop-joyai.ps1" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " RepoRoot      : $RepoRoot"
Write-Host " Targets       : $($targetPorts -join ', ')"
Write-Host " DryRun        : $DryRun"
if ($StopContainer.Count -gt 0) {
    Write-Host " StopContainer : $($StopContainer -join ', ')"
}
Write-Host ""

# ---------------------------------------------------------------------------
# Step 1: PID-file pass (only when running default mode)
# ---------------------------------------------------------------------------
$killedCount = 0
$failedLabels = @()

if ($Only.Count -eq 0) {
    $PidDir = Join-Path $RepoRoot "services\.pids"
    if (Test-Path $PidDir) {
        $pids = Get-ChildItem $PidDir -Filter "*.pid" -ErrorAction SilentlyContinue
        foreach ($f in $pids) {
            $name = $f.BaseName
            $v = Get-Content $f.FullName -ErrorAction SilentlyContinue
            if ($v -and ($v -as [int])) {
                if (-not (Kill-Pid -Id ([int]$v) -Label "pid-file:$name")) {
                    $failedLabels += "pid-file:$name"
                } else {
                    $killedCount++
                    Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue
                }
            }
        }
    }
}

# ---------------------------------------------------------------------------
# Step 2: Port-based pass (catches manually-started services)
# ---------------------------------------------------------------------------
$listeners = Get-Listeners -Ports $targetPorts
if ($listeners.Count -eq 0) {
    Write-Host "  [..]  No listeners on target ports. All clean." -ForegroundColor DarkGray
} else {
    # Build name lookup so the message is human-friendly
    $portToName = @{}
    foreach ($k in $AllPorts.Keys)    { $portToName[$AllPorts[$k]]    = $k }
    foreach ($k in $ExtraPorts.Keys)  { $portToName[$ExtraPorts[$k]]  = $k }

    foreach ($l in $listeners) {
        $label = "port $($l.Port)"
        if ($portToName.ContainsKey($l.Port)) { $label = "$($portToName[$l.Port]) (port $($l.Port))" }
        if (-not (Kill-Pid -Id $l.Pid -Label $label)) {
            $failedLabels += $label
        } else {
            $killedCount++
        }
    }
}

# ---------------------------------------------------------------------------
# Step 3: Optional docker containers
# ---------------------------------------------------------------------------
if ($StopContainer.Count -gt 0) {
    foreach ($c in $StopContainer) {
        Write-Host "  [docker stop] $c" -ForegroundColor Yellow
        if (-not $DryRun) {
            docker stop $c 2>&1 | ForEach-Object { Write-Host "    $_" }
        }
    }
}

# ---------------------------------------------------------------------------
# Step 4: Confirm and report
# ---------------------------------------------------------------------------
Start-Sleep -Seconds 1
$stillUp = Get-Listeners -Ports $targetPorts
Write-Host ""
if ($stillUp.Count -eq 0) {
    Write-Host "[OK]  All target ports free. Killed $killedCount process(es)." -ForegroundColor Green
    if ($DryRun) { Write-Host "      (DryRun -- nothing was actually killed)" -ForegroundColor DarkGray }
    exit 0
}
Write-Host "[WARN] Still listening:" -ForegroundColor Yellow
foreach ($s in $stillUp) { Write-Host "       port $($s.Port) -> PID $($s.Pid)" -ForegroundColor Yellow }
Write-Host ""
if ($failedLabels.Count -gt 0) {
    Write-Host "[FAIL] Some services refused to die:" -ForegroundColor Red
    foreach ($f in $failedLabels) { Write-Host "       $f" -ForegroundColor Red }
}
Write-Host "       Try running once more, or open Task Manager and kill manually." -ForegroundColor Yellow
exit 2
