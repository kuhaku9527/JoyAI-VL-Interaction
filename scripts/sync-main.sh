#!/usr/bin/env bash
#
# scripts/sync-main.sh
#
# 安全把本地仓库对齐 origin/main，并自动补回「磁盘缺失的跟踪文件」。
#
# 背景（详见 docs/github-runbook.md §4「git 沙箱陷阱」）：
#   在沙箱 / ff-merge 场景下，跟踪文件可能从磁盘消失，但 HEAD 中仍保留它们，
#   导致 `git status` 出现假 `D`（典型如最近 PR 往 services/*/tests/ 新加的
#   测试文件）。这些不是真实删除——本仓库的删除永远是先提交再合并，不存在
#   「未提交的有意删除」。因此把缺失的跟踪文件从 HEAD 补回，始终是安全的。
#
# 用法：
#   bash scripts/sync-main.sh
#
# 行为：
#   1. git fetch origin                                （刷新 tracking 引用，消 §13 过期假象）
#   2. 若当前在 main：git merge --ff-only origin/main  （只快进，绝不改写历史）
#   3. 自动补回磁盘缺失的跟踪文件（git ls-files -d -> git checkout HEAD --）
#   4. 打印状态摘要
#
# 安全铁律：绝不 reset --hard / clean -fd；删除永远显式、已提交后才合入。
#
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "[sync-main] fetch origin..."
git fetch origin

branch="$(git rev-parse --abbrev-ref HEAD)"
echo "[sync-main] current branch: $branch  HEAD=$(git rev-parse HEAD)"
echo "[sync-main] origin/main=$(git rev-parse origin/main)"

if [ "$branch" = "main" ]; then
  local_main="$(git rev-parse main)"
  remote_main="$(git rev-parse origin/main)"
  if [ "$local_main" = "$remote_main" ]; then
    echo "[sync-main] main already at origin/main, nothing to fast-forward."
  else
    echo "[sync-main] fast-forwarding main $local_main -> $remote_main"
    git merge --ff-only origin/main
  fi
else
  echo "[sync-main] not on main; skipping ff (checkout main to sync). still healing below."
fi

echo "[sync-main] healing tracked files missing from disk..."
git update-index -q --refresh || true
missing="$(git ls-files -d || true)"
if [ -z "$missing" ]; then
  echo "[sync-main] working tree complete, nothing missing."
else
  echo "[sync-main] restoring the following tracked files from HEAD:"
  echo "$missing"
  # 用 HEAD 显式补回（避免依赖可能过期的 index）
  echo "$missing" | xargs -r git checkout HEAD --
  echo "[sync-main] restored $(echo "$missing" | wc -l | tr -d ' ') file(s)."
fi

echo "[sync-main] done. status (first 30 lines):"
git status --porcelain | head -30 || true
echo "[sync-main] final HEAD: $(git rev-parse HEAD)"
