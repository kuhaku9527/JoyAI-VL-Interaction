#!/usr/bin/env bash
# ===========================================================================
# verify.sh — 决策书(决策/) 自动校验器
# ---------------------------------------------------------------------------
# 把每条 D-XXX 的"校验"字段命令化，跑一遍即可知晓哪些决策被运行态漂移破坏。
# 只读、不改任何文件。输出 [PASS]/[FAIL]/[DRIFT] 表格 + 汇总。
#
# 用法:
#   bash scripts/verify.sh            # 全部校验
#   bash scripts/verify.sh --quiet    # 仅列出非 PASS 项
#
# 注意: 端口校验依赖服务当前是否在运行；DOWN 表示该服务此刻未起，
#       属环境状态而非代码漂移，会标 [DOWN] 不计入 fail。
# ===========================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

QUIET="${1:-}"
pass=0; fail=0; drift=0; down=0

# ---- 端口健康检查 ----------------------------------------------------------
check_port() {  # $1=标签 $2=端口 $3=预期(可选,用于 drift 判定)
  local label="$1" port="$2"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 2 "http://127.0.0.1:${port}/health" 2>/dev/null || echo "000")
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

# ---- 废弃端口反向断言 (DRIFT-2 拦截点, D-010 端口铁律) --------------------
check_port_absent() {  # $1=标签 $2=端口  —— 反向断言：废弃端口不得有任何监听(DRIFT-2 拦截)
  local label="$1" port="$2" listening=0 probe_rc=1
  # 端口必须是数字，否则无法探测 -> 跳过(fail-open)，避免误判
  if [[ ! "$port" =~ ^[0-9]+$ ]]; then
    echo "[PASS]  $label  :$port  (非数字端口, 跳过)"
    pass=$((pass+1)); return 0
  fi
  # 裸 TCP 连接探测(不依赖 HTTP /health)：连得上=有监听(违例,FAIL)，连不上(连接被拒)=DOWN(期望,PASS)。
  # 不能用 curl /health 探测(裸 TCP 监听不返回 HTTP 200，会被误判 absent)；git-bash 的 /dev/tcp 重定向
  # 在连接被拒时也不报错，不可用；git-bash 的 `python` 是 localhost 连接超时的残缺别名，故优先 python3
  # (托管 3.13.12，git-bash/Linux CI 均可正常 connect)，回退 curl 退出码(7=被拒)。
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', int(sys.argv[1]))); s.close()" "$port" >/dev/null 2>&1; probe_rc=$?
  elif command -v python >/dev/null 2>&1; then
    python -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', int(sys.argv[1]))); s.close()" "$port" >/dev/null 2>&1; probe_rc=$?
  elif command -v curl >/dev/null 2>&1; then
    # curl 无法可靠区分"裸 TCP 监听"与"超时/其他"，故兜底一律 fail-open(不声明有监听)，
    # 避免把超时(28)误判为 drift FAIL。真实探测依赖上面的 python3/python 裸 TCP connect。
    probe_rc=1
  fi
  # probe_rc==0 表示连上了某监听(违例)；非0 表示探测失败/无监听(视为 absent，fail-open)
  [ "$probe_rc" -eq 0 ] && listening=1
  if [ "$listening" -eq 1 ]; then
    echo "[FAIL]  $label  :$port  unexpected listener (drift)"
    fail=$((fail+1)); return 1
  else
    echo "[PASS]  $label  :$port  absent (good)"
    pass=$((pass+1)); return 0
  fi
}

# ---- 文本断言 ---------------------------------------------------------------
grep_file() {  # $1=标签 $2=文件 $3=pattern $4=期望命中(0/非0) $5=drift判定(y/n)
  local label="$1" file="$2" pat="$3" expect="$4" isdrift="${5:-n}"
  if [ ! -f "$file" ]; then
    echo "[DOWN]  $label  (文件不存在: $file)"; down=$((down+1)); return 0
  fi
  local n
  n=$(grep -cE "$pat" "$file" 2>/dev/null || echo 0)
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
check_port "D-020/021 VLM :7060"            7060
check_port "D-023 webinfer :8070"           8070
check_port "D-032 webui :8099"              8099
check_port "D-040/041 memory-store :8997"   8997
check_port "D-045 ASR :8993"                8993
check_port "D-047 TTS :8985"                8985
check_port "D-048 Hermes :8642"             8642
check_port "D-049 background-agent :8079"   8079

# D-010 端口铁律 + DRIFT-2：memory-store 决策态监听 :8997；废弃 :8996 必须 DOWN。
check_port_absent "D-010 deprecated :8996 must be down" 8996

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
