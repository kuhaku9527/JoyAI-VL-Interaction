# Local Wiki 方法论（爬取 / 使用 / 维护规范）

> 配套文档：`services/memory-store/tools/fetch_wiki.py`、`seed_wiki.py`、
> `eval_golden_recall.py`，以及 `tools/README.md`（封闭测试回路 runbook）。
>
> 本文档是 **Local Wiki** 功能的爬取 / 使用 / 维护方法论（SSOT 级别的方法论），
> 不是代码、也不是执行脚本。

---

## 1. 定位与目的

本文档规定 Local Wiki 语料的**爬取流程**、**落盘格式（contract layout）**、
**测试基线（SSOT）的维护规则**，以及**如何扩语料 / 换游戏 / 重建测试基线**。

目标读者：

- 需要**扩语料**（增加页面 / 分类）的开发者或 agent；
- 需要**换游戏**（从 Elden Ring 换到另一款游戏的 wiki）的开发者；
- 需要**重建测试基线**（重跑 golden recall、更新 `golden_recall_set.json`）
  的开发者或 agent。

读完本文档后，读者应能做到：在不破坏钉死测试基线的前提下，安全地把新语料
接入 `memory-store` 的 `wiki:<game>` 命名空间。

---

## 2. 钉死测试语料的 provenance（溯源）

`services/memory-store/tools/sample_wiki/elden-ring/` 是 13 个 markdown 文件组成的
**测试语料 SSOT**（含 `bosses` / `areas` / `items` / `mechanics` 子目录）。

### 来源

- **游戏**：艾尔登法环（Elden Ring）攻略 wiki。
- **原始数据**：来自 Fandom 的 MediaWiki API：
  `https://eldenring.fandom.com/api.php`
- **生成方式**：通过 `fetch_wiki.py` 从 MediaWiki API 拉取指定 categories 的页面，
  转换为仓库约定的 markdown contract layout（`# 标题` + 正文段落 + `## 子标题`）。

### 已知 gap（本次文档要弥补）

- **确切的 fetch 命令参数在 git 历史中未记录**：当前落地样本是怎么爬下来的，
  没有可复现的命令证据。本次创建本文档后，后续任何重新爬取**必须**把完整命令
  记录到本文档的「变更日志」节（§7），以闭合 provenance。
- **当前落地样本缺 frontmatter / provenance**：13 个 `.md` 文件头部**没有**
  `source_url` / `license` / `fetched_at` frontmatter（`fetch_wiki.py` 自称会写，
  但落地样本未写）。这违反了 §3 的 contract，标记为**待补**。后续爬取必须补
  frontmatter（见 §3 与 §7 首条记录）。

### license

- Fandom 内容通常遵循 **CC BY-SA 3.0**。
- 实际样本当前缺 frontmatter，license 未落盘 → 后续爬取必须补（见 §3）。
- 不同 wiki 的 license 不同（如 Wikipedia 为 CC BY-SA 4.0），爬取前请核对目标
  wiki 的条款，并在 frontmatter 中如实记录。

---

## 3. 语料 contract layout（fetch_wiki.py 输出格式规范）

每个 `.md` 文件必须是标准 markdown，结构如下：

1. **第一行**：`# 页面标题`
2. **正文段落**：自然语言，不含 HTML。
3. **可含** `## 子标题` 分段（副主题）。
4. **必须**在文件头部插入 YAML frontmatter（放在 `# 标题` 之前或之后第一行均可）：

```yaml
---
source_url: "https://eldenring.fandom.com/wiki/PageName"
license: CC-BY-SA-3.0
fetched_at: YYYY-MM-DD
---
```

- `source_url`：页面在源 wiki 的规范 URL（用于 CC BY-SA 署名与溯源）。
- `license`：实际采用的 license 标识（以目标 wiki 条款为准）。
- `fetched_at`：爬取日期（ISO `YYYY-MM-DD`）。

### 图片引用

- 图片引用保留为 `![alt](assets/xxx.png)` 格式；`wiki_service` 已支持从语料中
  提取该格式并关联到 block 的 `images` 字段。
- `fetch_wiki.py --with-images` 会把图片下载进 `assets/`，并自动生成上述引用。

### 禁止项

- **禁止**在语料里嵌入 HTML 标签、JavaScript、广告或任何非内容噪声。
- **禁止**手改正文后不更新 `content_hash` / 不重跑 sync（见 §4）。

> 注：现有 `fetch_wiki.py` 写入的 frontmatter 字段为 `title` / `source_url` /
> `license: "CC BY-SA (see source wiki terms)"`。若后续统一到本文档的 `license`
> 枚举（如 `CC-BY-SA-3.0`）+ `fetched_at`，属于「改 methodology」，需在 §7 记录。

---

## 4. SSOT 规则（最重要）

`services/memory-store/tools/sample_wiki/` 下的语料是**测试基线 SSOT**——
`golden_recall_set.json` 的 24 条 golden query 的 `expects` 断言依赖它。

### 改 SSOT = 改回归基线

任何对语料的**增 / 删 / 改**文件操作，都视为「改测试基线」，必须走完以下流程：

1. 重跑 `eval_golden_recall.py --mode local` 确认 `recall@5` 仍合理
   （不要求严格 `1.000`，但不能崩、不能大面积掉到 0）。
2. 更新 `golden_recall_set.json` 的 `expects` 关键词，使其匹配新语料。
3. 在本文档「变更日志」节（§7）记录**改动原因 + 日期**。

### 禁止随意覆盖 SSOT

- **禁止**随意重新爬取覆盖 SSOT。
- 只有在**有意换游戏**或**有意扩语料**，且走完上述三步流程时，才允许重建 SSOT。
- 平时对 SSOT 语料**只读**。

### hit 语义与 score 字段的解耦

- golden recall 的命中规则是**基于 content 关键词匹配**（`expects` 关键词是否出现在
  top-5 的 `content` 中），**不受 `score` 字段影响**。
- `score` 字段（从 `sqlite_backend` 返回）是向量检索的 **cosine 相似度**（bge-m3
  输出 L2-normalized 向量，cosine = 点积，范围 [-1, 1]，语义相近通常 > 0.3）。改
  `score` 计算方式（例如从恒 `1.0` 改为真实相似度）不会改变命中率，只会让 metrics
  更真实。

---

## 5. 爬取流程（如何扩语料 / 换游戏）

```bash
# 1. 检测目标 API 是否可用
python tools/fetch_wiki.py --api https://<game>.fandom.com/api.php --check

# 2. 拉取指定分类
python tools/fetch_wiki.py \
    --api https://<game>.fandom.com/api.php \
    --categories "Bosses,Weapons,Areas" \
    --out tools/sample_wiki/<game-slug> \
    --with-images \
    --max-pages 500

# 3. (可选) seed 进运行中的服务验证
python tools/seed_wiki.py tools/sample_wiki/<game-slug> --namespace wiki:<game-slug> --drop-first
```

### 速率限制

- 默认 **1 req/s**（`fetch_wiki.py` 内置 polite delay），**不要改快**。
- 对第三方 wiki 保持礼貌，避免被限流或封禁。

### category 名称

- `--categories` 决定拉哪些页面；**先用 `--check` 确认目标 wiki 的 category 名称**
  （不同 wiki 的 category 命名差异很大，例如 Fandom 上 Elden Ring 用 `Bosses`、
  `Weapons`、`Areas` 等）。
- 拉取前建议先在浏览器里确认目标 wiki 确实使用这些 category 名称。

### 落盘后

- 确认每个 `.md` 都带了 §3 规定的 frontmatter（source_url / license / fetched_at）。
- 如用于更新 SSOT，按 §4 流程重跑 golden 并登记变更日志。

---

## 6. 测试回路入口（指针，不重复写细节）

完整的**封闭测试回路**（钉死语料 + golden 集 + 离线 / 真机命令）见
`tools/README.md`（runbook）。本文档只列入口指针：

- **离线封闭回路**：`tools/eval_golden_recall.py --mode local`
  （默认钉死 `sample_wiki/elden-ring` + `golden_recall_set.json`，零网络）。
- **pytest 入口**（均在 `services/memory-store/tests/`）：
  - `test_golden_recall.py`：in-process golden recall@5（无本地 bge-m3 权重时自动 skip）。
  - `test_local_real_recall.py`：真机 local bge-m3 召回（无权重时 skip）。
  - `test_wiki_sync_and_recall.py`：fake embedder 的 sync/recall 单测，恒跑（不依赖权重）。

> 任何「测试 local wiki 召回」都必须走上述钉死回路，**禁止**在临时目录现造语料。

---

## 7. 变更日志

### 2026-08-05 | AI | 创建本文档；标记 sample_wiki/elden-ring 缺 frontmatter / provenance

- 新建 `docs/local-wiki-methodology.md`，闭合 `fetch_wiki.py` docstring 中长期悬空的
  `docs/local-wiki-methodology.md` 引用。
- 确认 `tools/sample_wiki/elden-ring/` 的 13 个 `.md` **缺** `source_url` /
  `license` / `fetched_at` frontmatter；确切 fetch 命令在 git 历史中未记录。
- 标记上述 gap 为**待补**：后续重新爬取（换游戏 / 扩语料）时必须补 frontmatter，
  并把完整 fetch 命令登记到本节。
- recall@5 before: 1.000（基线未变，仅文档与 provenance 登记） | after: 1.000
