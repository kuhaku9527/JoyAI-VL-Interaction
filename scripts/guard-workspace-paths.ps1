# guard-workspace-paths.ps1
# ---------------------------------------------------------------------------
# 防外溢看门狗（dry-run，绝不自动删除）。
# 扫描已知的“外溢盘符根” D:/c D:/d D:/Cache D:/tmp，若再冒出 Joy/WorkBuddy 相关
# 文件即告警，供人工或 CI 发现回归。
#
# 用法：
#     pwsh scripts/guard-workspace-paths.ps1
#     pwsh scripts/guard-workspace-paths.ps1 -Fix   # 预留：未来如需自动移回工作区
# 退出码：0 = 无命中；1 = 发现外溢。
# ---------------------------------------------------------------------------
[CmdletBinding()]
param(
    [switch]$Fix
)

$Roots = @('D:\c', 'D:\d', 'D:\Cache', 'D:\tmp')

# 判定“Joy/WorkBuddy 相关”的令牌（路径或文件名包含其一即视为命中）
$Tokens = @(
    'joyai', 'JoyAI', 'joy_ai',
    'workbuddy', '.workbuddy',
    'agent-scratch',
    'playwright',            # 仅当出现在上述外溢根下才算（仓库内 .cache/playwright 不扫）
    'ruff-migrate', 'tmp_ruff', 'ruff69', 'ruff-check-venv', 'rv3'
)

$hits = @()

foreach ($root in $Roots) {
    if (-not (Test-Path $root)) { continue }
    # 仅扫两层深，避免无谓遍历大缓存；外溢多为浅层
    Get-ChildItem -Path $root -Recurse -Depth 2 -ErrorAction SilentlyContinue | ForEach-Object {
        $full = $_.FullName
        foreach ($t in $Tokens) {
            if ($full -like "*$t*") {
                $hits += $full
                break
            }
        }
    }
}

if ($hits.Count -eq 0) {
    Write-Host "[guard] OK - 四盘符未发现 Joy/WorkBuddy 外溢文件。"
    exit 0
}

Write-Host "[guard] 发现 $($hits.Count) 个外溢命中："
foreach ($h in $hits) { Write-Host "  - $h" }

if ($Fix) {
    Write-Host "[guard] -Fix 模式暂未实现自动迁移，请人工处理或扩展本脚本。"
}

exit 1
