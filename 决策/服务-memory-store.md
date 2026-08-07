# 服务-memory-store / :8997 bge-m3 召回后端

> 范围：`:8997` memory-store + bge-m3 语义召回；Local Wiki 后端 ADR-0012 落地。
> 真相源：`services/memory-store/src/memory_store/app.py` + ADR-0012 + 实测。
> **修改走 §0 治理协议（AI 提议 → 用户同意 → 落盘）。**

---

### D-2026-07-26-030 | memory-store 真实端口
| 字段 | 内容 |
|---|---|
| **事实** | memory-store 实际跑在 **`127.0.0.1:8997`**（非 8996）；webui 必须经 `JOYAI_MEMORY_STORE_URL=http://127.0.0.1:8997` 启动。**⚠️ `run-windows.env` 并未覆盖 `MEMORY_PORT` / `JOYAI_MEMORY_STORE_URL`**（实测 grep 零命中）~~，须每次手动设 env；这是已知漂移，待 #43 修脚本自动注入~~ **该漂移已由 PR #83/#84（D-034 端口固定 8997）闭环：run-windows.env 现含 8997 覆盖，默认连真后端；归属非 #43（#43=视频采集端到端延迟调研）**。modified: 2026-08-07｜by AI｜approved: 用户** |
| **来源** | 8997 确立为生产后端于 2026-07-26；`services/webui/.../server.py` 默认 8996；`run-windows.ps1:114` 默认 8996 |
| **校验** | `curl -fsS http://127.0.0.1:8997/health -m 3` |
| **预期** | 200 OK |
| **Drift** | 🟥 `run-windows.ps1:114` 默认 `MEMORY_PORT=8996`（空壳）；须手动 env 覆盖为 8997（详见 `启动链路.md` D-008） |
| **Owner** | 运维 |
| **锁定** | ✅ |

---

### D-2026-07-26-031 | 8996 端口废弃
| 字段 | 内容 |
|---|---|
| **事实** | `127.0.0.1:8996` = 历史空壳，无服务监听；**禁止**任何脚本/agent 启动 8996 记忆服务 |
| **来源** | 8996 早期由 ADR-0005（2026-07-12）定为 memory-store skeleton 默认；8997 于 2026-07-26 取代为生产 |
| **校验** | `curl -fsS http://127.0.0.1:8996/health -m 2 2>&1; netstat -ano | grep ":8996" | grep LISTENING` |
| **预期** | curl 失败 + 0 LISTENING |
| **Drift** | 2026-07-26 误以为 8996 是真后端，前端 F2/F3 全 502 |
| **Owner** | 运维 |
| **锁定** | ✅ |

---

### D-2026-07-25-032 | memory-store 路由全集
| 字段 | 内容 |
|---|---|
| **事实** | `app.py` 暴露的关键路由： |
| | `GET /health` — liveness |
| | `GET /v1/backends` — 列出 embeddings provider |
| | `POST /v1/blocks/push` — 写入记忆块 |
| | `POST /v1/blocks/recall` — 召回（含 Local Wiki 语义） |
| | `POST /v1/external/sync` — Local Wiki 外部知识库同步 |
| | `GET /v1/namespaces` / `POST /v1/namespaces` — namespace 列表/创建 |
| | `DELETE /v1/namespaces/{ns}` — 删 namespace |
| | `GET /v1/providers/health` — B3/F2 健康面板（real ping） |
| | `GET /v1/settings/network` — B4/F3 读网络设置 |
| | `PUT /v1/settings/network` — B4/F3 写网络设置 |
| | `POST /v1/external/ingest-text` — 网关暂存 .md 转 sync |
| **来源** | #36（2026-07-25 引入 recall/sync/namespaces）+ #38（2026-07-27 引入 B3/B4 providers/health、settings/network）；`services/memory-store/src/memory_store/app.py:95,162,195,274,295,316` |
| **校验** | `grep -nE "@app\.(get|post|put|delete)\(" services/memory-store/src/memory_store/app.py` |
| **预期** | 命中 11+ 行 |
| **Drift** | 🟥 2026-07-27 误以为 B3/B4 路由缺失，实际是磁盘文件被沙箱陷阱删（已 `git checkout HEAD --` 还原，py_compile 全绿） |
| **Owner** | 后端 |
| **锁定** | ✅ |

---

### D-2026-07-24-033 | bge-m3 双栖模式（建库 vs 召回）
| 字段 | 内容 |
|---|---|
| **事实** | bge-m3 嵌入走两份 provider： |
| | **建库** = 进程内 SentenceTransformer（`local` provider），CPU 跑（venv `D:\AI\envs\joyai-main` 装 `sentence_transformers==5.6.1`） |
| | **召回** = vLLM embed API（生产部署，GPU）或硅基流动 API（双栖设计） |
| | 双栖一致性铁律：建库 provider ≠ 召回 provider → 空间不一致；必须同源 |
| **来源** | ADR-0012 v5（2026-07-24 双栖定稿）+ `services/memory-store/src/memory_store/config.py` |
| **校验** | `grep -nE "provider.*local|provider.*siliconflow|provider.*nvidia" services/memory-store/src/memory_store/config.py` |
| **预期** | 命中 provider 枚举 |
| **Drift** | 🟥 **P1 待裁决**：#38（2026-07-27）把 `BgeM3Embedder` 默认 provider 从 `siliconflow` 改为 `nvidia`（`integrate.api.nvidia.com/v1`，默认 `use_proxy=false` 国内通常不可达），注释指向 ADR-0012 但设计文档无对应记录 → 新部署大概率开箱即败。三选一：①恢复硅基；②保留 NVIDIA 但补 ADR+代理；③默认 `local`（开箱即用但吃本地算力） |
| **Owner** | 后端 |
| **锁定** | 🔓（P1 设计偏离，待裁决后锁） |

---

### D-2026-07-25-034 | USearch 侧车 HNSW（每 namespace 一份）
| 字段 | 内容 |
|---|---|
| **事实** | 每 namespace（`wiki:<游戏>`）在 `data/vec/` 目录下有独立 `.usearch` 文件（HNSW 索引）；与 `data/memory.sqlite` 同源；`.gitignore` 已忽略 `*.usearch`（commit c5d87f5，2026-07-28） |
| **来源** | #36（2026-07-25 引入 USearch 侧车）+ `doc/adr/0005-memory-store-start.md` |
| **校验** | `ls data/vec/*.usearch 2>/dev/null | wc -l` |
| **预期** | ≥ 1 个（live 环境下有真实 namespace） |
| **Drift** | 早期 `.gitignore` 只忽略 `*.sqlite`，`.usearch` 误被 `git add -A` 提交过 → 2026-07-28 补 `.gitignore` 行（c5d87f5） |
| **Owner** | 后端 |
| **锁定** | ✅ |

---

### D-2026-07-25-035 | memory-store 启动方式
| 字段 | 内容 |
|---|---|
| **事实** | memory-store 由 `run-windows.ps1` 拉起（`memory-store` pid 名），支持 `mock` 或真实模式（mock 用于 local dev 离线） |
| **来源** | #36（2026-07-25 语义召回落地）+ `services/scripts/run-windows.ps1` |
| **校验** | `curl -fsS http://127.0.0.1:8997/health -m 3 | jq -e '.ok == true'` |
| **预期** | exit 0 |
| **Drift** | webui 若连不上 8997 → 502（端口覆盖铁律详 `跨域铁律.md` D-010） |
| **Owner** | 运维 |
| **锁定** | ✅ |

---

### D-2026-07-27-036 | NetworkConfig / ProxyConfig 类型
| 字段 | 内容 |
|---|---|
| **事实** | `config.py` 含 `NetworkConfig` / `ProxyConfig` / `NetworkConfigStore` / `get_network_config` / `update_network_config`；模型在 `models.py` `NetworkSettingsRequest`（B2，#38 引入） |
| **来源** | #38（2026-07-27）+ `services/memory-store/src/memory_store/config.py` + `models.py` |
| **校验** | `grep -nE "class NetworkConfig|class ProxyConfig|NetworkConfigStore" services/memory-store/src/memory_store/config.py` |
| **预期** | 命中 3+ 行 |
| **Drift** | 🟥 2026-07-27 误以为配置文件被删（实际是工作树被沙箱陷阱删，已 `git checkout HEAD --` 还原） |
| **Owner** | 后端 |
| **锁定** | ✅ |

---

### D-2026-07-26-037 | gateway 代理契约（webui server.py）
| 字段 | 内容 |
|---|---|
| **事实** | `services/webui/src/joy_interaction_webui/server.py` 对 B3/B4/B1 仅做**纯盲转发**到 `MEMORY_STORE_URL+path`（L1219-1221 + L961-993），不合成；后端 404 时网关 502 透明透传 |
| **来源** | #37（2026-07-26 前端网关路由）+ `webui/server.py:1219-1221` + `webui/server.py:961-993` |
| **校验** | `grep -nE "_proxy_to_memory_store|/v1/(providers/settings|external|namespaces)" services/webui/src/joy_interaction_webui/server.py` |
| **预期** | 命中 5+ 行 |
| **Drift** | 2026-07-26 修过代理 bug：转发 Content-Type 含 `; charset` 会被 aiohttp 抛错，已剥离 charset 后透传 |
| **Owner** | 后端 |
| **锁定** | ✅ |

---

### D-2026-08-05-001 | bge-m3 local 模型路径 / HF 缓存坏 → /v1/providers/health 500 根因 + 修复
| 字段 | 内容 |
|---|---|
| **事实** | memory-store local 嵌入（`EMBEDDING_PROVIDER=local`，PR #42 已将 #38 的 nvidia 改回 local）加载模型时：`EMBEDDING_LOCAL_MODEL` 未设 → 默认 `BAAI/bge-m3`；`HF_HOME` 被重定向到仓库内 `<ws>/.cache/huggingface`，该缓存 `config.json` 为**空文件** → `sentence_transformers` 加载时 `json.load` 抛 `JSONDecodeError`（ValueError 子类，**不是** `EmbedderError`）→ `embedder.health()` 仅 `except EmbedderError`，`providers_health()` 调 `embedder.health()` 未套 try → 原始异常冒泡 → **HTTP 500**。仓库外 `D:/AI/models/bge-m3/` 有完整有效模型（2.27GB，config.json 正常）。 |
| **来源** | 2026-08-05 实测 + kb-runner 同款 venv 复现（100% 确认）。`services/memory-store/src/memory_store/embedder.py:240` `_get_local_model`。 |
| **校验** | `curl -s --max-time 12 http://127.0.0.1:8997/v1/providers/health` → 应 200 且 `embedding.ok=true, model="D:/AI/models/bge-m3"`。修复前基线为 500。 |
| **预期** | 200，embedding.ok=true，不再 500。 |
| **修复** | ①代码守卫：`embedder.py:_get_local_model` 把 `SentenceTransformer(name)` 包进 `try/except Exception → raise EmbedderError(...)`（health/sync 优雅降级，不再 500）。②运行时定址：`run-windows.env` 追加 `EMBEDDING_LOCAL_MODEL=D:/AI/models/bge-m3`（指向仓库外有效权重）。 |
| **Drift** | 🟥 默认去仓库内坏缓存（空 config.json）加载，而非仓库外有效模型；且 `run-windows.env` 被 `.gitignore`（`*.env`）忽略，env 写入**不进版本控制**——若该文件被重置，需重设 `EMBEDDING_LOCAL_MODEL`。embedder.py 守卫是版本控制层的兜底（模型加载失败 → ok=false 而非 500）。后续建议：在 `run-windows.ps1`（git 跟踪）硬编码 `EMBEDDING_LOCAL_MODEL` 默认值以彻底版本控制定住。 |
| **Owner** | 后端 |
| **锁定** | ✅ |

### D-2026-08-05-002 | memory-store 与 Local Wiki 同进程同端口（8997）；驳"共用端口冲突"误解
| 字段 | 内容 |
|---|---|
| **事实** | Local Wiki **不是独立服务**，是 memory-store 的功能模块：其全部后端端点（`POST /v1/external/sync`、`GET /v1/namespaces`、`POST /v1/blocks/recall`、`GET /v1/providers/health`）全挂在 `services/memory-store/src/memory_store/app.py`。`services/` 顶层**无独立 local-wiki 服务**。`ADR-0012-v6` 讨论的"独立服务（建议 :7999）"指 **embedding 嵌入推理服务**（方案 B，显存隔离），**非** Local Wiki；且 ADR-0012 最终落地默认**方案 A（进程内 local 直载）**。Local Wiki 数据+API 始终在 memory-store(:8997)。 |
| **来源** | 2026-08-05 查证 `services/` 结构 + `doc/adr/ADR-0012-v6-proposal.md`。 |
| **校验** | `ls services/`（无 local-wiki）；`grep -nE "@app.(get|post)" services/memory-store/src/memory_store/app.py`（wiki 端点均在 memory-store）。 |
| **预期** | Local Wiki 后端 = memory-store(:8997)，单一进程单一端口。 |
| **Drift** | 用户曾疑"memory-store 与 local wiki 共用端口冲突"——不成立，本就同端口同进程；ADR-0012 的 :7999 是 embedding 服务非 Local Wiki。 |
| **Owner** | 后端/运维 |
| **锁定** | ✅ |

---

### D-2026-08-05-003 | recall 删除 FTS5 BM25 兜底，只留向量语义路径（已落地，锁定）
| 字段 | 内容 |
|---|---|
| **事实** | 语义召回 `recall` **只保留向量（bge-m3 余弦）路径，删除 FTS5 BM25 兜底分支**：不再 `if namespaces and embedder: vector else fts`；改为 **`filter.namespaces` 必填（作用域）→ 向量语义召回；embedder 不可用 → 抛 `EmbedderError`（HTTP 5xx）；裸 recall（无 namespace）→ 显式报错（HTTP 400）**。杜绝静默降级到对中文整句不友好的 BM25（裸 recall 返回空、看起来像"算法坏了"）。 |
| **来源** | 用户 2026-08-05 裁定："不要设置 fallback，不要两条路，不要 # FTS5 BM25（兜底）；我只要向量语义路径"。旧行为局限见上方 Drifts「语义召回两条已知局限·局限 1」。 |
| **设计** | ①删 `_recall_fts` 函数及其路由（含 FTS5 虚拟表/触发器，确认无引用后）；②`recall` 仅向量：**`filter.namespaces` 必填**——裸 recall（无 namespace）→ 显式报错（HTTP 400，**禁止**静默空/落 BM25）；embedder 不可用 → 抛 `EmbedderError`（HTTP 5xx，明确失败**不静默**）；③`__warmup__`（取最近块）抽为独立 SQL 路径，不依赖 BM25；④向量结果补 `session_ids`/`created_after` 后过滤（原 BM25 能力，避免回归）；⑤`score` 恒 1.0 局限本轮不动（见 Drifts），后续回传真 cosine/HNSW 距离。 |
| **校验** | 裸 `recall`（无 namespace）不再静默空/落 BM25，而是明确错误；embedder down 时 recall 返回明确错误而非 200 空。需 grep 所有 `recall` 调用方确认都带 `filter.namespaces`，缺者补 scope 或更新调用。 |
| **Drift** | 旧 BM25 分支注释自称 "legacy FTS5 BM25 path … fail-open fallback when the embedding API is down"——违反约法三章「禁 fallback / 禁静默返回」（`决策/AI代码质量约法三章.md`），故删。 |
| **Owner** | 后端 |
| **锁定** | ✅（设计锁 + 代码已落地：任务 #33 完成；裸 recall 显式 400、embedder down 显式 5xx，无 BM25 兜底、无静默降级） |

---

## Drifts（漂移历史，仅追加）

### 2026-07-27 22:35 — B3/B4 缺口翻案
- **症状**：前端 F2/F3 报 404 → 误判后端漏实现
- **真因**：磁盘工作树被沙箱 git 写陷阱静默删除（40 文件 / -1679 行，config.py/client_factory.py 物理删除，app.py 228→360 行）
- **修复**：`git checkout HEAD -- services/memory-store/`（22:45），py_compile 全绿；git HEAD 完整（app.py:274/295/316 三路由齐全）
- **教训**：看"代码缺失"必须先 `git show HEAD:` 确认 git 真值，再查磁盘

### 2026-07-25 — 端口拓扑混乱
- **症状**：8996 vs 8997 哪个是真后端搞不清
- **修复**：8997 确立为生产（2026-07-26）；`run-windows.env` 未覆盖，须手动 env（见 D-030）

### 2026-07-27 — bge-m3 默认 provider 漂移（P1）
- #38 把默认改 `nvidia`，无 ADR 记录，国内通常不可达 → 待裁决（见 D-033）

### 2026-08-05 — 语义召回两条已知局限（实测确认）
- ~~**局限 1｜裸 recall 掉 BM25 兜底返回空**~~ → **已解决（2026-08-05 #33 落地）**：原裸 recall 掉进 FTS5 BM25 分支对中文整句返回空；现裸 recall（无 namespace）显式报错 400，不再静默落 BM25。语义命中仍需显式 `filter.namespaces`（作用域必填）。
- **局限 2｜返回的 `score` 恒 1.0，非余弦相似度**：`recall_blocks` 返回的 `score` 字段是**块存储相关性分**（命中即 1.0），**不是**向量余弦距离；前端/调用方不能用该 `score` 做相似度排序或阈值过滤，会全部相等。语义相关性需日后改为回传真实 cosine 值或 HNSW 距离（本轮不动）。
- **影响**：调用方若指望裸 recall 做中文语义搜索、或用 score 排序，都会踩坑。局限 1 已随 #33 落地解决；局限 2 仍在（4 条中文语义 query 显式带 namespace → top-1 全命中对应 BOSS，已在临时实例 8998 用真实 bge-m3 端到端复现）。
- **2026-08-05 裁定（D-2026-08-05-003，任务 #33 已落地）**：FTS5 BM25 兜底**已删除**，recall 只留向量语义路径；裸 recall（无 namespace）已改为**显式报错 400**（不再静默空/落 BM25），embedder down → 明确 5xx。局限 1 旧行为已失效，以 D-2026-08-05-003 为准。

---

## 待补充

- D-XXX：memory-store 数据持久化路径（`data/memory.sqlite` 默认）
- ~~D-XXX：embedding 模型切换 ENV（EMBEDDING_LOCAL_MODEL / EMBEDDING_PROVIDER）~~ → 已补：见 D-2026-08-05-001
- D-XXX：recall 默认参数（top_k / min_score / namespaces 列表）
- D-XXX：mock 模式 vs 真实模式（env 变量）
