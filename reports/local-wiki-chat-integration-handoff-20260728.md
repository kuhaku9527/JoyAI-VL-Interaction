# Local Wiki 聊天接入缺口 — Handoff（2026-07-28）

> 真相源：本文档记录 Local Wiki 知识库"已建好但不被聊天消费"的功能缺口，交给**后端（webinfer 微服务）+ 架构**裁决接入方案。
> 关联：Local Wiki 全链路已合 main（#36–#41）；launcher PS5.1 / schema 迁移见 `integration-launcher-ps51-schema-fix-handoff-20260728.md`（与本问题无关）。

## 0. 当前真机状态（已验证）
- 已合 main：`#36` 语义召回 + `#37` 前端 F1-F4 + `#38` 后端 B1-B4/B9 + `#39` F4 fix + `#40` schema 迁移幂等 + `#41` launcher PS5.1。
- 2026-07-28 晚真机拉起：**memory-store(:8997, CPU/local bge-m3) + webui(:8099, test-mode) + llama-main(:7060, b10155 win-cuda-13.3) + webinfer(:8070)**，LLM 推理端到端通过（webinfer→llama 实测返回真实文本）。
- Local Wiki 建库经 `POST /v1/external/sync` 成功；直查 `POST /v1/blocks/recall`（带 `filter.namespaces`）score 1.0 命中（已验证）。

## 1. 问题
聊天（webinfer → llama）**不会自动引用 Local Wiki 知识库内容**。问已建库的知识点（如假资料"熔渣之王"弱点是冰属性/用盾），模型凭空编造（`streamingharness.memory_chars=0`）。

## 2. 根因（已查实，非崩溃、非 bug）
- webinfer 聊天路径的召回只走 `memory_io._memory_warmup` → `MemoryStoreClient.warmup(session_id)`，其 payload 固定为 `filter:{session_ids:[session_id]}`，**仅拉本会话自己 push 的长期记忆**。
- `MemoryStoreClient.recall(query, ...)`（按问题语义召回，支持 `filter.namespaces`）**在聊天真实路径中从不调用**——grep 全仓确认仅出现在 `services/webinfer/tests/`。
- `memory_io._memory_recall(question)` 只返回 `state._memory_block_cache`（warmup 结果），不触发语义 hot-fetch；代码注释明写：
  - `v0.1 spec skips per-question rerank -- the cache is the answer`
  - `v0.3+ may add per-question hot-fetch against the live query`
- `prompt_assembly._build_memory_prompt` 的 `[Local Wiki]` 系统提示段只消费 `session._memory_block_cache`。
- → Local Wiki 知识库（`wiki:*` namespace，经 `/v1/external/sync` 建）已建好且可查，但**未接入聊天 prompt**。属被架构显式推迟（v0.3+）的功能缺口，不是缺陷。

## 3. 影响
- 用户建好的攻略/资料库在聊天中完全不起作用，Local Wiki 功能"名存实亡"：只验证了建库 + 网页面板 + 后端 recall API，**聊天不消费**。

## 4. 建议方案（供后端/架构裁决）

### 方案 A — 最小可用（推荐先做）
在 `memory_io._memory_recall(question)` 中，warmup 完成后额外调用
`memory_store.recall(question, top_k=N, min_score=θ, filter={namespaces: [...wiki ns...]})`，
将命中的 wiki 块合并进 `state._memory_block_cache`（按 content_hash 去重），供现有 `[Local Wiki]` 段消费。
- **需架构决策**：
  1. namespace 范围：`wiki:*` 全量召回 vs 配置白名单（如 `LOCAL_WIKI_NAMESPACES` env）。
  2. 阈值：`top_k`（建议 4–6）、`min_score`（建议 0.35–0.5，避免噪声块污染 prompt）。
  3. 是否对命中块做轻量 rerank（v0.3+ 预留，A 版可先跳过）。
- **风险**：低；不改动现有会话记忆写入/读取路径，仅扩展 warmup 后的缓存来源。

### 方案 B — 更彻底（结构分离）
聊天时把"按问题语义召回的 wiki"与"会话长期记忆"分开处理：`[Local Wiki]` 段与 `[Session Memory]` 段独立拼接，避免两类内容互相污染，并可对 wiki 块加引用标记。
- **改动更大**，需架构定 prompt 段结构与去重/截断策略。

## 5. 负责人 / 阻塞
- **后端（webinfer 微服务）**：实现方案 A 或 B。
- **架构**：定 namespace 范围策略 + 召回阈值 +（方案 B）prompt 段结构。
- **阻塞**：无。四服务全在跑，可随时复现（复现步骤见 §6）。

## 6. 复现 / 验证步骤
1. 起服务：memory-store(:8997, 已建 `wiki:sample-test`) + webinfer(:8070, `MEMORY_STORE_URL=http://127.0.0.1:8997`) + llama-main(:7060, b10155)。
2. 发聊天：
   `POST http://127.0.0.1:8070/v1/chat/completions`
   `{"model":"JoyAI-VL-Interaction-Preview","messages":[{"role":"user","content":"熔渣之王有什么弱点？怎么打？"}],"stream":false}`
   → 模型瞎编（原神 boss），`streamingharness.memory_chars=0`。
3. 对照（证明库可查、仅缺接入）：
   `POST http://127.0.0.1:8997/v1/blocks/recall`
   `{"query":"熔渣之王 弱点","top_k":3,"min_score":0.1,"filter":{"namespaces":["wiki:sample-test"]}}`
   → 命中 boss 攻略块 score 1.0。
4. 验收标准（接入后）：同样聊天请求 `memory_chars>0`，且回复引用 wiki 内容（冰属性弱点/用盾）。

## 7. 不在本次范围
- llama.cpp 替换（本地完成 b10155 CUDA13.3，解决 Blackwell 崩溃）、schema 迁移(#40)、launcher PS5.1(#41) 均已合 main，与本缺口无关。
- 前端 wiki 面板"无召回 UI"是另一已知项（召回由后端内部调用），不在此文档范围。

## 8. 决策记录
- 2026-07-28：主理人评估该缺口**非小修**（架构曾显式推迟 v0.3+；含 namespace 策略/阈值/rerank 设计决策）→ 不入擅自实现，写入本 handoff 交后端/架构。若后续授权最小可用版（方案 A），由后端 agent 按 SOP 实现并经 CI + reviewer 门禁后合入。
