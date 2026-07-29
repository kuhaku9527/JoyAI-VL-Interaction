# 全项目级评审报告 — live_adapter.py 拆分（ADR 0007 里程碑 1）

- 日期：2026-07-20
- 评审团队：JoyAI-VL-Interaction 研发团队（主理人 + 5 角色）
- 评审对象：git 提交 `2dacfa5`（refactor，10 文件 +4187/-3519）+ `2a76044`（docs，ADR 0007 + lint-baseline）
- 角色分工（按 SOP 顺序）：前端 WebUI → 后端 → ML/VLM → DevOps → 代码审查（最终）
- 流程：主理人建团队、调度 5 角色各出专业意见（经主理人中转），由代码审查做最终审查

---

## 总裁决：🔴 阻断（仅一条配置缺陷即构成合并阻断）

唯一硬阻断项 = **打包缺口**（`pyproject.toml` 的 `py-modules` 漏列 10 个模块）。修复约 1 行 pyproject 改动即满足最小可合并集。其余发现均为**非阻断**：要么是单体时代既有债（拆分未引入回归，66 测试全绿），要么是风格级，应按里程碑 2 / 独立 PR 跟踪，**不应阻塞本次合并**。

正面确认：门面契约完整保留（`live_adapter.py` re-export `StreamingInferAdapter`/`AdapterConfig`，console script `live_adapter:main` 可用，e2e 测试 import 路径被覆盖）；9 个新拆模块的机械缺陷（F401/F811/F821/E402/I001/D100）已清零。

---

## 五角色结论摘要

| 角色 | 结论 | 关键判断 |
|------|------|----------|
| 前端 WebUI | ✅ 通过·零风险 | 生产前端经 HTTP(127.0.0.1:8070/v1) 解耦，不 import 门面；唯一直接 import 的是 e2e 测试（已被门面 re-export 覆盖）；XSS/WS/WebRTC 零影响 |
| 后端 | ⚠️ 有风险 | 依赖 DAG 单向无环（已静态确认）；**打包阻断**；`adapter_core._handle_chat_payload`(:1096-1420) 为 ~324 行巨型混合方法 |
| ML/VLM | ⚠️ 有风险·非阻断 | 决策 token 解析未漂移；视频路径未走 `_parse_decision_tokens` 且缺决策字段（既有债）；~60 行系统提示/常量块在 7 文件重复（决策文案改一处会静默漂移） |
| DevOps | ⚠️ 有风险 | 启动编排/外部接入/依赖隔离不受影响；**同打包阻断**；CI 门禁无容差/上限；树内 `*.egg-info` 已被 `.gitignore` 覆盖（非泄漏） |
| 代码审查 | 🔴 阻断 | 独立核实打包缺口属实；机械缺陷已清零；给出最小可合并清单与里程碑 2 优先级 |

---

## 阻断项详情（已独立复核）

**`services/webinfer/pyproject.toml:58` — `py-modules` 缺口（10 个模块未打包）**

证据链（主理人独立复核）：
- `py-modules = ["live_adapter", "memory_summarizer", "system_prompts"]` —— 仅 3 个
- 实际顶层模块 **13 个**：adapter_core, adapter_types, app, config, io_utils, live_adapter, memory_store_client, memory_summarizer, prompt_building, request_parsing, response_format, system_prompts, time_ranges
- `joyvl_webinfer_adapter.egg-info/top_level.txt` 仅列 3 个 → 干净 `pip install .` 的 wheel **不含**其余 10 个
- 两个提交均未改 pyproject.toml

**后果**：`live_adapter.py:10` `from adapter_core import StreamingInferAdapter` 在 wheel 安装后 import 即 `ModuleNotFoundError`；`joyvl-webinfer-adapter` console script 与 `python live_adapter.py` 启动即崩溃。本地 `-e`/源码在盘掩盖了该问题。

**推荐修复（按风险从低到高）**：
- **方案 A（推荐）**：把 13 个顶层模块全数列入 `py-modules`（零契约破坏）
- **方案 C（次选）**：删除 `[tool.setuptools] py-modules` 键，让 setuptools 自动发现（契约不变、零维护，较隐式）
- 方案 B（转 package 子目录）：会把 `live_adapter` 变为 `joyvl_webinfer.live_adapter`，破坏 ADR 约定的外部契约，**本次不可取**
- 验证：干净 venv `pip install .` 后 `python -c "import live_adapter; from live_adapter import StreamingInferAdapter, AdapterConfig"` 成功；console script 可启动。建议 CI 加「构建 wheel + import 冒烟」

---

## 发现清单（blocking → nits）

### 🔴 BLOCKING
1. `pyproject.toml:58` `py-modules` 缺口（10 模块未打包）—— 修复即最小可合并集

### 🟠 高优先（既有债·建议里程碑 2 / 独立 PR·非阻断）
2. `adapter_core.py:1316-1324` + `:1392` — 帧路径未走 `_parse_decision_tokens`、缺 `decision`/`delegation_question` 字段（与文本路径 `:746/:762` 不一致）；属既有债，里程碑 2 统一「模型→解析→response_records→TTS」原子链路（维持 `state.lock` 临界区）
3. 系统提示/常量块在 9 个新模块各自**复制**（非 import）定义，且 `adapter_core.py:112 DEFAULT_SYSTEM_PROMPT_EN`（闭标签）与 `:124`（开标签）两变体并存 → 决策文案改一处静默漂移；建议里程碑 2 收敛到单一 `prompt_constants.py`
4. `adapter_core.py:708` — memory warmup 写 `_memory_block_cache` 未持锁（并发竞态）；既有债，里程碑 2 修（`SessionState` 单 owner + warmup 持锁）

### 🟡 nit（风格/低优先·非阻断）
5. `adapter_core.py:648` `B007` 未用循环变量 `part_index`（改用 `for part in content:`）
6. `adapter_core.py:1274-1284` 残留 `DEBUG v0.2` 日志含单引号字符串（违 `quote-style = double`），建议移除或降 DEBUG
7. `memory_summarizer.py:1 D100`、`tests/test_prompt_guard.py:16 E402` — 均来自 `6315215`（quality-gate 提交），已计入基线；会被 `ruff check .` 标红 → 若 `quality.yml` 严格，main 当前 CI 已红。建议落实 baseline「只降不升」

### 🟢 正面确认
- 66 webinfer 测试通过；门面 53 行仅 re-export，`StreamingInferAdapter`/`AdapterConfig` 覆盖（`:10-11`、`:37-49`）
- 依赖 DAG 无环已静态确认；新拆模块 `F401/F811/F821/E402/I001/D100` = 0（ruff 复核）

---

## 里程碑 2 落地优先级（结合五角色风险）

- **P0（正确性/一致性）**：#2 决策解析链路统一；#4 并发竞态修复；#3 常量收敛到单一 `prompt_constants`（高优先——静默漂移风险随迭代放大）
- **P1（结构）**：`adapter_core` 1992 行拆 5 簇（session / infer_loop / summarizer_routing / memory_io / prompt_assembly）+ coordinator；重点治理巨型方法 `_handle_chat_payload`，组合注入防环，后台任务生命周期收口
- **P2（工程化）**：① 打包门禁（CI wheel 构建 + import 冒烟）；② 落实 lint-baseline「只降不升」（`quality.yml` 当前无容差/上限）；③ 根 `ruff target-version = py39` → 升 `py310+`（服务要求 3.12，吸收 UP007/UP006 共 129 项）

---

## 最小可合并（merge-blocking）清单

- [ ] 修复 `services/webinfer/pyproject.toml:58`：`py-modules` 补齐为全部 13 个顶层模块（或删除该键改自动发现）
- [ ] 验证：干净 venv `pip install .` 后 `python -c "import live_adapter; from live_adapter import StreamingInferAdapter, AdapterConfig"` 成功；`joyvl-webinfer-adapter` console script 可启动

其余（#2–#7）均不阻塞本次合并，建议随里程碑 2 / 独立 PR 处理，并在合并后登记进 `lint-baseline.md` 跟踪。
