#!/usr/bin/env bash
# ===========================================================================
# verify.sh — 运行态探针（/health 探活 + 废弃端口反向断言 + VLM n_ctx 运行态）
# ---------------------------------------------------------------------------
# F4-P0 之后：配置/代码级静态断言已迁移到 config/drift-contract.json，
# 由 scripts/drift_gate.py 统一执行（CI drift-gate job 直接跑 drift_gate.py）。
# 静态校验的「单一真值源」就是 drift_gate.py —— 不要再经 verify.sh 委托，
# 否则会出现「CI 直跑 drift_gate.py」与「verify.sh --ci 委托」双分叉。
#
# 本脚本只负责「运行态探活」——这是契约 grep 无法替代的部分：
#   - 各服务 /health 端口探针（check_port）
#   - 废弃端口反向断言（check_port_absent，DRIFT-2 拦截点）
#   - VLM n_ctx 运行态（D-022，读 llama-main.log）
# 需要静态校验请直接调用：python scripts/drift_gate.py --contract config/drift-contract.json --phase static --mode closed
#
# 用法:
#   bash scripts/verify.sh            # 运行态探针
#   bash scripts/verify.sh --quiet    # 仅列出非 PASS 项
#
# 注意: 端口校验依赖服务当前是否在运行；DOWN 表示该服务此刻未起，
#       属环境状态而非代码漂移，会标 [DOWN] 不计入 fail。
# ===========================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- 参数 ---------------------------------------------------------------
# 仅 --quiet。静态校验不再经本脚本委托（单一真值源 = drift_gate.py，见文首）。
# 运行态探针始终运行——探针无法被契约替代。
QUIET=0
case "${1:-}" in
  --quiet) QUIET=1 ;;
  "")      ;;
  *) echo "usage: verify.sh [--quiet]" >&2; exit 2 ;;
esac

pass=0; fail=0; drift=0; down=0

# ---- 端口健康检查 ----------------------------------------------------------
check_port() {  # $1=标签 $2=端口 $3=预期(可选,用于 drift 判定)
  local label="$1" port="$2"
  local code
  # 注：curl 连接失败时仍会在 stdout 打印 "000" 且退出非 0；若再 `|| echo "000"`
  # 会追加成 "000000"，导致下方 `[ "$code" = "000" ]` 判等失败、把合法 [DOWN] 误判成 [FAIL]。
  # 故只取 curl 自身输出，缺失时再兜底为 "000"（不重复追加）。
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 2 "http://127.0.0.1:${port}/health" 2>/dev/null)
  code="${code:-000}"
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

# ---- 文本断言（已迁移）---------------------------------------------------
# F4-P0: 原 grep_file 静态断言（D-030/008/031/015/034/007/033/036/076）已
# 迁移到 config/drift-contract.json，由 scripts/drift_gate.py 统一执行。
# verify.sh 现只负责运行态探活（下方 check_port / check_port_absent / D-022）。
# 需要静态子集请直接跑 `python scripts/drift_gate.py`（单一真值源）。

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

# ---- 静态决策契约校验（不在本脚本内）------------------------------------
# F4-P0: D-XXX 静态断言已迁移到 config/drift-contract.json，由
# scripts/drift_gate.py 统一执行（CI drift-gate job 直接跑 drift_gate.py）。
# 本地看静态结果请直接：
#   python scripts/drift_gate.py --contract config/drift-contract.json --phase static --mode closed
# （verify.sh 只负责上方运行态探针，静态结果不再经本脚本委托，避免双分叉。）

echo "==================================================================="
echo " 汇总: PASS=$pass  FAIL=$fail  DRIFT=$drift  DOWN=$down"
echo "==================================================================="
if [ "$QUIET" = "1" ]; then
  echo "(--quiet: 仅 FAIL/DRIFT 已上方列出)"
fi
# 退出码: 有 FAIL 才非 0（DRIFT/DOWN 不阻断，属已知/环境）
[ "$fail" -eq 0 ]
