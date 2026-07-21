#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# quality-check.sh — repo-agnostic lint/format gate.
# Runs locally and inside any CI. Exits non-zero on violations.
#
# Usage:  ./scripts/quality-check.sh            # lint + format check
#         ./scripts/quality-check.sh --fix       # also auto-fix lint issues
# ---------------------------------------------------------------------------
set -euo pipefail

RUFF="ruff"
if command -v ruff >/dev/null 2>&1; then
  RUFF="ruff"
fi

echo "==> ruff version"
"$RUFF" --version

echo "==> ruff check (lint)"
if [ "${1:-}" = "--fix" ]; then
  "$RUFF" check . --fix
else
  "$RUFF" check .
fi

echo "==> ruff format --check"
"$RUFF" format --check .

echo "==> quality gate passed"
