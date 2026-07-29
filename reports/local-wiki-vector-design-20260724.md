# Local Wiki 向量化（方案 C）设计 + 推荐架构

> 日期：2026-07-24（v5 定稿）｜ 2026-07-28 v6 追加：**PR #42 已合 main (c8da4dea28，P1 修复 + handoff 方案 A 落地)，CI 全绿**
> 角色：架构（后端记忆 / Hermes 桥接对话）
> 背景：[Local Wiki] 原始定义 = **游戏攻略 / 角色 lore 预置外部知识库**（游戏直播注入 `/v1/solve`）。演进：v1 sqlite-vec exact KNN → v2 HNSW+本地视觉模型 → v3 MiniMax 云嵌入 → v4 gemini-embedding-2 统一空间（⚠️ 基于错误的免费限额假设，已被推翻）→ **v5：经限额核实与 API/本地严肃取舍，回归 bge-m3 双栖方案**。
> 调研通道：Exa（.mcp.json key）+ Tavily + WebSearch；证据见 §10。关键修正记录见 §3。

---

## 0. 一句话结论（v5 定稿）

- **索引**：USearch 侧车 HNSW；**每 `namespace`（=每个游戏）一个 `.usearch` 文件**；删游戏 = 删文件 + 一行 SQL。
- **文本嵌入**：**bge-m3（1024d）双栖**——**建库跑本地 GPU**（离线、免费、无频率限制、万级 chunk 分钟级完成），**召回走硅基流动免费 API**（¥0、OpenAI 兼容、国内直连、~50–200ms）。同一模型 → 同一向量空间 → 召回有效（空间一致性铁律，§2.3）。
- **图片**：**文本引用**（不建图片向量）。图片实体存 `wiki/<游戏>/assets/`，block 记 `images[]` 路径+alt 说明；文字命中攻略块后，图片随块注入，主模型（有视觉）**直接读原图**。
- **成本**：**¥0**（建库本地 + 召回免费 API + 图片零请求）；运行时显存 0 占用（全部归主模型+游戏）。
- **网络**：一期出站全部国内（硅基+MiniMax），代理模块做成**预留**（per-provider 设计，Gemini 若启用走 Clash 7890）；`GET /v1/providers/health` 统一健康检测。
- **资料**：项目只承诺输入契约；`tools/fetch_wiki.py` 保留为官方工具+自测；四层保底。

### 0.1 v6 增补（PR #42，2026-07-28，CI 全绿）

- **embedder 默认 provider**：nvidia → **local**（ADR-0012 §6 落地）。NVIDIA / SiliconFlow 仍可选（`EMBEDDING_PROVIDER` 切换），用于跨空间一致性验证。未知 provider 抛 `ValueError`。
- **webinfer 聊天接入 Local Wiki**（[`reports/local-wiki-chat-integration-analysis-20260728.md`](local-wiki-chat-integration-analysis-20260728.md) 方案 A 变体 2）：
  - `_memory_recall` 每次玩家提问时，在 warmup cache 之外**并行**触发一次 Local Wiki 语义召回（fail-open，错误仅 warning）
  - 召回结果落入 `state._memory_wiki_cache`，prompt renderer 读两个 cache 渲两段 `[Previous Memory]` + `[Local Wiki]`
  - 每块渲染前缀包含 `ns= / src= / id=`（前世今生、来源 URL、block_id 三件套）
  - `MemoryStoreClient.recall` 增加 `namespaces=` 参数（backend 解析 `wiki:*` 通配）
  - env 旋钮：`WIKI_RECALL_NAMESPACES` / `TOP_K` / `MIN_SCORE` / `ENABLED`，env > config
- **代码 / 测试**：
  - memory-store 16 文件改 +1 新（test_local_real_recall.py），webinfer 7 文件改 +1 新（test_local_wiki_recall.py）
  - pytest：memory-store **64 pass + 7 skip** / webinfer **111 pass**
  - ruff check + format 按 CI 精确命令双服务全绿
  - CI Workflow #42 dispatch 2 runs both success
- **PR #42**：https://github.com/kuhaku9527/JoyAI-VL-Interaction/pull/42 — open, mergeable, **Pending merge**

---

## 1. 索引层：USearch 侧车 HNSW（已确认）

```
data/
  memory.db                     # sqlite：内容 + 元数据 + namespace（唯一真相源）
  vec/
    wiki-elden-ring.usearch     # HNSW（bge-m3, 1024d, cos）
    wiki-zelda-totk.usearch
    ...
```

- **键**：`key = memory_blocks.rowid`（u64）；命中 → sqlite 取 content/images/namespace。sqlite 唯一真相源，索引可随时全量重建（崩溃自愈）。
- **每游戏一文件**：删游戏 = `rm wiki-<游戏>.usearch` + `DELETE … WHERE namespace=…`；直播只 mmap 当前游戏；单篇更新 = `remove+add`。
- **参数起点**：`connectivity=16, expansion_add=128, expansion_search=64, metric=cos`。
- **内存**：5 万向量 × 1024d f32 ≈ 200MB（i8 量化再降 4×，金标集实测后定）。
- **未来 Rust 化零成本**：索引文件跨语言（Rust `Index::restore` 直读），模型调用纯 HTTP——换壳不重建。

## 2. 嵌入方案：bge-m3 双栖 + 图片文本引用（已确认）

### 2.1 双栖架构（核心）

```
【建库 · 离线】                    【召回 · 在线（直播）】
wiki/*.md 切块                     玩家提问
   │                                  │
   ▼                                  ▼
本地 bge-m3（GPU）              硅基流动 BAAI/bge-m3 API
   │  万级 chunk 分钟级               │  ~50-200ms，¥0，国内直连
   ▼                                  ▼
同一向量空间（1024d） ═══════►  USearch KNN → sqlite 取块 → 注入
```

- **为什么双栖成立**：本地权重与托管 `BAAI/bge-m3` 是同一模型 → 同一空间。这是 bge-m3 独有优势（开源权重 + 免费托管 API 双通道）；gemini-embedding-2 只能云。
- **为什么 bge-m3 而非 Gemini**（取舍依据，详见 §3）：中文检索最强（MIRACL/MKQA 多语 SOTA，arXiv 2402.03216；dense+sparse+multi-vec 三合一，专名有 sparse 兜底）；免费（硅基 ¥0，注册即送）；国内直连免代理；OpenAI 兼容零 adapter；与项目 spec（memory-architecture.md）原定模型一致。
- **查询期负载**：每天几十~几百次单条嵌入，免费 API 绰绰有余。

### 2.2 图片：文本引用（机制澄清）

**不是"不注入"，是"不向量化"**：

```
存储：wiki/<游戏>/assets/*.png        ← 图片实体放文件系统，不进 DB
关联：md 里 ![说明](assets/x.png) → block 记 images[] + alt 文字并入块文本
检索：文字问 → bge-m3 命中【文本块】（靠正文+alt 说明）
注入：块的 images[] → 读图（缩放长边 ~768px）→ image_url 随块发主模型
生成：主模型直接看原图作答
```

- 图片角色：**不参与匹配（检索），但参与命中后的理解（注入）**。
- 只有"以图搜文"（贴截图找攻略）才需要图片向量——本期不做，留为备选路径（§9）。

### 2.3 空间一致性铁律（落地三注意）

**建库模型 = 召回模型**，否则距离计算无意义、召回失败。落地保障：

1. **同文双嵌验证**（上线前必做）：同一文本，本地嵌一次、API 嵌一次，余弦相似度须 >0.999；若托管侧量化致漂移，则二选一（全本地或全 API），禁止混用。
2. **预处理统一封装**：embed 调用收敛到单一函数（是否加检索指令前缀等规则只此一处），建库/召回共用，杜绝手工分叉。
3. **归一化**：bge-m3 输出已 L2 归一化，cos 距离直接用，禁止二次归一化。

## 3. 成本与限额：核实修正记录（为什么推翻 v4 的 Gemini 主路线）

| 项 | v4 结论（错误） | 核实结论（官方速率表镜像交叉验证） |
| - | - | - |
| gemini-embedding-2 免费层 | "~1500 req/day，一天跑完 $0" | **preview/实验版 = 5 RPM / 100 RPD**；付费 Tier 1 仅 10 RPM / 1000 RPD。万级嵌入 = 免费层 3–6 天排队（高峰动态下调） |
| 异步 Batch API 半价 | 可用 | **预览版不支持**（仅稳定版功能） |
| 配额稳定性 | 隐含假设稳定 | **2025-12 Google 无预警削减免费配额 50–80%** 前科；preview 模型 ID/价格 GA 时可能变 |

**终账（v5 方案，一个游戏 ≈ 5000 chunk）**：

| 环节 | 路径 | 成本 | 时长 |
| - | - | - | - |
| 建库 | 本地 bge-m3（GPU） | **¥0** | 分钟级 |
| 召回 | 硅基流动 bge-m3（免费 API） | **¥0** | 每次 ~50–200ms |
| 图片 | 不向量化 | **¥0** | — |
| **合计/游戏** | | **¥0** | |

**Gemini 的保留价值**：若未来启用"贴图搜攻略"（§9 备选），gemini-embedding-2 是国内可及的最佳多模态嵌入（图像腿只嵌图，量小，免费层可覆盖增量；或 ~¥7/游戏付费）。key 不浪费，但不做默认路径。

## 4. 网络与代理（预留设计，一期全国内）

```yaml
network:
  proxy: { enabled: false, url: "http://127.0.0.1:7890" }   # 预留开关
providers:
  siliconflow: { use_proxy: false }   # 国内直连
  minimax:     { use_proxy: false }   # 国内直连
  gemini:      { use_proxy: true  }   # 若启用 → Clash（一期不启用）
```

- per-provider 代理，**拒绝全局 `HTTPS_PROXY`**（避免国内流量绕行）。
- 统一 HTTP client factory：所有出站 client 从 factory 取 `use_proxy`。
- 一期代理模块仅做**配置预留**（设置页可见、可测），实际流量全直连。

## 5. API 健康检测（已确认）

`GET /v1/providers/health` → 每 provider 真实 ping（embedding 嵌 "ping"；LLM 1-token completion；本地服务探活）：

```json
{
  "main_llm":     {"ok": true,  "latency_ms": 42},
  "summarizer":   {"ok": true,  "latency_ms": 38},
  "embedding":    {"ok": true,  "latency_ms": 96,  "provider": "siliconflow/bge-m3"},
  "memory_store": {"ok": true,  "latency_ms": 3},
  "tts":          {"ok": true,  "latency_ms": 5}
}
```

- **必须与真实调用同配置路径**（同代理同 key 同 endpoint），杜绝假绿灯。
- 失败项返回 `error` + `hint`（如 "检查 API key / 服务是否启动"）。
- 前端设置页顶部状态面板展示；保存配置后自动重测。

## 6. 资料获取（已确认）：契约 + 工具 + 四层保底

**项目唯一承诺的契约**：

```
wiki/<游戏>/*.md（可选 frontmatter）+ assets/ 图片  →  sync 端点  →  可检索
```

- 资料的生成/获取/使用**责任在用户**；开源交付 `docs/local-wiki-methodology.md` 方法论。
- **`tools/fetch_wiki.py` 保留**（官方工具）：① 项目自测端到端；② 用户开箱可用（MediaWiki 站分类白名单）。**项目维护"工具能跑"，不维护"帮谁爬哪个游戏"**；许可合规（CC BY-SA 系）+ `source_url` 溯源 + 1–2 req/s 礼貌速率。
- **国产游戏 wiki 大多是 MediaWiki**（bwiki、灰机 wiki）——探测 `/api.php?action=query&meta=siteinfo&format=json` 有响应即可用同一脚本。

四层保底：① MediaWiki 站 → fetch_wiki.py ② 非 MediaWiki 网页 → 用户自转 md（Jina Reader / 自己的 AI）③ 零散资料 → webui 粘贴框 ④ 单 txt 丢目录也能 sync。

## 7. 实现清单 + 分工（已认可）

### 7.1 契约 schema（前后端联调接口面）

- `GET /v1/providers/health` → §5 的 JSON。
- `PUT /v1/settings/network` → `{ proxy:{enabled,url}, providers:{<name>:{use_proxy}} }`；热生效 + 保存即重测。

### 7.2 后端任务（本对话认领）

| # | 任务 |
| - | - |
| B1 | 统一 HTTP client factory（per-provider `use_proxy` 预留） |
| B2 | config schema：`network.proxy` + `providers.<name>.use_proxy`；持久化 + env 覆盖 |
| B3 | `GET /v1/providers/health`（真实 ping + hint，同配置路径） |
| B4 | `PUT /v1/settings/network`（热生效 + 重测） |
| B5 | `BgeM3Embedder`：硅基 OpenAI 兼容 client（召回）+ 本地 sentence-transformers/FlagEmbedding 路径（建库）；**统一 embed 函数**（预处理单点）；同文双嵌验证脚本 |
| B6 | 存储/索引：`memory_blocks` 加 `namespace`/`images`/`source_url`/`content_hash`；USearch 每游戏一文件；`remove+add` 单篇更新 |
| B7 | 读路径：`_enrich_with_memory` → 云嵌入 → KNN → `namespace=wiki:<当前游戏>` → content+images+source_url；fail-open：API 挂 → FTS5 BM25 → web search |
| B8 | `POST /v1/external/sync` + `tools/seed_wiki.py`（seed/drop/rebuild）+ `tools/fetch_wiki.py`（MediaWiki 分类白名单） |
| B9 | 金标评测集 20–50 条 recall@5（调阈值/验证/未来重构 baseline） |

### 7.3 前端任务（移交前端对话）

| # | 任务 |
| - | - |
| F1 | 设置页「网络代理」区块：总开关 + host + 端口 + "测试连接"（调 B3） |
| F2 | API 状态面板：状态灯 + 延迟 + 错误详情（数据源 B3） |
| F3 | 设置保存交互：`PUT /v1/settings/network` → 乐观更新 |
| F4 | 知识库页：namespace 分布 + 手动粘贴入口 + 按游戏删 + sync 触发 |

## 8. ADR-0012（v5 定稿）

```markdown
# ADR-0012: [Local Wiki] 语义向量化——USearch HNSW + bge-m3 双栖（本地建库/云召回）

## Status
Accepted（全部决策经用户逐项确认 2026-07-24；v4 Gemini 主路线经限额核实后推翻）

## Context
- [Local Wiki] = 用户预置游戏攻略/lore 库，直播注入 /v1/solve；v0.1/v0.2 漂移成对话记忆存储。
- 攻略图文混排、按游戏频繁增删；用户要 HNSW、省显存（运行时显存归主模型+游戏）、建库可用本地。
- 限额核实：gemini-embedding-2-preview 免费层仅 5 RPM/100 RPD（v4 假设 1500/day 有误），
  预览版无异步 Batch API，且 Google 有 2025-12 无预警削减配额前科 → 不配做默认路径。
- 关键发现：bge-m3 可"本地权重 + 硅基流动免费 API"双栖（同模型同空间）；中文检索 SOTA
  （MIRACL/MKQA，arXiv 2402.03216）；硅基 API ¥0、OpenAI 兼容、国内直连。
- 空间一致性铁律：建库模型=召回模型；落地以同文双嵌（>0.999）+ 统一 embed 函数保障。

## Decision
1. USearch 侧车 HNSW；每 namespace(=wiki:<游戏>) 一个 .usearch 文件；key=rowid；
   sqlite 唯一真相源，索引可重建；删游戏=删文件+一行 SQL。
2. 文本嵌入 = bge-m3（1024d）：建库本地 GPU（离线/免费/分钟级），召回硅基流动免费 API
   （国内直连 ~50-200ms）；统一 embed 函数；上线前同文双嵌验证。
3. 图片 = 文本引用（不向量化）：存 assets/，block 记 images[]+alt；命中后读图随块注入，
   主模型直接读原图。"贴图搜攻略"不做，留备选（gemini-embedding-2 图像腿）。
4. 网络 per-provider 代理预留（一期全直连；Gemini 若启用走 Clash 7890）；
   GET /v1/providers/health 真实 ping（同配置路径）；PUT /v1/settings/network 热生效。
5. 项目只承诺输入契约（wiki/<游戏>/*.md+assets → sync → 可检索）；tools/fetch_wiki.py
   保留（官方工具+自测）；获取责任在用户；四层保底。
6. fail-open：嵌入 API 挂 → FTS5 BM25 → web search；content_hash 增量去重。
7. 分工：后端 B1–B9；前端 F1–F4（移交前端对话）；契约=health/settings 两 JSON schema。

## Consequences
- ✅ 全链路 ¥0（本地建库+免费 API+图片零请求）；运行时显存 0 占用。
- ✅ 中文检索质量最强（bge-m3 中英专优化+sparse 兜底专名）；与项目 spec 原定模型一致。
- ✅ 免代理（一期全国内）；无 preview 模型变动/配额削减风险。
- ✅ 频繁增删结构性安全；未来 Rust 化零成本（USearch 跨语言+模型纯 HTTP）。
- ➖ 无"贴图搜攻略"（备选路径保留，启用时引入 gemini-embedding-2 第二空间）。
- ➖ 召回依赖硅基免费 API 可用性（fail-open 链 + Pro 付费加速版兜底 + 可切本地嵌入）。
- ➖ 本地建库需一次性下载 bge-m3 权重（~2.3GB FP16 / 600MB INT8）。
- ➖ 弃用 sqlite-vec vec0；spec 的"embedding 服务 :8997"改为"本地建库器+云召回 client"
  （spec 文档需备注偏离原因）。
```

## 9. 决策存档 + 备选路径

**已确认（2026-07-24）**：
1. USearch 侧车 + 每游戏一个索引文件 ✅
2. 文本腿 bge-m3 双栖：建库本地 / 召回硅基免费 API ✅
3. 建库本地跑、运行时显存归主模型+游戏 ✅
4. 图片文本引用（不向量化、随块注入、主模型读原图）✅
5. 代理 per-provider 预留 + health 检测 + 前后端分工（B/F 系）✅
6. 资料契约边界 + fetch_wiki.py 保留 + 四层保底 ✅

**备选路径（未启用，触发条件=「贴图搜攻略」成为硬需求）**：
- 引入 gemini-embedding-2-preview 作为**图像专用嵌入**（第二空间）：只嵌图片（量小），与 bge-m3 文本空间组成双空间双索引；查询时文字走 bge-m3、图片走 gemini，规则融合。预估成本：免费层排队数天或 ~¥7/游戏付费。启用时重开 ADR-0012 增补。

## 10. 调研来源（2026-07-24）

- **bge-m3**：arXiv 2402.03216（MIRACL 18 语/MKQA SOTA，dense+sparse+multi-vec，8192 token，L2 归一化）；硅基流动模型页/第三方核实（`BAAI/bge-m3` ¥0、OpenAI 兼容、8192 token、国内直连）。
- **gemini-embedding-2**：Google 官方博客+ai.google.dev embeddings 文档（规格/batchEmbedContents）；**限额修正**：官方速率表镜像（page.ke、gemini-api.apifox.cn：Embedding Experimental 5 RPM/100 RPD，Tier1 10 RPM/1000 RPD）；aifreeapi 指南（预览版无 Batch API；2025-12 配额削减事件；embeddingcost.com 的"~1500/day"系旧模型概括，v4 误用）。
- **直接嵌入 vs caption**：arXiv 2511.16654（mAP@5 +32%）；Lenovo LP2371（VLM TTFT×分辨率）。
- **HNSW**：USearch 2.25.3；sqlite-vec issue #25 + PR #276/#277（官方不做 HNSW）。
- **wiki 爬取**：pywikifetch、wiki.gg Cargo、mediawiki-scraper；CC BY-SA 系许可。
- **搜索通道**：Tavily（key 生效实测）+ Exa（.mcp.json key 实测）+ WebSearch。
