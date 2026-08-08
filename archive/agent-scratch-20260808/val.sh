#!/usr/bin/env bash
set -u
REPO="D:/AI/workspace/JoyAI-VL-Interaction-main"
cd "$REPO"
OUT="$REPO/_val4.txt"
{
  echo "=== re-run --ci after LF normalization ==="
  bash scripts/verify.sh --ci; echo "CI_EXIT=$?"

  echo ""
  echo "=== full run, NO services (8996 should be absent=PASS; ports DOWN) ==="
  bash scripts/verify.sh; echo "FULL_NO_SVC_EXIT=$?"

  echo ""
  echo "=== start fake listener on :8996 (returns 200) ==="
  python3 /tmp/fake8996.py &
  FAKE=$!
  sleep 1
  echo "fake pid=$FAKE"
  echo "=== full run WITH fake :8996 listener (D-010 8996 should FAIL) ==="
  bash scripts/verify.sh; echo "FULL_WITH_FAKE_EXIT=$?"
  kill $FAKE 2>/dev/null || true
  echo "killed fake listener"
} > "$OUT" 2>&1
echo DONE
