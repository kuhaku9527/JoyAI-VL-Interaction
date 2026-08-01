# 服务-memory-store / :8997 bge-m3 召回后端

> 范围：`:8997` memory-store + bge-m3 语义召回；Local Wiki 后端 ADR-0012 落地。
> 真相源：`services/memory-store/src/memory_store/app.py` + ADR-0012 + 实测。
> **修改走 §0 治理协议（AI 提议 → 用户同意 → 落盘）。**

---

### D-2026-07-26-030 | memory-store 真实端口
| 字段 | 内容 |
|---|---|
| **事实** | memory-store 实际跑在 **`127.0.0.1:8997`**（非 8996）；webui 必须经 `JOYAI_MEMORY_STORE_URL=http://127.0.0.1:8997` 启动。**⚠️ `run-windows.env` 并未覆盖 `MEMORY_PORT` / `JOYAI_MEMORY_STORE_URL`**（实测 grep 零命中），须每次手动设 env；这是已知漂移，待 #43 修脚本自动注入** |
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
| **Drift** | ✅ 2026-08-01 复核：embedder.py:89 默认实为 `local`（#42 于 07-28 revert，非 #38 的 nvidia）。原 P1「nvidia 默认不可达」告警系误读（基于 #38 中间态），已关闭。默认 local 与 D-038 设计一致。modified: 2026-08-01｜by AI｜approved: 用户 |
| **Owner** | 后端 |
| **锁定** | ✅ |

---

### D-2026-08-01-038 | E4 根因：EMBEDDING_LOCAL_MODEL 未接线（配置漂移）
| 字段 | 内容 |
|---|---|
| **事实 | Local Wiki 语义召回（E4）不健康的真因 = **配置漂移**。本地 bge-m3 完整 checkpoint 在 `D:/AI/models/bge-m3`（pytorch_model.bin 2.27G + config.json + `1_Pooling/`/tokenizer 全套，07-27 验收已证实可用）。但 `EMBEDDING_LOCAL_MODEL` **全仓库未设**（run-windows.env grep 零命中；git log -p 全历史零命中）→ embedder.py:102/238 默认模型名落到 `BAAI/bge-m3`（HF hub id）→ HF 缓存 `.cache/huggingface/hub/models--BAAI--bge-m3/` 存在但**不完整**（总 40K；blobs=3 个 0 字节 .incomplete，Jul 29/31 三次下载尝试均失败）→ `SentenceTransformer("BAAI/bge-m3")` 加载失败 → `EmbedderError`(embedder.py:220) → `wiki_service.sync_wiki_dir`:91-93 静默存文本块 `vector=None` → 语义召回(ANN 无向量)返回空 → E4"召回不健康"。`available()`(embedder.py:127-133) 对 local **无条件返回 True**，不校验模型可加载，掩盖根因。**根因 = 缺 env 接线（配置漂移），非代码 bug**。07-27 曾验收通过(embedded=3, recall cos=0.65~0.74)，但使成功的 env 配置从未持久化到 run-windows.env（可能为临时终端设置或网络下载成功后缓存丢失/迁移）。 |
| 来源 | 2026-08-01 健康深扒 FA-4（三源交叉：git 历史 + 磁盘文件 + HF 缓存）；embedder.py:89/102/127/220/238 + wiki_service.py:91-93 + run-windows.env(grep 零命中) + test_local_real_recall.py(明确要求设该变量) + HF 缓存时间线重建 |
| 校验 | 起服务后 `curl http://127.0.0.1:8997/v1/providers/health` 应见 embedding `ok:true`；wiki sync 后 `embedded>0`；真实提问 Local Wiki 召回应返回块 |
| 预期 | embedding available + 有向量召回 |
| Drift | 🟥 `available()`(embedder.py:127) 对 local 无条件 True 不校验模型可加载，掩盖根因；run-windows.env 未导出 `EMBEDDING_LOCAL_MODEL`；HF 缓存残留不完整残骸（可清理） |
| Owner | 后端（实施 T-06）/ 运维（验证） |
| 锁定 | 🔓（T-06 修复实施中） |

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

## Drifts（漂移历史，仅追加）

### 2026-07-27 22:35 — B3/B4 缺口翻案
- **症状**：前端 F2/F3 报 404 → 误判后端漏实现
- **真因**：磁盘工作树被沙箱 git 写陷阱静默删除（40 文件 / -1679 行，config.py/client_factory.py 物理删除，app.py 228→360 行）
- **修复**：`git checkout HEAD -- services/memory-store/`（22:45），py_compile 全绿；git HEAD 完整（app.py:274/295/316 三路由齐全）
- **教训**：看"代码缺失"必须先 `git show HEAD:` 确认 git 真值，再查磁盘

### 2026-07-25 — 端口拓扑混乱
- **症状**：8996 vs 8997 哪个是真后端搞不清
- **修复**：8997 确立为生产（2026-07-26）；`run-windows.env` 未覆盖，须手动 env（见 D-030）

### 2026-08-01 — E4 根因定位 + T-02 结案 + D-033 误读修正
- E4 真因 = **EMBEDDING_LOCAL_MODEL 未设**（配置漂移，FA-4）；本地权重 `D:/AI/models/bge-m3` 完整但未被引用 → wiki 建库无向量。修复见 **D-038 / T-06**。
- T-02「E2/E3 token 泄露」猜想代码深扒无真实泄漏（FA-5），关闭，无需修复。
- D-033 默认 provider 误读（nvidia）复核为 local（#42 于 07-28 revert），P1 漂移关闭，**锁定 ✅**。
- FA-2 补充：webinfer 端口假设不成立（启动链路证明实际连 8997）。
- FA-3 补充：embedder.py:89 默认实为 local，非 nvidia。
- HF 缓存残留：`.cache/huggingface/hub/models--BAAI--bge-m3/` 存在但不完整（40K，0 字节 incomplete blobs ×3），可清理。

### 2026-07-27 — bge-m3 默认 provider 漂移（P1，已解决）
- #38 把默认改 `nvidia`，无 ADR 记录 → #42 revert 回 `local`（已解决，见 D-033 修正）

---

## 待补充

- D-XXX：memory-store 数据持久化路径（`data/memory.sqlite` 默认）
- D-XXX：recall 默认参数（top_k / min_score / namespaces 列表）
- D-XXX：mock 模式 vs 真实模式（env 变量）
- ~~D-XXX：embedding 模型切换 ENV（EMBEDDING_LOCAL_MODEL / EMBEDDING_PROVIDER）~~ → **已由 D-038 覆盖**
