#requires -Version 7.0
<#
.SYNOPSIS
  Live "log terminal" for the JoyAI-VL service stack.

.DESCRIPTION
  Tails the scattered service log files in services/.logs/ in real time,
  tagged and color-coded per service, with optional substring filter and
  time-window slicing. This is the missing "log terminal" layer on top of
  the existing file-based logging (Start-Transcript launcher log, per-service
  *.log / *.err.log, drift-gate / vlm-probe JSON, webui access log).

  Forward-compatible with the Q2 logging spec (ADR-0014): when
  logs/events/*.jsonl exists (or -Jsonl is forced), lines are parsed as JSON
  events and rendered as "ts | service | event | level | extra" per ADR-0014.

  Requires PowerShell 7+ (pwsh). Multi-file real-time follow is not supported
  on Windows PowerShell 5.1.

.EXAMPLE
  pwsh scripts/tail_logs.ps1
  pwsh scripts/tail_logs.ps1 -Filter "circuit_breaker"
  pwsh scripts/tail_logs.ps1 -Since 1h -Services webui,memory-store
  pwsh scripts/tail_logs.ps1 -All -Once -Tail 20
#>
[CmdletBinding()]
param(
    [int]$Tail = 50,
    [string]$Filter = "",
    [string[]]$Services = @(),
    [switch]$All,
    [switch]$Jsonl,
    [switch]$Once,
    [string]$Since = "",
    [switch]$IncludeLauncher
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repoRoot = Split-Path $PSScriptRoot -Parent
$logDir = Join-Path $repoRoot "services" ".logs"
$eventsDir = Join-Path $repoRoot "logs" "events"

# --- service -> color map (falls back to Cyan for unknown) ---
$colorMap = @{
    "webui"        = "Green"
    "memory-store" = "Cyan"
    "webinfer"     = "Magenta"
    "llama-main"   = "Yellow"
    "vllm-llama"   = "Yellow"
    "asr"          = "DarkYellow"
    "kws"          = "DarkCyan"
    "tts"          = "DarkGreen"
}
$defaultColor = "White"

function ColorFor($svc) {
    if ($colorMap.ContainsKey($svc)) { return $colorMap[$svc] }
    return $defaultColor
}

function Parse-Since([string]$raw) {
    if (-not $raw) { return $null }
    if ($raw -match '^(\d+)\s*([hms])$') {
        $n = [int]$Matches[1]; $u = $Matches[2]
        switch ($u) {
            'h' { return [timespan]::FromHours($n) }
            'm' { return [timespan]::FromMinutes($n) }
            's' { return [timespan]::FromSeconds($n) }
        }
    }
    Write-Warning "Cannot parse -Since '$raw' (expected e.g. 1h, 30m, 90s). Ignoring time filter."
    return $null
}

function LineTimestamp([string]$line) {
    # webui.err.log: "2026-07-31 23:36:13,088 - __main__ - INFO - ..."
    # also accept ISO "2026-07-31T23:36:13"
    if ($line -match '(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})') {
        try { return [datetime]::Parse($Matches[1]) } catch { }
    }
    return $null
}

$span = Parse-Since $Since
$cutoff = if ($span) { (Get-Date).Subtract($span) } else { $null }

# --- discover files ---
$candidates = @()
if (Test-Path $logDir) {
    $errFiles = Get-ChildItem -Path $logDir -Filter "*.err.log" -File
    $candidates += $errFiles
    if ($All) {
        $candidates += Get-ChildItem -Path $logDir -Filter "*.log" -File |
            Where-Object { $_.Name -notlike "*.err.log" }
    }
}
if ($IncludeLauncher) {
    $launcherDir = Join-Path $repoRoot "logs"
    if (Test-Path $launcherDir) {
        $candidates += Get-ChildItem -Path $launcherDir -Filter "launcher-*.log" -File
    }
}

# filter by -Services (match the base name, e.g. "webui" matches webui.err.log)
if ($Services.Count -gt 0) {
    $candidates = $candidates | Where-Object {
        $base = $_.BaseName -replace '\.err$', ''
        $Services -contains $base
    }
}

$files = @($candidates | Select-Object -ExpandProperty FullName)
if ($files.Count -eq 0) {
    Write-Host "[tail_logs] No log files found in $logDir" -ForegroundColor Red
    exit 0
}

# --- JSONL mode (Q2 spec) ---
$useJsonl = $Jsonl -or (Test-Path $eventsDir)
if ($useJsonl) {
    $eventFiles = @()
    if (Test-Path $eventsDir) {
        $eventFiles = @(Get-ChildItem -Path $eventsDir -Filter "*.jsonl" -File | Select-Object -ExpandProperty FullName)
        if ($Services.Count -gt 0) {
            $eventFiles = @($eventFiles | Where-Object {
                $svcName = ($_.BaseName -split '-')[0]
                $Services -contains $svcName
            })
        }
    }
    if ($eventFiles.Count -eq 0) {
        Write-Host "[tail_logs] JSONL dir not present; falling back to text mode." -ForegroundColor DarkGray
        $useJsonl = $false
    }
}

if ($useJsonl) {
    Write-Host ("[tail_logs] JSONL mode :: " + ($eventFiles -join ", ")) -ForegroundColor DarkGray
    Write-Host ("[tail_logs] filter='{0}' since='{1}'" -f $Filter, $Since) -ForegroundColor DarkGray
    Write-Host ("-" * 60) -ForegroundColor DarkGray
    try {
        Get-Content -Path $eventFiles -Wait:(-not $Once) -Tail $Tail | ForEach-Object {
            $raw = $_
            try { $ev = $raw | ConvertFrom-Json } catch { Write-Host $raw -ForegroundColor DarkGray; return }
            $ts  = if ($ev.ts) { $ev.ts } else { "" }
            $svc = if ($ev.service) { $ev.service } else { "?" }
            $evt = if ($ev.event) { $ev.event } else { "" }
            $lvl = if ($ev.level) { $ev.level } else { "info" }
            # ADR-0014 has no top-level 'msg'; surface the optional 'extra' payload
            # as a compact one-liner so events stay readable.
            $msg = ""
            if ($ev.extra) {
                try { $msg = ($ev.extra | ConvertTo-Json -Compress -Depth 4) } catch { $msg = "$($ev.extra)" }
            }
            if ($cutoff -and $ts) {
                try { if ([datetime]::Parse($ts) -lt $cutoff) { return } } catch { }
            }
            if ($Filter -and ($msg -notmatch $Filter) -and ($evt -notmatch $Filter) -and ($lvl -notmatch $Filter)) { return }
            $col = ColorFor $svc
            if ($lvl -match 'error|critical') { $col = "Red" }
            elseif ($lvl -match 'warn') { $col = "Yellow" }
            elseif ($lvl -match 'debug') { $col = "DarkGray" }
            elseif ($lvl -match 'info') { $col = "Gray" }
            $line = "{0} | {1} | {2} | {3} | {4}" -f $ts, $svc, $evt, $lvl, $msg
            Write-Host $line -ForegroundColor $col
        }
    } finally {
        Write-Host "[tail_logs] stopped." -ForegroundColor DarkGray
    }
    exit 0
}

# --- text mode ---
Write-Host ("[tail_logs] tailing {0} file(s) ::" -f $files.Count) -ForegroundColor DarkGray
$files | ForEach-Object { Write-Host ("  - " + $_) -ForegroundColor DarkGray }
Write-Host ("[tail_logs] filter='{0}' since='{1}'{2}" -f $Filter, $Since, $(if ($Once) { " (once)" } else { " (follow)" })) -ForegroundColor DarkGray
Write-Host ("-" * 60) -ForegroundColor DarkGray

function Emit-Line([string]$line, [string]$svc, [string]$svcCol) {
    $msgCol = "White"
    if ($line -match 'ERROR') { $msgCol = "Red" }
    elseif ($line -match 'WARNING|WARN') { $msgCol = "Yellow" }
    elseif ($line -match 'INFO') { $msgCol = "Gray" }
    [Console]::ForegroundColor = $svcCol
    [Console]::Write("[$svc] ")
    [Console]::ForegroundColor = $msgCol
    [Console]::WriteLine($line)
    [Console]::ResetColor()
}

function Pass-Line([string]$line) {
    if ($cutoff) {
        if ($line -match '(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})') {
            try {
                $lt = [datetime]::Parse($Matches[1])
                if ($lt -lt $cutoff) { return $false }
            } catch { }
        }
    }
    if ($Filter -and ($line -notmatch $filter)) { return $false }
    return $true
}

if ($Once) {
    # snapshot: read the last $Tail lines of each file, then exit
    foreach ($f in $files) {
        $svc = ($f -split '[/\\]')[-1] -replace '\.err\.log$', '' -replace '\.log$', ''
        $svcCol = ColorFor $svc
        Get-Content -Path $f -Tail $Tail | ForEach-Object {
            if (Pass-Line $_) { Emit-Line $_ $svc $svcCol }
        }
    }
    exit 0
}

# follow mode: one thread job per file -> per-service color + live interleave
try {
    $jobs = foreach ($f in $files) {
        $svc = ($f -split '[/\\]')[-1] -replace '\.err\.log$', '' -replace '\.log$', ''
        $svcCol = ColorFor $svc
        Start-ThreadJob -ScriptBlock {
            param($path, $svc, $svcCol, $tail, $filter, $cutoff)
            & { param($p, $t) Get-Content -Path $p -Wait -Tail $t } $path $tail | ForEach-Object {
                $line = $_
                if ($cutoff) {
                    if ($line -match '(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})') {
                        try {
                            $lt = [datetime]::Parse($Matches[1])
                            if ($lt -lt $cutoff) { return }
                        } catch { }
                    }
                }
                if ($filter -and ($line -notmatch $filter)) { return }
                $msgCol = "White"
                if ($line -match 'ERROR') { $msgCol = "Red" }
                elseif ($line -match 'WARNING|WARN') { $msgCol = "Yellow" }
                elseif ($line -match 'INFO') { $msgCol = "Gray" }
                [Console]::ForegroundColor = $svcCol
                [Console]::Write("[$svc] ")
                [Console]::ForegroundColor = $msgCol
                [Console]::WriteLine($line)
                [Console]::ResetColor()
            }
        } -ArgumentList $f, $svc, $svcCol, $Tail, $Filter, $cutoff
    }
    Wait-Job $jobs | Out-Null
} finally {
    $jobs | Stop-Job -ErrorAction SilentlyContinue
    $jobs | Remove-Job -ErrorAction SilentlyContinue
    Write-Host "[tail_logs] stopped." -ForegroundColor DarkGray
}
