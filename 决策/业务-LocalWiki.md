# 业务-LocalWiki / 方案 C 全链路（ADR-0012）

> 范围：Local Wiki 前端 F1-F4 + 后端 B1-B4 + B9 评测 + ADR-0012 方案 C。
> 真相源：`docs/ADR-0012-v6-proposal.md` + `services/memory-store` + `services/webui/static/wiki_frontend.js` + `index.html` + `services/webui/server.py`。
> **修改走 §0 治理协议（AI 提议 → 用户同意 → 落盘）。**

---

### D-2026-07-24-040 | Local Wiki 用途定性
| 字段 | 内容 |
|---|---|
| **事实** | Local Wiki = **游戏攻略库**（艾尔登法环等）；用户意图：把攻略资料离线索引 + 检索，注入 VLM 回答；**不是**对话记忆存储 |
| **来源** | ADR-0012 v5（2026-07-24 定稿，明确 wiki=攻略 not 对话记忆）+ `MEMORY.md` |
| **对话证据** | 会话记录/审查本地Wiki向量检索架构设计.json（07-24 17:17「补 ADR-0012 钉死 wiki=攻略库」、18:48「ADR-0012 更新为 v2」、21:39「v4 定稿已落盘、ADR-0012 翻为 Accepted」、22:52「bge-m3 在硅基流动是免费 API，设计意图=硅基流动」）—— 三源一致。注：对话 07-24 21:39 称「v4 定稿」，决策书+代码注释采用 v5（siliconflow 默认），为同日 v4→v5 小幅修订，事实一致 |
| **校验** | `head -5 docs/ADR-0012-v6-proposal.md` |
| **预期** | 看到 "游戏攻略" / "wiki" 关键词 |
| **Drift** | 2026-07-24 前误以为 Local Wiki 是对话记忆存储 → 引入 RecallFilter session_ids 隔离（后明确 wiki 用 namespace 隔离） |
| **Owner** | 审查协调 |
| **锁定** | ✅ |

---

### D-2026-07-25-041 | 方案 C = bge-m3 + USearch + Obsidian 风格 md
| 字段 | 内容 |
|---|---|
| **事实** | 三件套： |
| | **bge-m3** 双栖向量（本地 SentenceTransformer 建库 + vLLM/硅基 API 召回） |
| | **USearch 侧车 HNSW**（每 namespace 一份 `.usearch`） |
| | **Obsidian 风格 md**（图文混排，图片纯文本引用，不向量化） |
| **来源** | ADR-0012 v6 提案（2026-07-25，取代 v5 双栖设计）+ `doc/adr/0005-memory-store-start.md` |
| **校验** | `grep -E "USearch|bge-m3|Obsidian" docs/ADR-0012-v6-proposal.md` |
| **预期** | 命中 3+ 关键词 |
| **Drift** | 早期 v0.1/v0.2 漂移为对话记忆存储 → 第 3 次需求澄清后定方案 C（2026-07-25） |
| **Owner** | 架构 |
| **锁定** | ✅ |

---

### D-2026-07-25-042 | namespace 命名约定
| 字段 | 内容 |
|---|---|
| **事实** | namespace = `wiki:<游戏名>`，例：`wiki:elden-ring` / `wiki:ba-wukong`；作为增删边界（按 namespace 整批同步/删除） |
| **来源** | ADR-0012 v6（2026-07-25） |
| **校验** | `curl -fsS http://127.0.0.1:8997/v1/namespaces -m 3 | jq -r '.namespaces[]'` |
| **预期** | 至少含 `wiki:elden-ring` |
| **Drift** | 早期未约定前缀 → 跟对话记忆 namespace 混淆 |
| **Owner** | 后端 |
| **锁定** | ✅ |

---

### D-2026-07-26-043 | 前端 F1-F4（#37 已合）
| 字段 | 内容 |
|---|---|
| **事实** | **F1** = 知识库列表（`GET /v1/namespaces`）；**F2** = 健康面板（`GET /v1/providers/health`）；**F3** = 网络设置（`GET/PUT /v1/settings/network`）；**F4** = 同步/删除（`POST /v1/external/sync` + `DELETE /v1/namespaces/{ns}`） |
| **来源** | #37（2026-07-26 squash → 9692d01）+ `services/webui/static/wiki_frontend.js` + `index.html` |
| **校验** | `git show 9692d01:services/webui/src/joy_interaction_webui/static/wiki_frontend.js | grep -E "wiki|F1|F2|F3|F4" | head -5` |
| **预期** | 含 F1-F4 关键词 |
| **Drift** | #39（2026-07-27）修了 `wikiNamespace` 同步 bug（`syncWiki` 读 `wikiNamespace` 输入而非 path 派生） |
| **Owner** | 前端 |
| **锁定** | ✅ |

---

### D-2026-07-27-044 | 前端 F4 syncWiki 修复（#39）
| 字段 | 内容 |
|---|---|
| **事实** | `wiki_frontend.js` L183 `syncWiki(namespace)` 优先读 `#wikiNamespace` 输入框；`#wikiNamespace` 在 `index.html` L518 已有；缺保底 `|| {}` 防 undefined |
| **来源** | #39（2026-07-27 squash → c91b22c）+ `services/webui/src/joy_interaction_webui/static/wiki_frontend.js` |
| **校验** | `grep -n "wikiNamespace" services/webui/src/joy_interaction_webui/static/wiki_frontend.js` |
| **预期** | 命中 2+ 行（syncWiki 读取 + 初始化） |
| **Drift** | 修复前传的是 path 派生 namespace，跟用户输入不一致 |
| **Owner** | 前端 |
| **锁定** | ✅ |

---

### D-2026-07-27-045 | 后端 B1-B4（#38 已合）
| 字段 | 内容 |
|---|---|
| **事实** | **B1** = `client_factory.py` per-provider proxy routing（siliconflow / nvidia / local 三 provider）；**B2** = `NetworkConfig` / `ProxyConfig` 模型层；**B3** = `GET /v1/providers/health` 真实 ping；**B4** = `GET/PUT /v1/settings/network` 网络设置热生效 |
| **来源** | #38（2026-07-27 squash → 0ac6d10）+ `services/memory-store/src/memory_store/app.py:274,295,316` |
| **校验** | `grep -nE "@app\.(get|put)\(.v1/(providers/health|settings/network)" services/memory-store/src/memory_store/app.py` |
| **预期** | 命中 3 行（274/295/316） |
| **Drift** | 2026-07-27 误以为 B3/B4 是后端漏实现（实际是磁盘被沙箱陷阱删，已还原） |
| **Owner** | 后端 |
| **锁定** | ✅ |

---

### D-2026-07-27-046 | B9 金标评测（recall@5 = 24/24）
| 字段 | 内容 |
|---|---|
| **事实** | 离线 fts5 评测 24/24 全过；真机 vector recall 待硅基流动充值（账户 -0.0239 元欠费，key 有效） |
| **来源** | #38（2026-07-27，golden recall eval 合入）+ `datasets/` |
| **校验** | `ls datasets/` |
| **预期** | 含评测 corpus 文件 |
| **Drift** | 离线 fts5 全过 ≠ 真机 vector recall 全过（硅基 API 受账户余额阻塞） |
| **Owner** | 后端 |
| **锁定** | 🔓（待硅基充值后真机 parity） |

---

### D-2026-07-26-047 | 端到端验收例程（运维端）
| 字段 | 内容 |
|---|---|
| **事实** | 完整端到端验收必须走： |
| | 1. `start-joyai.ps1 -Mode default` 拉全套 |
| | 2. **手动** `$env:JOYAI_MEMORY_STORE_URL="http://127.0.0.1:8997"` 后启动 webui（`run-windows.env` 未覆盖，见 D-008/D-030） |
| | 3. 打开 :8099 → 玩家问游戏攻略问题 |
| | 4. 验 F1（namespaces 列表） / F2（健康面板） / F3（网络设置） / F4（同步） |
| | 5. 验后端 B3 / B4（通过 webui 面板间接验证） |
| **来源** | `分析/交叉验证与各端方案-20260727.md` §四 给运维/启动端 + 8997 确立 2026-07-26 |
| **校验** | `curl -fsS http://127.0.0.1:8070/health -m 3 | jq -e '.memory_store.healthy == true'` |
| **预期** | exit 0 |
| **Drift** | 2026-07-26 之前测试绿是 fake memory-store 掩盖后端缺失；**真机验收必须 8099 → 8070 → 8997 链路通** |
| **Owner** | 运维 |
| **锁定** | ✅ |

---

### D-2026-07-25-048 | 知识库本地建库命令
| 字段 | 内容 |
|---|---|
| **事实** | 本地 bge-m3 离线建库走： |
| | `python -m memory_store.scripts.seed_wiki --provider local --namespace <ns> --db data/memory.sqlite --vec-dir data/vec/ --drop-first --corpus <path>` |
| | 默认建库 venv = `D:\AI\envs\joyai-main`（CPU 跑，GPU 需另装 CUDA torch） |
| **来源** | bge-m3 路径澄清（2026-07-25）+ `services/memory-store/scripts/seed_wiki.py` |
| **校验** | `ls services/memory-store/scripts/seed_wiki.py` |
| **预期** | 找到脚本 |
| **Drift** | 2026-07-25 误以为脚本走 GPU（实际 joyai-main venv CPU 跑） |
| **Owner** | 后端 |
| **锁定** | ✅ |

---

## Drifts（漂移历史，仅追加）

### 2026-07-24 — v0.1/v0.2 漂移为对话记忆存储
- 误以为 Local Wiki = 对话记忆
- 加 RecallFilter session_ids 隔离
- 第 3 次需求澄清后定方案 C（2026-07-25）：namespace = `wiki:<游戏>`、图文混排剧本

### 2026-07-25 — bge-m3 路径歧义
- 误以为 `bge-m3` 在 `D:\AI\bin\llama.cpp\`（GGUF 路径）
- 实际：bge-m3 在 `D:\AI\models\bge-m3\`（SentenceTransformer 路径）
- llama.cpp GGUF 不支持 bge-m3 嵌入（生成式运行时）
- **铁律**：本地建库 = SentenceTransformer；生产嵌入 = vLLM embed / 硅基 API

### 2026-07-27 — B3/B4 误判缺口
- F2/F3 报 404 → 误判后端漏实现
- 真因：磁盘工作树被沙箱陷阱静默删
- 修复：`git checkout HEAD -- services/memory-store/`（22:45）

### 2026-07-27 — bge-m3 默认 provider 改 nvidia（P1，已闭环）
- #38（2026-07-27 `0ac6d10`）改默认 provider 为 `nvidia`（国内通常不可达），无 ADR 记录
- **2026-07-28 #42 已 revert 默认回 `local`**（`embedder.py:15-17,83-89`；当前 `EMBEDDING_PROVIDER` 默认 `local`），`nvidia`/`siliconflow` 仍可选
- 对话证据：`会话记录/审查本地Wiki向量检索架构设计.json`（07-24 22:52）设计意图=硅基流动免费 API；印证 #38 临时改 nvidia 偏离设计、#42 回归 local
- 状态：✅ 原 P1 待裁决已闭环（默认=`local`）
- `modified: 2026-07-28｜by AI｜approved: §0.4召回轮特许（交叉验证修正陈旧漂移）`

---

## 待补充

- D-XXX：图文混排 .md 注入 prompt 的格式约定（前缀 / 块引用 / 图片文本引用）
- D-XXX：recall 后的 context 长度截断（防止 VLM 上下文溢出）
- D-XXX：F4 sync 时的 chunk 切分规则（heading / paragraphs）
- D-XXX：bge-m3 量纲 vs 切分句数（max_seq_length）
- D-XXX：真机 vector recall 验收脚本（硅基充值后）
