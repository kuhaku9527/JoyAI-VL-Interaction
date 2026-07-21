#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# smoke-frontend-baseline.sh — 前端解耦前回归基线冒烟
#
# 用途：在前端模块解耦（index.html 单体 -> 模块化）过程中作为回归门禁。
#       每次拆完一块，跑一遍本脚本；全部 PASS 即视为无回归。
#       覆盖 WebUI(8099) ↔ webinfer(8070) ↔ llama(7060) 集成契约
#       + TTS(8985) + memory-store(8996) + 端到端真实推理。
#
# 注意：本脚本只验证 HTTP / 契约层。以下浏览器侧 UI 功能 curl 测不到，
#       需在浏览器手动回归（解耦若动到这些模块务必纳入）：
#         - capture_webcam / capture_rtsp / screen_capture 三个采集模块
#         - Jarvis 模式 UI
#         - TTS 语音合成 UI（/v1/synthesize 调用）
#         - memory-store 记忆面板 UI
#
# Usage:  bash scripts/smoke-frontend-baseline.sh
# Exit:   0 = 全绿; 非 0 = 失败项数（可直接作 CI gate）
# ---------------------------------------------------------------------------
set -uo pipefail

HOST="127.0.0.1"
WEBUI=8099
WEBINFER=8070
LLAMA=7060
TTS=8985
MEMSTORE=8996

pass=0
fail=0

ok()  { echo "  [PASS] $1"; pass=$((pass + 1)); }
bad() { echo "  [FAIL] $1"; fail=$((fail + 1)); }

# HTTP 状态码
code() {
  curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://$HOST:$1$2" 2>/dev/null
}
# 响应体
body() {
  curl -s --max-time 8 "http://$HOST:$1$2" 2>/dev/null
}

echo "==> 前端解耦回归基线冒烟 ($(date -u +%H:%M:%SZ))"

# 1) WebUI 首页
c=$(code "$WEBUI" /)
if [ "$c" = "200" ]; then ok "WebUI 首页 GET $WEBUI/ -> $c"; else bad "WebUI 首页 GET $WEBUI/ -> ${c:-OFF}"; fi

# 2) 前端自报后端地址（契约一致性）
b=$(body "$WEBUI" /detect-services)
if echo "$b" | grep -q "8070/v1" && echo "$b" | grep -q "8985"; then
  ok "detect-services 契约含 8070/v1 + 8985"
else
  bad "detect-services 契约缺失 (body: ${b:0:200})"
fi

# 3) 前端 -> 后端 summarizer 代理（路由须存在且转发，非 404 / 5xx）
c=$(code "$WEBUI" /api/webinfer/summarizer/route)
if [ "$c" != "000" ] && [ "$c" != "404" ] && [ "${c:0:1}" != "5" ]; then
  ok "WebUI summarizer 代理 GET $WEBUI/api/webinfer/summarizer/route -> $c"
else
  bad "WebUI summarizer 代理 -> ${c:-OFF}"
fi

# 4) WebSocket 路由存在（GET 应 400/426 而非 404 / 连接拒绝）
c=$(code "$WEBUI" /ws)
if [ "$c" != "000" ] && [ "$c" != "404" ] && [ "${c:0:1}" != "5" ]; then
  ok "WebUI /ws 路由存在 -> $c"
else
  bad "WebUI /ws 路由异常 -> ${c:-OFF}"
fi

# 5) webinfer 健康 + memory_store.healthy
b=$(body "$WEBINFER" /health)
if echo "$b" | grep -q '"ok": *true'; then
  if echo "$b" | grep -q '"healthy": *true'; then
    ok "webinfer /health ok + memory_store.healthy"
  else
    bad "webinfer /health memory_store.healthy=false (body: ${b:0:200})"
  fi
else
  bad "webinfer /health 非 ok (body: ${b:0:200})"
fi

# 6) llama-server 健康
c=$(code "$LLAMA" /health)
if [ "$c" = "200" ]; then ok "llama-server /health -> $c"; else bad "llama-server /health -> ${c:-OFF}"; fi

# 7) TTS /health minimax_ok
b=$(body "$TTS" /health)
if echo "$b" | grep -q '"minimax_ok": *true'; then
  ok "TTS /health minimax_ok=true"
else
  bad "TTS /health minimax_ok 非 true (body: ${b:0:200})"
fi

# 8) memory-store /health ok
b=$(body "$MEMSTORE" /health)
if echo "$b" | grep -q '"ok": *true'; then
  ok "memory-store /health ok=true"
else
  bad "memory-store /health 非 ok (body: ${b:0:200})"
fi

# 9) 端到端真实推理 8070 -> 7060（会触发一次真实 VLM 推理，稍慢）
b=$(curl -s --max-time 60 -X POST "http://$HOST:$WEBINFER/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"joyai-vl-interaction-preview","messages":[{"role":"user","content":"ping"}],"stream":false}' 2>/dev/null)
if echo "$b" | grep -qi '"content"'; then
  ok "端到端 8070->7060 chat 返回 content"
else
  bad "端到端 chat 异常 (body: ${b:0:200})"
fi

echo ""
echo "==> 结果: PASS=$pass  FAIL=$fail"
if [ "$fail" -gt 0 ]; then
  echo "!! 存在回归，解耦需回查"
  exit "$fail"
fi
echo "✅ 全绿，无回归"
exit 0
