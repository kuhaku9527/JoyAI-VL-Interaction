# 旧活儿接手 TODO（分支大扫除后）

> 背景：2026-08-02~03 分支大扫除删了 18 条旧分支（本地+远端），其中 7 条有真货的打了
> `archive/<名>` 标签兜底（**本地标签、不推送、不占工作分支数**）。
> 本文件逐条判断是否值得接手，按「一个一个来、少开分支、做完即删」的纪律执行。
> 接手纪律以 `决策/AI代码质量约法三章.md` 为准。

## 接手前置流程（每条都走）

1. **复活**：`git branch <原名> archive/<原名>` → 从原 commit 变成工作分支。
2. **范围核验（spec/adr 框定）**：核对该分支对应的 spec/adr 是否仍在 `doc/specs/` / `doc/adr/` 且能框住本次改动范围。
   - 框得住 → 继续第 3 步。
   - 框不住 / 缺失 / 已 stale → **先补 spec**（走 spec→adr→落地 流程），再开工。**禁止无 spec 框定就直接写代码**——这正是「AI 从零做漂亮 demo 但不对接创作者需求」的根因。
3. **精确核验**：对比标签版改动文件 vs `origin/main` 同名文件，确认 main 是否已有等价实现（标签独有 ≠ main 没有等价，可能已被别的 PR 取代）。
4. **开工**：只建这一条工作分支，遵守约法三章（禁静默/禁 fallback/必 log/增新删旧）。
5. **收尾**：合 PR → 删远端+本地分支 → 此时 `archive/<名>` 标签可保留兜底或 `git tag -d` 清掉。

## 逐条清单（依据 `git diff --stat origin/main...archive/<tag>` 实测）

### ① `feat-q2-emit` —— ★ 最高优先，建议第一个接手
- **内容**：把 ADR-0014 JSONL 事件流接线进 cold services（webinfer / memory-store / webui）
- **相对 main 独有**：15 提交，31 文件，+1782/−772；核心改动 `memory_io.py` / `memory_store_client.py` / `webui/server.py` + `index.html` + `决策/` 文档
- **判断**：**真·未完**。main 里 JSONL 仅 `background-agent/codex_api/main.py` 一处；webinfer/memory-store/webui 侧接线缺失 = 用户说的「模块 log 没做完」本体，也是约法三章生效的前提。
- **spec/adr 痕迹**：ADR-0014 + `doc/specs/log-event-schema` ✅ 齐全，框得住。
- **复活**：`git branch feat-q2-emit archive/feat-q2-emit`
- **开工核验**：比对标签版 memory_io.py / memory_store_client.py 与 main 同名文件，找出缺的 logger 调用
- **收尾（2026-08-03 ✅）**：实际从 `integrate/q2-emit-logging` 走 **PR #68**（squash → main `5eeec8a`）合入，reviewer 约法三章门禁 **PASS**（5 条全过、6 历史 BLOCKING 清）。`package-smoke` 修复 = 7 个 caller 由 fail-loud `raise` 改 logged no-op。旧的 `feat-q2-emit` 本地分支已 stale（内容已由 PR #68 交付，`archive/feat-q2-emit` 标签仍兜底），留待分支大扫除。`log_with_timestamp.py` 在 checkout 时被误删出工作树，已从 HEAD 还原（无回归）。

### ② `feat-drift-gate-runtime-v2.1` —— 大概率跳过，待精确核验
- **内容**：drift-gate v2.1 运行时门禁 + D-038 决策 + T-06 spec
- **相对 main 独有**：15 提交，23 文件；但 main 的 `quality.yml` 已有 `drift-gate-runtime` 段、`doc/adr/0015` 也存在
- **判断**：主体已落地；15 个提交可能是 D-086 微调或后续。复活后精确比对，大概率无活儿可接。
- **spec/adr 痕迹**：spec `drift-gate-harness-spec` + main 已含 ADR-0015 ✅ 齐全。
- **复活**：`git branch feat-drift-gate-runtime-v2.1 archive/feat-drift-gate-runtime-v2.1`
- **精确核验（2026-08-03）**：功能性门禁**已在 main**（`quality.yml` 的 `drift-gate-runtime` job + 新 `scripts/verify.sh` drift 校验 + `ADR-0015`）。标签独有、main 仍缺的**安全高价值**部分：(1) `.gitattributes`（强制 LF，修反复踩的 CRLF CI 坑）；(2) `doc/specs/drift-gate-runtime-v2.1-spec.md` + `doc/adr/ADR-0012-v6-proposal.md`（框定特征，仓库 spec 驱动）。❌ **不删** `scripts/drift_gate.py`/`drift_gate_smoke_test.py`/`config/drift-contract.json`：grep 全仓确认仍被 `vlm_runtime_probe.py`/`log_maintenance.ps1`/`run-windows.ps1`/`doc/specs/drift-gate-harness-spec.md` 引用，删=回归（约法三章 3.4 零引用才删）。**处置：接手 (1)+(2) 纯新增，跳过删除与 决策/报告等已演进内容。**
- **收尾（2026-08-03 ✅）**：实际走 **PR #70**（squash → main 0e0a5fe）合入，reviewer 约法三章门禁 **PASS**。原计划的第 3 文件 `doc/specs/drift-gate-runtime-v2.1-spec.md` 经双重核验在源标签 `archive/feat-drift-gate-runtime-v2.1` 不存在（标签内仅 `drift-gate-harness-spec.md` 等），按方案 A 仅合入实际可用的 2 文件收口。reviewer nits（ADR 内称"现有"的 `tools/golden_recall_set.json`/`tools/verify_nvidia_recall.py` 实由 PR #38 引入、`drift_gate_smoke_test.py` 主杆缺失）为非阻塞 follow-up。

### ③ `fix-backend-p3-swallow-logging` —— 建议接手（直接对应用户痛点）
- **内容**：记录 `webinfer/session.py` 与 `memory-store/sqlite_backend.py` 里被静默吞掉的异常
- **相对 main 独有**：1 提交，2 文件，+9/−3
- **判断**：小修复、正面（符合约法三章「要有 log」），价值高、风险低。
- **spec/adr 痕迹**：与日志 schema(ADR-0014) 沾边 ✅ 部分（非专门 spec，属小修复，按治理可不强制 spec）。
- **复活**：`git branch fix/backend-p3-swallow-logging archive/fix-backend-p3-swallow-logging`
- **精确核验（2026-08-03 ✅）**：**无需接手**。标签改动已随 **PR #27 (`8c34f46`)** 落地 main——`session.py:158-162`（`CancelledError` 拆分支 + `LOGGER.warning("cleanup task raised during shutdown...")`）与 `sqlite_backend.py:510-511`（`_LOGGER.warning("sqlite connection close failed...")`）逐字一致，且 sqlite 还多了 vector store close 日志。pickaxe 确认交付 commit 为 `8c34f46`。`LOGGER` 在 main 的 `session.py:28` 已定义（`logging.getLogger("streaming_infer_adapter")`），无 NameError 风险。

### ④ `fix-backend-p1-asr-kwstraining-s101` —— 接手
- **内容**：把 asr/kws/hermes 里的生产 `assert` 换成显式 `raise` + 测试（`test_hermes_api_enrich_guard.py`）
- **相对 main 独有**：3 提交，6 文件，+126
- **判断**：方向正确（把静默 assert 变显式 raise，正是约法三章鼓励的）。复活后核验 main 是否已有等价。
- **spec/adr 痕迹**：对应 ADR-0008（p0-adapter-fixes）✅。
- **复活**：`git branch fix/backend-p1-asr-kwstraining-s101 archive/fix-backend-p1-asr-kwstraining-s101`
- **精确核验（2026-08-03 ✅）**：**无需接手**。全部 6 文件改动已随 **PR #25 (`6037348`)** + `38444e6` 落地 main：asr.py/kws.py 的 `raise ValueError`、hermes_api/main.py 的 logged `except`、summarizer_routing.py 的 `raise RuntimeError`、export_kws_onnx.py 的 `raise ValueError`、kws_data_module.py 的 `@cached_property`，以及新增回归测试 `test_hermes_api_enrich_guard.py`（main blob `d8677fe` 与标签完全一致）。pickaxe 确认交付 commit `6037348`/`38444e6`。

### ⑤ `fix-backend-p1-kws-datamodule-b019` —— 接手
- **内容**：`lru_cache` 误用在实例方法的修复
- **相对 main 独有**：2 提交，3 文件，+13/−7
- **判断**：小修复，低风险。
- **spec/adr 痕迹**：对应 ADR-0008（p0-adapter-fixes）✅。
- **复活**：`git branch fix/backend-p1-kws-datamodule-b019 archive/fix-backend-p1-kws-datamodule-b019`
- **精确核验（2026-08-03 ✅）**：**无需接手**。3 文件改动已随早期 PR（#25 等）落地 main：`hermes_api/main.py` 的 logged except、`kws_data_module.py` 的 `@cached_property`（:80/89/94）、`summarizer_routing.py` 的 `raise RuntimeError`（:105/154）均已在 main。与 ④ 大量重叠，属同一批 assert→raise 改造。

### ⑥ `fix-webinfer-context-overflow-bound` —— 接手
- **内容**：webinfer 上下文溢出边界测试 + 实现边界
- **相对 main 独有**：2 提交，5 文件，+229；含 `test_context_overflow_bounds.py`
- **判断**：测试类，低风险，接手。
- **spec/adr 痕迹**：ADR-0013 + spec `memory-client-resilience` ✅ 齐全。
- **复活**：`git branch fix/webinfer-context-overflow-bound archive/fix-webinfer-context-overflow-bound`
- **精确核验（2026-08-03 ✅）**：**无需接手**。5 文件改动已全部在 main：`memory_io.py:411-412`（`qa_history_window` 边界）、`summarizer_routing.py:194-215`（`long_term_memory_max_tokens` token budget 循环 + `_rebuild_long_term_memory`）、`adapter_types.py:140,165`（两 config 字段）、`test_context_overflow_bounds.py`（blob `5f44f35` 与标签逐字一致）。三点 diff 虽非空（标签分支自 merge-base 前偏离），grep main 工作树确认代码已通过别的路径落地。另：3 条他人远端 webinfer 分支（nit-cleanup / reentrant-lock / text-chat-deadlock）只动锁/deadlock 测试，与 ⑥ 无重叠。

### ⑦ `feat-webui-i18n-tests` —— 待定（前端测试）
- **内容**：前端 device-label i18n 抽出做测试
- **相对 main 独有**：1 提交，3 文件，+126（`i18n_device_label.js` + `i18n_device_label.test.js`）
- **判断**：前端测试，价值取决于是否要 i18n。先排队。
- **spec/adr 痕迹**：❌ 无专门 spec/adr（大概率直接 PR 没走流程）→ **接手前须先补 spec 框定范围**。
- **复活**：`git branch feat/webui-i18n-tests archive/feat-webui-i18n-tests`

## 建议接手顺序

| 序 | 条目 | 理由 |
|----|------|------|
| 1 | `feat-q2-emit` | 模块 log 接线 = 用户痛点本体 + 约法三章前提，最高优先 |
| 2 | `fix-backend-p3-swallow-logging` | 静默异常记录，契合约法三章，小低风险 |
| 3 | `fix-backend-p1-asr-kwstraining-s101` | 显式 raise，方向正确 |
| 4 | `fix-backend-p1-kws-datamodule-b019` | 小修复 |
| 5 | `fix-webinfer-context-overflow-bound` | 测试，低风险 |
| 6 | `feat-drift-gate-runtime-v2.1` | 核验后大概率跳过 |
| 7 | `feat-webui-i18n-tests` | 待定 |

## 状态追踪（每条开工 / 合入后更新）

- [x] ① feat-q2-emit — 已合入 ✅ PR #68（squash → main 5eeec8a，约法三章门禁 PASS）
- [x] ② feat-drift-gate-runtime-v2.1 — 已合入 ✅ PR #70（squash → main 0e0a5fe，约法三章门禁 PASS；2 文件纯新增：.gitattributes 强制 LF + ADR-0012-v6-proposal；不删仍被引用的 drift_gate 文件）
- [x] ③ fix-backend-p3-swallow-logging — 已随 PR #27 落地 ✅ 无需单独 PR（精确核验）
- [x] ④ fix-backend-p1-asr-kwstraining-s101 — 已随 PR #25/#27 落地 ✅ 无需单独 PR（精确核验）
- [x] ⑤ fix-backend-p1-kws-datamodule-b019 — 已随 PR #25 等落地 ✅ 无需单独 PR（精确核验）
- [x] ⑥ fix-webinfer-context-overflow-bound — 已随早期 PR 落地 ✅ 无需单独 PR（精确核验）
- [x] ⑦ feat-webui-i18n-tests — 已合入 ✅ PR #69（squash → main 8828e1b，约法三章门禁 PASS，CI 9/9 绿）
