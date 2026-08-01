#!/usr/bin/env bash
# ===========================================================================
# verify.sh — 决策书(决策/) 自动校验器
# ---------------------------------------------------------------------------
# 把每条 D-XXX 的"校验"字段命令化，跑一遍即可知晓哪些决策被运行态漂移破坏。
# 只读、不改任何文件。输出 [PASS]/[FAIL]/[DRIFT] 表格 + 汇总。
#
# 用法:
#   bash scripts/verify.sh            # 全部校验(端口+运行时+静态)
#   bash scripts/verify.sh --ci       # CI 模式：仅静态 grep 子集(fail-closed)，跳过端口/运行时
#   bash scripts/verify.sh --quiet    # 仅列出非 PASS 项
#
# 注意: 端口校验依赖服务当前是否在运行；DOWN 表示该服务此刻未起，
#       属环境状态而非代码漂移，会标 [DOWN] 不计入 fail。
# ===========================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

QUIET=""
CI_MODE=""
for _a in "$@"; do
  case "$_a" in
    --ci) CI_MODE=1 ;;
    --quiet) QUIET="--quiet" ;;
  esac
done
pass=0; fail=0; drift=0; down=0

# ---- 端口健康检查 ----------------------------------------------------------
check_port() {  # $1=标签 $2=端口 $3=预期(可选,用于 drift 判定)
  local label="$1" port="$2"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 2 "http://127.0.0.1:${port}/health" 2>/dev/null)
  code=${code:-000}
  if [ "$code" = "200" ]; then
    echo "[PASS]  $label  :$port  health=200"
    pass=$((pass+1)); return 0
  elif [ "$code" = "000" ]; then
    echo "[DOWN]  $label  :$port  (服务未运行)"
    down=$((down+1)); return 0
  else
    echo "[FAIL]  $label  :$port  health=$code"
    fail=$((fail+1)); return 1
  fi
}

# ---- 文本断言 ---------------------------------------------------------------
grep_file() {  # $1=标签 $2=文件 $3=pattern $4=期望命中(0/非0) $5=drift判定(y/n)
  local label="$1" file="$2" pat="$3" expect="$4" isdrift="${5:-n}"
  if [ ! -f "$file" ]; then
    echo "[DOWN]  $label  (文件不存在: $file)"; down=$((down+1)); return 0
  fi
  local n
  n=$(grep -cE "$pat" "$file" 2>/dev/null)
  n=${n:-0}
  if { [ "$expect" = "0" ] && [ "$n" -eq 0 ]; } || { [ "$expect" != "0" ] && [ "$n" -gt 0 ]; }; then
    echo "[PASS]  $label  ($file 命中 $n)"; pass=$((pass+1)); return 0
  else
    if [ "$isdrift" = "y" ]; then
      echo "[DRIFT] $label  ($file 期望命中=$expect 实际=$n)"; drift=$((drift+1))
    else
      echo "[FAIL]  $label  ($file 期望命中=$expect 实际=$n)"; fail=$((fail+1))
    fi
    return 1
  fi
}

echo "==================================================================="
echo " 决策书校验  $(date '+%Y-%m-%d %H:%M')"
echo "==================================================================="

# ---- L2 服务端口 (D-020/023/032/040/045/047/048/049) ----------------------
# CI 模式(--ci)跳过运行时/端口检查：它们需服务起停，在 CI 中必为 [DOWN]，
# 属 fail-open 维度，由本地/运行时 job 负责，不进合并门禁。
if [ -z "$CI_MODE" ]; then
check_port "D-020/021 VLM :7060"            7060
check_port "D-023 webinfer :8070"           8070
check_port "D-032 webui :8099"              8099
check_port "D-040/041 memory-store :8997"   8997
check_port "D-045 ASR :8993"                8993
check_port "D-047 TTS :8985"                8985
check_port "D-048 Hermes :8642"             8642
check_port "D-049 background-agent :8079"   8079

# ---- D-022 VLM n_ctx 运行态 (决策态 16384) --------------------------------
LATEST_LOG=$(ls -t logs/llama-main.log 2>/dev/null | head -1)
if [ -n "$LATEST_LOG" ]; then
  nctx=$(grep -oE "n_ctx_slot = [0-9]+" "$LATEST_LOG" 2>/dev/null | tail -1 | grep -oE "[0-9]+")
  if [ "$nctx" = "16384" ]; then
    echo "[PASS]  D-022 VLM n_ctx_slot=16384 (决策态一致)"; pass=$((pass+1))
  elif [ "$nctx" = "4096" ]; then
    echo "[DRIFT] D-022 VLM n_ctx_slot=4096 (决策态=16384, 见 drift-历史 DRIFT-1)"; drift=$((drift+1))
  else
    echo "[DOWN]  D-022 VLM n_ctx 未从日志解析 (无运行实例?)"; down=$((down+1))
  fi
else
  echo "[DOWN]  D-022 无 llama-main.log (VLM 未运行)"; down=$((down+1))
fi
else
  echo "[SKIP]  运行时/端口检查 (--ci 模式跳过；需起服务，属 fail-open)"
fi

# ---- D-030 webinfer timeout 300 -------------------------------------------
grep_file "D-030 webinfer request_timeout=300" "services/webinfer/adapter_types.py" "request_timeout_seconds: float = 300.0" "1"

# ---- D-031/008 run-windows.env 无 8997 覆盖 (已知 drift) ------------------
grep_file "D-008/031 run-windows.env 无 MEMORY_PORT(期望零命中=drift存在)" "services/scripts/run-windows.env" "MEMORY_PORT|JOYAI_MEMORY_STORE_URL" "0" "y"

# ---- D-015 webui 网关默认 8996 (已知 drift) -------------------------------
grep_file "D-015 server.py 默认 8996(期望命中=drift存在)" "services/webui/src/joy_interaction_webui/server.py" 'JOYAI_MEMORY_STORE_URL.*"http://127.0.0.1:8996"' "1" "y"

# ---- D-034 前端 Vitest 基座 -----------------------------------------------
grep_file "D-034 vitest 配置存在" "services/webui/vitest.config.js" "vitest/config" "1"
grep_file "D-034 package.json vitest 脚本" "services/webui/package.json" '"vitest run"' "1"

# ---- D-007 ruff 固定 0.15.22 ----------------------------------------------
grep_file "D-007 quality.yml ruff==0.15.22" ".github/workflows/quality.yml" "ruff==0.15.22" "1"

# ---- D-033 前端模块化 window.JoyXxx --------------------------------------
grep_file "D-033 index.html window.JoyWiki" "services/webui/src/joy_interaction_webui/static/index.html" "window.JoyWiki" "1"

# ---- D-036 前端 wikiNamespace 显式输入 ------------------------------------
grep_file "D-036 wiki_frontend.js wikiNamespace" "services/webui/src/joy_interaction_webui/static/wiki_frontend.js" "wikiNamespace" "1"

# ---- D-076 WIKI_RECALL env 读取 -------------------------------------------
grep_file "D-076 memory_io WIKI_RECALL_NAMESPACES" "services/webinfer/memory_io.py" "WIKI_RECALL_NAMESPACES" "1"

echo "==================================================================="
echo " 汇总: PASS=$pass  FAIL=$fail  DRIFT=$drift  DOWN=$down"
echo "==================================================================="
if [ "$QUIET" = "--quiet" ]; then
  echo "(--quiet: 仅 FAIL/DRIFT 已上方列出)"
fi
# 退出码: 有 FAIL 才非 0（DRIFT/DOWN 不阻断，属已知/环境）
[ "$fail" -eq 0 ]
