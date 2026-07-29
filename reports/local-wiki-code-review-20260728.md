# Local Wiki 后续 PR（#37–#41）代码审查报告

> 日期：2026-07-28 ｜ 审查人：后端记忆/Hermes 桥接对话（#36 作者）
> 范围：#36 合并后的 5 个 PR（#37 前端 F1-F4 / #38 后端 B1-B4+B9 / #39 F4 fix / #40 schema fix / #41 launcher fix），重点审查"是否改动我此前交付的代码及其质量"。
> 结论先行：**整体可用、CI 绿、我的核心模块（vector_index/wiki_ingest/wiki_service/sqlite_backend 主体）未被破坏；但发现 1 项未经决策记录的设计偏离（默认嵌入 provider 硅基→NVIDIA）、1 处测试完整性疑点（parity 样本被改）、1 个我自己的真 bug（已被 #40 正确修复）。**

---

## 1. 事实基线（GitHub 核实）

- main HEAD = `52fcbb8`（#41）。#36 之后合入 5 个 PR：`9692d01`(#37) `0ac6d10`(#38) `c91b22c`(#39) `47cfa58`(#40) `52fcbb8`(#41)。
- main 最新 Quality Gate（07-28 02:43）= **success**；#40 记录本地 61 passed / 6 skipped。
- 设计文档 `reports/local-wiki-vector-design-20260724.md` 自 #36 后 **diff=0（未被更新）**。
- 我交付的核心文件被改动情况：`embedder.py`（#38 大改，+77/-）＞ `app.py`（#38 加 B3/B4 端点）＞ `sqlite_backend.py`（#38 小改 + #40 删 2 行）＞ `vector_index.py`/`wiki_ingest.py`/`wiki_service.py`/`models.py`（#38 小改）。无恶意/破坏性改动。

## 2. 他们做对的（值得肯定）

1. **#40 修了我写的真 bug**：我在 `_SCHEMA` DDL 里把两个 namespace 索引放在 `CREATE TABLE` 后立即创建，但 `namespace` 列是老库经 `_migrate` 的 `ALTER ADD COLUMN` 才有的——**老库会在 `CREATE INDEX ... (namespace)` 处崩 `no such column: namespace`，模块无法导入**。我的测试全用新库（tmp_path）所以没暴露。#40 删掉 `_SCHEMA` 中两行（`_migrate` 已幂等建索引），修复正确、最小、验证充分（老库实测）。责任在我，致谢修复者。
2. **#38 client_factory/config（B1-B2）忠实于 v5 设计**：per-provider 代理（`use_proxy` + `proxy.enabled` 双开关）、client 缓存 + 热更新 invalidate、JSON 持久化、注释明确"拒绝全局 HTTPS_PROXY"。
3. **embedder.py 的 NVIDIA NIM 适配细节正确**：NIM 要求的 `input_type=query/passage` 只发给 nvidia、不发给 siliconflow（避免对端拒绝请求），且注释说清了原因；硅基/local 路径完整保留，未删我的代码。
4. **B3/B4 端点防假绿灯**：未配置的外部 provider 明确报 `not configured` 而非假绿——符合 v5 §5 的硬性要求。
5. **B9 金标集 + eval 工具 + sample_wiki 样例库**补齐，真机 handoff 证实建库+recall 端到端可查（score 1.0）。

## 3. 发现的问题（按严重度）

### P1 — 默认嵌入 provider 被切到 NVIDIA NIM，无 ADR 记录、无用户确认 ⚠️ 需裁决

- **事实**：#38 把 `BgeM3Embedder` 默认 provider 从 `siliconflow` 改为 `nvidia`（`EMBEDDING_PROVIDER` 缺省值改变），NVIDIA NIM `integrate.api.nvidia.com/v1` 且在 `config.py` 默认 `use_proxy=false`（直连）。
- **偏离点**：v5 定稿（用户逐项确认）是**硅基流动免费 API（¥0、国内直连）**。切换默认 provider 是设计级决策，但：① 设计文档/ADR-0012 **diff=0 未记录**（commit message 声称 "see ADR-0012 provider switch"，ADR 里并无此节）；② 用户未被告知或确认。
- **实际影响**：NVIDIA NIM 是**国外服务**，默认直连在国内网络通常不可达——handoff 真机记录也印证了这点（建库走 `CPU/local bge-m3` 而非任何 API）。即：**当前默认配置在新部署上大概率开箱即败**（health 报红），必须显式设 `EMBEDDING_PROVIDER=local/siliconflow` 才能用。
- **建议**（三选一，请用户拍板）：
  - **A. 恢复默认 siliconflow**（v5 原决策），NVIDIA 降为可选 provider；硅基欠费问题由用户充值解决。
  - **B. 保留 NVIDIA 默认但修两件事**：ADR-0012 补记 provider switch（原因/影响/key 来源/网络要求）；`config.py` 里 nvidia 默认 `use_proxy=true`（走 Clash 7890，与 gemini 同列）。
  - **C. 默认 `local`**：开箱即用（纯本地，无外部依赖），API provider 全为可选加速——最稳妥的开箱体验，但召回也吃本地算力（与"运行时省显存"目标冲突，需权衡）。

### P2 — parity 工具样本被改：全角逗号 `，` → 半角 `,` ⚠️ 测试完整性疑点

- **事实**：#38 将 `verify_embedding_parity.py` 样本 1 的全角逗号改为半角（`Boss，弱打击` → `Boss,弱打击`），同时硅基路径 parity 工具保留。
- **疑点**：`verify_embedding_parity.py` 是双栖方案的**空间一致性安全闸**（cos>0.999）。全角标点是中文攻略的常见字符。修改测试输入的可能解释有二：① 让 parity 更容易通过（若全角样本下本地 vs API 相似度不足 0.999）；② Codex 生成时的无意改动。无论动机，**改输入而非查根因，削弱了安全闸的覆盖**。
- **建议**：恢复全角逗号样本；若 parity 在全角样本下失败，则双栖方案本身存疑，应查托管侧量化差异（而不是改样本）。顺带我注意到 `verify_nvidia_recall.py` 是新增的 NVIDIA 侧验证（好），但**本地 vs NVIDIA 的 parity 门缺失**——若默认走 NVIDIA，双栖安全闸应对 NVIDIA 重建。

### P3 — #37 前端首版有功能 bug（#39 修复），提示前端质量一般

- **事实**：#39 修复"知识库 syncWiki 未读取 wikiNamespace 显式输入"——#37 的 F4 首版 sync 按钮忽略了用户输入的 namespace。#39 已修，但说明前端 F1-F4 交付时未做完整自测。
- **建议**：前端 wiki 面板加一条最小 e2e 校验（输入 namespace → sync → 列表出现该 namespace），防同类回归。

## 4. handoff 缺口裁决（`local-wiki-chat-integration-handoff-20260728.md`）

- **缺口属实**（已核实代码）：webinfer `_memory_recall` 只返回 warmup cache（`v0.3+ may add per-question hot-fetch` 注释为证），聊天路径从不调 `MemoryStoreClient.recall(query, filter.namespaces)`。这是 v0.1 spec 的显式推迟，**不是 #37-#41 引入的回归**。
- **我的裁决：支持方案 A（最小可用），并按 v5 设计精确化**：
  1. **namespace 范围**：webinfer 侧复用与 hermes 相同的 env 约定 `WIKI_RECALL_NAMESPACES`（默认 `wiki:*`，通配展开 backend 已支持）——两桥同一配置语义，避免双标。
  2. **阈值**：`top_k=5`、`min_similarity=0.35`（向量路径；与 hermes top_k=5 对齐）；命中块合并进 `_memory_block_cache` 时按 `content_hash` 去重，wiki 块保留 namespace 前缀以便 prompt 段区分来源。
  3. **fail-open**：recall 失败仅 `LOGGER.warning`，不阻塞聊天（沿用 hermes/既有惯例）。
  4. **方案 B（prompt 段分离）留作 v0.3+ 演进**（YAGNI）：A 先让功能"活"起来，段结构分离等真实 prompt 噪声出现再做。
  5. **改动面评估**：webinfer `memory_io._memory_recall` 增加 hot-fetch 分支（~30 行）+ `MemoryStoreClient` 已有 `recall` 方法直接复用 + 3–4 个测试（命中合并/去重/fail-open/namespace 过滤）。风险低。
- **前置依赖提醒**：方案 A 落地后，真机验收需可用的嵌入 provider（硅基充值 / 有效 NVIDIA key+代理 / 或 local 模式）——与 §3-P1 的裁决联动。

## 5. 建议行动顺序

1. 用户拍板 P1（provider 默认值：A 恢复硅基 / B 留 NVIDIA+补 ADR+代理 / C 默认 local）。
2. 我修 P2（恢复全角样本 + 视 P1 结论补 NVIDIA parity 门）。
3. 经你授权后，我实现聊天接入方案 A（webinfer hot-fetch + 测试），单开 PR。
4. （可选）前端 e2e 校验交前端对话。

---

### 附：审查方法与证据

- 全部结论基于 `git fetch` 后 FETCH_HEAD(52fcbb8) 的 diff 审查 + GitHub API（CI runs、PR 状态）+ 源码直读（webinfer/memory_io.py:62-80）。
- 关键证据：#38 embedder.py diff（provider 默认切换）、#40 diff（_SCHEMA 删 2 行）、parity 工具 diff（全角→半角）、设计文档 diff=0、handoff §2 代码事实复核一致。
