# Local Wiki 聊天接入方案对比（方案 A 变体）

**上下文**：webinfer 聊天路径的 `_memory_recall(state, question)` 当前只读 session 级 warmup 缓存（filter={session_ids:[sid]}`），从不调 `recall(query)`。Local Wiki 库已建好可查但**未接入聊天 prompt**。已确认问题属实（`reports/local-wiki-chat-integration-handoff-20260728.md`）。

**目标**：让 `_memory_recall` 收到玩家问"玛莲妮亚怎么打"时，把 wiki 召回的攻略块也注入到 prompt。

## 现状代码地图

- `services/webinfer/memory_io.py::_memory_recall` 唯一注入点
- `services/webinfer/memory_store_client.py::recall` 已有 `query` 参数与 `filter.namespaces` 兼容（PR #36 改）
- `services/webinfer/prompt_assembly.py::_build_memory_prompt` 读 `_memory_block_cache`
- `services/webinfer/system_prompts.py::_clip_memory_blocks` 渲染块（不区分来源）

## 三个变体对比

### 变体 1：**混合注入**（注入同一字段）

```python
# memory_io.py::_memory_recall
async def _memory_recall(self, state, question):
    session_blocks = await self._ensure_warmup(state)
    if question and WIKI_RECALL_ON:
        wiki_blocks = await self.memory_store.recall(
            query=question, top_k=5, min_score=0.0,
            filter={"namespaces": WIKI_RECALL_NAMESPACES},  # 默认 ["wiki:*"]
        )
        session_blocks = session_blocks + wiki_blocks
    return session_blocks
```

| 维度 | 评估 |
| - | - |
| 改动 | **~5 行**（仅 memory_io.py） |
| 缓存 | 同 session 一份，per-question recall 命中 webinfer 缓存 |
| 渲染 | wiki 块与 chat 块混在 [Previous Memory] 段，**来源不可区分** |
| 调试 | 玩家看到的"记忆"是混合的，溯源困难 |
| 风险 | 极低（仅多一次 HTTP） |
| 限制 | 4000 字符 limit 同时吃两类内容，wiki 块可能挤掉 chat 块 |

### 变体 2：**分组注入**（同 cache、带 source 字段）

```python
# memory_store_client.py-recall 多带 source:
{"content": "...", "source": "wiki", "namespace": "wiki:elden-ring"}

# prompt_assembly.py 分组渲染
def _clip_memory_blocks(blocks):
    chat = [b for b in blocks if b.get("source") != "wiki"]
    wiki = [b for b in blocks if b.get("source") == "wiki"]
    # 各自渲染两段
```

| 维度 | 评估 |
| - | - |
| 改动 | **~20 行**（client + system_prompts + memory_io） |
| 渲染 | [Previous Memory] + [Local Wiki] 两段，**来源清晰** |
| 字符 limit | 可各自设 limit（4000/4000 共 8000），更宽 |
| 调试 | 玩家看到"记忆"和"wiki 检索"两个独立分段，溯源直观 |
| 风险 | 中（动到 system_prompts，需要回归 prompt 渲染测试） |
| 维护 | 严格遵循设计文档 v5 §Local Wiki 集成，意图和实现一致 |

### 变体 3：**独立 path**（另起一个 `_memory_wiki_recall`，renderer 改 2 段）

```python
# memory_io.py 落两个 cache
state._memory_block_cache = chat_blocks
state._memory_wiki_cache = wiki_blocks

# prompt_assembly.py 读两 cache，渲染两段
```

| 维度 | 评估 |
| - | - |
| 改动 | **~40 行**（adapter_types + memory_io + prompt_assembly + system_prompts）+ 测试 |
| 渲染 | 完全独立，互不挤占 |
| 字符 limit | 各自 4000 |
| 风险 | 高（改 adapter_types 字段，多处读者；webinfer 单元测试涉及混合 fixture） |
| 维护 | 复杂，SessionState 字段膨胀 |

## 我的判断：**变体 2**（分组注入）最契合

理由：

1. **变体 1 太简陋**：wiki 块和 chat 块混在同段渲染，玩家看到的内容没法区分是"AI 记住的"还是"AI 检索的"——这正是当前缺口的**目的**（让玩家得到上下文增强）。如果渲染后看不出来源，等于没做。
2. **变体 3 过度工程**：webinfer 单元测试成熟（`test_live_adapter_memory_hooks.py`），动 adapter_types 字段意味着大批 fixture 要重写。**对于"把现有 recall 调用加一个 namespace filter"的任务来说，是杀鸡用牛刀**。
3. **变体 2 恰到好处**：
   - 改动集中在 3 个文件，每个改动 ~5-10 行
   - 渲染逻辑沿用现有 `_clip_memory_blocks`，只多一个分组
   - 镜像设计文档 v5 §Local Wiki 集成（"独立 [Local Wiki] 段"）
   - 字符 limit 各自独立，不会挤压
   - 测试用例少：加 1 个分组行为测试 + 1 个 fail-open 测试即可

### 变体 2 的精确参数

```ini
WIKI_RECALL_NAMESPACES = ["wiki:*"]   # 默认；通配展开在 backend
WIKI_RECALL_TOP_K = 5
WIKI_RECALL_MIN_SIMILARITY = 0.35     # 走 backend 内置阈值
```

触发条件：仅当 `question` 非空 且 `memory_store.enabled` 为真 且 wiki 库至少存在一个 namespace。

**fail-open**：recall 失败仅 `LOGGER.warning`，不阻塞聊天。webinfer 不会因 wiki 召回挂掉。

**去重**：session 内 `_memory_block_cache` 加 wiki 块前按 `block_id` 去重，避免重复命中。

### 验证计划

1. **单元测试**（webinfer/tests/test_local_wiki_recall.py）：
   - `test_wiki_recall_merges_into_cache_with_source_label`
   - `test_wiki_recall_failure_does_not_break_chat_recall`（fail-open）
   - `test_wiki_recall_skipped_when_disabled`
   - 装 mock `memory_store_client.MemoryStoreClient` 替换
2. **冒烟**（真实 memory-store :8997 + 真实 recall API）：
   - `python -m pytest services/webinfer/tests/test_local_wiki_recall.py -v`
   - 跑四次场景：wiki 库空 / 部分命中 / 全失败 / namespace 不匹配
3. **不开 CI 的真实 wiki 库**：建 `wiki:astrobotany` 几个块，问"攻略"看 prompt 注入

## 风险与回退

- 改动 webinfer 3 文件；webinfer 已有 11 个测试，需要所有不改的测试 + 新增测试都过
- 任何改动都要走 ruff check + format --check（CI 门禁）
- 回退：分支 PR #42 不合并，main 仍是 `52fcbb8`（已合 #41）
