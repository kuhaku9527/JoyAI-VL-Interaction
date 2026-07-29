# 服务真值 — background-agent（:8079 shim + Local Wiki recall 契约）

> 本文件记录 **background-agent（:8079 后台 agent shim）** 的已确定决策，覆盖 L2 `D-2026-07-23-049`。
> 所有事实由主理人亲自从 git 提交 + 代码（`services/background-agent/`）核实（2026-07-28 召回轮，不起子代理）。
> 注：Hermes 网关（:8642）与 background-agent shim（:8079）同处 `services/background-agent/` 目录，Hermes 决策见 `服务-Hermes.md`（D-048）。

---

## D-2026-07-23-049  background-agent :8079 + Local Wiki recall 契约（`_enrich_with_memory`）

- **事实**: background-agent 是 webui 默认指向的后台 agent（shim 端口 `:8079`，`BACKGROUND_AGENT_API_URL=http://127.0.0.1:8079`）。其与 Local Wiki 的黏合点是 `hermes_api._enrich_with_memory(question)`：每次提问并行触发 memory-store 语义召回（fail-open），召回失败必须记 WARNING 日志（不吞）。
- **来源**: git `96aba52`（2026-07-23，Hermes 落地）+ 测试守护 `a6ab947`
- **校验**:
  1. `grep -n "8079\|BACKGROUND_AGENT_API_URL" services/background-agent/background-agent.env services/background-agent/README.md` → env:3 `=http://127.0.0.1:8079`；README:20/90/147 端口 8079
  2. `grep -n "_enrich_with_memory\|WIKI_RECALL_NAMESPACES" services/background-agent/hermes_api/main.py` → main.py:55 `WIKI_RECALL_NAMESPACES = os.environ.get("WIKI_RECALL_NAMESPACES", "wiki:*")`；:255 解析 namespaces；test_hermes_api_enrich_guard.py:83/96 调 `_enrich_with_memory` 且断言 recall 失败记 WARNING
  3. `WIKI_RECALL_NAMESPACES` 默认 `wiki:*`（全 namespace 召回），空字符串则完全关闭 recall（fail-open）
- **预期**: shim 监听 8079 且为 webui 默认；`_enrich_with_memory` 存在且 recall 失败记日志不吞；默认 `wiki:*`
- **Drift**: 无
- **Owner**: 后端 / 架构
- **锁定**: 🔒

---

## 关联索引

- 记忆 warmup/recall 实际发生地（webinfer 侧）：见 `业务-决策记忆.md`（D-075/076）、`服务-webinfer.md`（D-025）
- Hermes 记忆后端（:8642）：见 `服务-Hermes.md`（D-048）
- Local Wiki 全链路：见 `业务-LocalWiki.md`
