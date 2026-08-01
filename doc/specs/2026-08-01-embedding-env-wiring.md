# Spec: EMBEDDING_LOCAL_MODEL 接线修复（T-06）

> **状态**：待实施（等用户确认后交后端对话）
> **关联**：FA-4（E4 根因）、D-038（决策条目）
> **日期**：2026-08-01
> **工作流**：审查组 spec → 后端对话实施 → QA 回归

---

## 1. 问题

Local Wiki 语义召回（E4）不健康。根因 = `EMBEDDING_LOCAL_MODEL` 环境变量未在启动脚本中持久化（配置漂移）。

### 症状链路

```
EMBEDDING_LOCAL_MODEL 未设
  → embedder.py:102/238 默认模型名 = "BAAI/bge-m3"（HF hub id）
  → SentenceTransformer("BAAI/bge-m3") 尝试加载 HF 缓存
  → HF 缓存 `.cache/huggingface/hub/models--BAAI--bge-m3/` 存在但不完整
     （总 40K；blobs=3 个 0 字节 .incomplete，Jul 29/31 三次下载失败）
  → EmbedderError（embedder.py:220）
  → wiki_service.sync_wiki_dir 静默存文本块 vector=None（:91-93）
  → 语义召回（ANN 无向量）返回空
  → E4 "召回不健康"
```

### 掩盖因素

- `available()`（embedder.py:127-133）对 local 模式**无条件返回 True**，不校验模型可加载
- `memory_store_client.py` 全 fail-soft + circuit breaker（3 次失败开路 30s），错误仅 warning 返回 []

### 已排除的假阳性

| 假阳性 | 真相 |
|---|---|
| webinfer 连废弃 :8996 | 启动链路证明 run-windows.ps1 继承 MEMORY_STORE_URL=8997 |
| D-033 nvidia 默认 | #42 于 07-28 revert 回 local，embedder.py:89 默认=local |
| E2/E3 token 泄露 | prompt_assembly/prompt_building/memory_io 全链路深扒无泄漏 |

---

## 2. 修复

### 2.1 必修：run-windows.env 加一行

**文件**：`services/scripts/run-windows.env`
**位置**：L136-142 端口配置块附近（MEMORY_PORT / MEMORY_STORE_URL 之后）

```env
# Embedding model local path (ADR-0012 §6, D-038)
# Points to the local bge-m3 checkpoint so memory-store doesn't need HF download.
EMBEDDING_LOCAL_MODEL=D:/AI/models/bge-m3
```

**传递链路验证**：
1. `run-windows.ps1`:74-86 载入 `run-windows.env` 到会话 env ✅
2. `Start-Background`:297-304 写当前进程 env ✅
3. `Start-Process`:318 继承父进程 env ✅
4. `embedder.py:102` 读 `os.getenv("EMBEDDING_LOCAL_MODEL", _DEFAULT_MODEL)` ✅

### 2.2 可选加固：available() 真校验

**文件**：`services/memory-store/src/memory_store/embedder.py`
**方法**：`available()` (L127-133)

**当前代码**：
```python
def available(self) -> bool:
    if self.provider == "none":
        return False
    if self.provider == "local":
        return True  # ← 无条件！
    return bool(self.api_key)
```

**建议改为**：
```python
def available(self) -> bool:
    if self.provider == "none":
        return False
    if self.provider == "local":
        # 校验模型路径存在且可加载（避免再次掩盖配置漂移）
        model_path = os.getenv("EMBEDDING_LOCAL_MODEL", "")
        if model_path and os.path.isdir(model_path):
            return True
        _LOGGER.warning(
            "local provider selected but EMBEDDING_LOCAL_MODEL='%s' "
            "is not a valid directory; embedding will likely fail",
            model_path or "(unset)",
        )
        return True  # 仍返回 True（向后兼容），但已 warn
    return bool(self.api_key)
```

**注意**：此加固为可选——不改也不影响 T-06 主修复。但如果未来再出现类似漂移，有 warn 至少能在日志里看到。

---

## 3. 不改什么

- **不改 embedder.py 默认值** `_DEFAULT_MODEL = "BAAI/bge-m3"`（保留作为最终 fallback）
- **不改 memory_store_client.py 的 DEFAULT_BASE_URL=8996**（属 T-03 防御性加固范围）
- **不改 HF 缓存残骸**（`.cache/huggingface/hub/models--BAAI--bge-m3/` 可后续清理，不阻塞修复）

---

## 4. 验证

### 4.1 静态验证

```bash
grep "EMBEDDING_LOCAL_MODEL" services/scripts/run-windows.env
# 预期命中新加的一行
```

### 4.2 服务验证（需真机起服务）

```bash
# 1. 启动 memory-store (:8997)
# 通过 start-joyai.ps1 或 run-windows.ps1

# 2. 检查 health 端点
curl -fsS http://127.0.0.1:8997/v1/providers/health | python -m json.tool
# 预见: embedding.ok=true, provider=local, model=D:/AI/models/bge-m3

# 3. 触发 wiki sync（通过 webui 或 API）
# POST /v1/external/sync with namespace=wiki:<game>

# 4. 再次检查 health
curl -fsS http://127.0.0.1:8997/v1/providers/health | python -m json.tool
# 预期: embedded > 0（sync 成功生成了向量）

# 5. 测试召回
# POST /v1/blocks/recall with query="火焰巨人"
# 预期: 返回非空 blocks 列表，cos > 0.5
```

---

## 5. 实施说明

- **实施者**：后端对话（非审查组）
- **分支**：`feat/health-audit-memory-webinfer` 或新建 `fix/embedding-env-wiring`
- **worktree**：`JoyAI-VL-Interaction-wt-health-audit`（已有）或新建
- **影响范围**：1 行 env 文件（必修）+ ~10 行 embedder.py（可选加固）
- **回归风险**：极低（仅新增 env 变量，不影响现有逻辑路径）
- **回滚方案**：删除 run-windows.env 新加行即可

---

*Spec v1 · 2026-08-01 审查组产出 · 基于 FA-4 三源交叉验证（git + 磁盘 + HF 缓存）*
