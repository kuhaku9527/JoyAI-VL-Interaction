# Local Wiki 封闭测试回路（钉死）

所有「测试 local wiki 召回」必须走本回路；**禁止**在 `.workbuddy/tmp` 或任何临时目录现造 wiki 语料。任何人（包括未来的 agent）测试 local wiki 召回时，都走这条钉死的回路，而不是重新造临时语料、重新读代码。

本回路的测试数据、评估逻辑与真机验证命令均已钉死并经主理人验证（`recall@5 = 24 / 24 = 1.000`，退出码 0）。

## 钉死的测试数据（SSOT）

- **语料**：`services/memory-store/tools/sample_wiki/elden-ring/`
  （13 个固定 markdown，含 `bosses` / `areas` / `items` / `mechanics` 子目录）。这是测试语料本体（SSOT）。
- **golden 集**：`services/memory-store/tools/golden_recall_set.json`
  （24 条 golden query + `expects` 关键词）。

改上面两条数据才算「改测试基线」，需要评审；平时**只读**，不要新建/修改它们。

## 离线封闭回路（首选，零网络）

```bat
cd D:/AI/workspace/JoyAI-VL-Interaction-main
set PYTHONPATH=services/memory-store/src
set EMBEDDING_LOCAL_MODEL=D:/AI/models/bge-m3
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
D:/AI/envs/joyai-main/python.exe services/memory-store/tools/eval_golden_recall.py --mode local
```

- 预期：`recall@5 = 24 / 24 = 1.000`（退出码 0）。
- `--mode vector` 走硅基 API（需 `SILICONFLOW_API_KEY`），仅作对比，不要求离线。

## pytest 入口（2026-08-05 新增 `tests/test_golden_recall.py`）

```bat
D:/AI/envs/joyai-main/python.exe -m pytest services/memory-store/tests/test_golden_recall.py -q
```

- 复用 `tools/eval_golden_recall.py` 的逻辑与默认路径（钉死 `sample_wiki/elden-ring` + `golden_recall_set.json`）跑 in-process golden recall@5。
- **无本地 bge-m3 权重时自动 skip**（CI 绿）；有 `EMBEDDING_LOCAL_MODEL` 时实跑并断言 `recall@5 == 1.000`。
- 另两个常跑的：
  - `tests/test_local_real_recall.py`：真机 local bge-m3 召回测试，无权重时 skip。
  - `tests/test_wiki_sync_and_recall.py`：fake embedder 的 sync/recall 单测，恒跑（不依赖权重）。

## 在线冒烟变体（sync 钉死语料进运行中的 memory-store，再跑 golden）

这条用**钉死语料**（`sample_wiki/elden-ring`）而非临时目录。

1. 起服务（端口 8997，`MEMORY_PORT=8997`、`EMBEDDING_LOCAL_MODEL=D:/AI/models/bge-m3`）：

   ```bat
   pwsh -File services/scripts/run-windows.ps1 -Restart memory-store
   ```

   （或用项目既定方式启动 memory-store。）

2. sync 钉死语料进命名空间 `wiki:elden-ring`。用写文件再 `--data @file` 的方式，避免 shell 对 Windows 路径做 mangling；`dir` 用 **Windows 风格**路径：

   `sync_req.json`：

   ```json
   {"namespace":"wiki:elden-ring","dir":"D:/AI/workspace/JoyAI-VL-Interaction-main/services/memory-store/tools/sample_wiki/elden-ring","drop_first":true}
   ```

   ```bat
   curl -X POST http://127.0.0.1:8997/v1/external/sync --data @sync_req.json -H "Content-Type: application/json"
   ```

3. 跑 golden（取 `golden_recall_set.json` 的 query，带 `filter.namespaces:["wiki:elden-ring"]`）：

   ```bat
   curl -X POST http://127.0.0.1:8997/v1/blocks/recall --data "{\"query\":\"<golden query>\",\"top_k\":5,\"min_score\":0.0,\"min_similarity\":0.0,\"filter\":{\"namespaces\":[\"wiki:elden-ring\"]}}" -H "Content-Type: application/json"
   ```

- 预期：每个 golden query 的 top-5 中**包含**其 `expects` 关键词（中文 key 用 `golden_recall_set.json` 的 `expects` 匹配 content）。
- 裸 recall（无 namespace）→ HTTP 400（向量-only 强制，D-2026-08-05-003）。

## 前置环境

- `EMBEDDING_LOCAL_MODEL=D:/AI/models/bge-m3`：本地 bge-m3 权重（约 2GB）。
- `PYTHONPATH=services/memory-store/src`。
- 离线标志：`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`。
- CI 无权重时，golden / local 测试自动 skip（保持绿）。
