# Audit Status — 2026-07-24 (四角色对齐)

**Owner:** review dialogue (alignment) · **backend chapter:** backend dialogue
**Source:** `reports/code-health-audit-20260723.md` · `doc/adr/0011-phased-lint-gate.md` · `reports/handoff-lint-gate-batch2-20260724.md` · 共享 daily log `2026-07-24.md`
**Verified:** 2026-07-24 13:26 GMT+8 (PR states pulled live from GitHub API)
**架构章更新:** 2026-07-24 17:20 GMT+8 — #35 已合并（Batch2 配置flip，门禁现守护）、#31 已合并（lint gate 生效）、陈旧分支清理、quality-check 双跑确认（均经 GitHub API 实拉）。

> 说明：本报告按「前端/后端/测试/架构」四章分角色列出审计收口进度，便于各对话直接读自己那节。后端章由后端对话产出（详细版）；其余三章依据当日各对话写入共享 daily log 的证据重建。

---

## 前端 (joyai-frontend-webui)

**P0 最小集已全做（用户选「按推荐走」）。状态：本地未提交/未推送，PR #28 (`feature/frontend-p0`) 已开。**

- **前端测试底座（已落地 + 绿）**：Vitest 4 + jsdom 29（零浏览器二进制，CI 快），4 测试文件 **24 用例全绿** — `joy_ws`（连接 happy-path / applyApiSettings / cleanupServerSession）、`render_markdown`（escape/fallback/link）、`sanitize_static_html`（isSafeStaticUrl / sanitizeStaticCss / completeStaticHtmlDocument / DOM fallback）、`config_services`（readForm/writeForm/setBadge/save）。`npm test`=vitest run；`quality.yml` 加 `frontend-test` job（node20 + npm ci + npm test）。
- **CSS 设计令牌外置（已落地）**：抽整块 `<style>` 为 `static/styles.css`（112KB 可缓存），index.html 9438→5739 行改 `<link>`；`:root` 补 **20 个高频 hex 基元令牌**，全文件 top-20 hex 替换 `var()`；**修原内联 `:root` 悬空引用**（`--joy-red` 等引用未定义的基元，现已真正生效）。
- **a11y 第一轮（已落地）**：抽屉焦点陷阱（`setOpen` 扩：打开移焦 + Trap Tab + 关时归还 `#sidebarToggle`，`role=dialog`+`aria-modal`）；给 **22 个有 title 无 aria-label 的按钮**补 `aria-label`，4 个 `prompt-preset-option`（靠 data-label）补，themeToggle/settingsClose 单独补 → 27 按钮全有访问名。
- **遗留**：① 原 style 块历史括号差 1（line~1581 多余 `}`，浏览器容错，非 P0）；② P1（Vite+ESM 替代 `window.*` / 增量 TS / 集中状态）用户未要求，未做。
- **待办**：`quality.yml` 是 workflow 文件，推送须 fine-grained PAT(workflow scope) 或 workflow_dispatch；当前未自动 PR，待用户确认是否开 PR 合入。

---

## 后端 (joyai-backend)

**Batch-2 范围后端生产代码修复已全部完成并 gate 验证。**

### 范围与基线
ADR-0011 Batch 2 收紧 repo `select` 到**限定 S 子集**（非整族 S / BLE，后者归 Batch 3）。`main` 上 Batch-2 规则（`B019,B007,F841,S104,S108,S110,S112,S310`）共 **33 处**：

| Rule | 含义 | 总数 | 分组 |
|------|------|-----:|------|
| S110 | `try`-`except`-`pass` 静默失败 | 10 | A 清晰 |
| S108 | 硬编码 `/tmp` | 8 | B 评审 |
| S104 | bind `0.0.0.0` | 4 | B 评审 |
| B019 | 方法上 `@lru_cache`（实例泄漏） | 3 | A 清晰 |
| F841 | 未用局部变量 | 3 | A 清晰 |
| S112 | `try`-`except`-`continue` | 2 | A 清晰 |
| S310 | 可疑 `urlopen` | 2 | B 评审 |
| B007 | 未用循环变量 | 1 | A 清晰 |
| **计** | | **33** | A=19, B=14 |

### Group A 修复映射（清晰修复 19 处）

| Rule | 总数 | 后端生产已修 (PR) | 测试文件待办 (测试对话) |
|------|-----:|------------------:|------------------------:|
| B019 | 3 | 3 — PR #26 (`kws_data_module.py:80,89,94`→`cached_property`) | 0 |
| B007 | 1 | 1 — PR #30 (`analyze_kws_captures.py:64`) | 0 |
| F841 | 3 | 2 — PR #29 (`export_kws_onnx.py:239`)、PR #30 (`record_kws_corpus.py:146`) | 1 (`test_jarvis_kws_e2e.py:80`) |
| S110 | 10 | 7 — PR #27 (`sqlite_backend.py:184`,`session.py:108`)、PR #30 (`asr.py:502`,`server.py:709,808,815,820`) | 3 (`test_sherpa_load.py:163`,`test_jarvis_state_machine_lite.py:123`,`test_jarvis_webinfer_e2e.py:203`) |
| S112 | 2 | 2 — PR #30 (`server.py:371`,`vlm_service.py:665`) | 0 |
| **A 小计** | **19** | **15** | **4** |

**后端生产 Group A 收口：15/15 (100%)** — 均在 open PR 中，待合并。

### Group B（评审/noqa，14 处，延至 P0）
`S104×4` / `S108×8` / `S310×2`：本地工具架构意图项（绑定局域网、用 `/tmp` 临时、开本地模型 URL）。决策：保持现状，配置 flip 时加针对性 `# noqa` 带理由。**非后端归属** → P0 lint 决策 / 架构对话。

### 后端 PR 清单（全部 open + mergeable + gate=success，GitHub 实拉验证）

| PR | 规则 | Head | Gate |
|----|------|------|------|
| #24 | S101(生产) | `fix/backend-p1-hermes-webinfer` | success |
| #25 | S101(生产) | `fix/backend-p1-asr-kwstraining-s101` | success |
| #26 | B019×3 | `fix/backend-p1-kws-datamodule-b019` | success |
| #27 | S110×2 | `fix/backend-p3-swallow-logging` | success |
| #29 | F841×1 | `fix/backend-f841-deadvar` | success |
| #30 | B007×1,F841×1,S110×5,S112×2 | `fix/backend-batch2-groupA` | success |

> 注：早期摘要误标 F841 PR 为 "#28"；**#28 是前端对话的 PR**（`feature/frontend-p0`）。后端 F841 修复是 **#29**。

### 后端判定
后端归属的生产 lint 修复（Batch-2 范围）**已完成且 gate 验证**。剩余为跨角色协调（测试文件修复 + 配置 flip），明确超出后端范围。后端已就绪，待他对话落地其部分后协同合并 / 配置 flip PR。

---

## 测试 (joyai-code-reviewer / 测试对话)

**角色：验证/回归，不写业务码。已守卫后端修复并复现审计发现。**

- **复现/验证 `code-health-audit-20260723.md` 发现**：BLE001=106、S104=4/S108=8/S110=7/S112=2/B019=3/S310=2（与报告一致）；**报告少报四项** S101=97、S311=13、B007=3、F841=5（实际生产缺陷比报告写的多）。
- **hermes_api:262 回归测试落地**（`test/regression-round2`，commit `a978c80` 含 3 测试文件、4 用例、4/4 通过）：守卫 `hermes_api/main.py:262` 由裸 `except Exception: return ""` 改为 `logger.warning`（PR #24 修）；SSR 失败时须打 WARNING 且仍 fail-open。
- **守卫后端修复**：把 #26/#27/#29 修复 commit **单向 merge** 进 `test/regression-round2`，加 3 回归测试 — `test_sqlite_backend_close_logging.py`(2)、`test_session_stop_logging.py`(1)、`test_export_kws_onnx_deadvar.py`(1)；临时 revert 三处修复后对应测试均转红，已验证守卫有效。
- **待办（归属测试）**：Group A 测试文件 4 处（F841×1 + S110×3，见后端章表）按角色归测试对话修；或接受为排除项。
- **经验**：共享工作树多次碰撞（恢复步骤见 daily log），守卫他人修复用「单向 merge 进自己测试分支」即可本地跑通，无需改他人分支。

---

## 架构 (joyai-devops / 架构文档)

**角色：CI 配置 + 文档一致性 + 分支流程。已写 ADR-0011 并推进 Batch 1/2/3。**

- **ADR-0011 分阶段 lint gate**（Status: Batch 1 已落地；Batch 2 代码修复已合 main，**门禁 `select` flip 已合 #35（main=`d90570c`）→ 现守护 Batch2 修复**；Batch 3 已合并 #31 → 部分生效）：Batch 1（安全、不碰 workflow select）／Batch 2（select 加 S3xx + 去 B904/B019/B007 extend-ignore，显式修有限高优项）／Batch 3（select 加 BLE001/S101/S311）。约束：baseline 只减不增；推 workflow 文件须 fine-grained PAT。
  - **Batch 3 实现要点（偏离原 `--baseline` 计划）**：ruff 0.15.22 **无 `--baseline`**，改用集中 `per-file-ignores` 冻结 87 处既有违规（33 生产 + 54 测试）作基线；webui 因自有 `[tool.ruff]` 表，其 10 文件基线放 `services/webui/pyproject.toml`，根 `per-file-ignores` 管其余 20 非 webui 文件。burn-down = 修一处即从 `per-file-ignores` 删该条目。详见 `doc/adr/0011-phased-lint-gate.md` + `reports/handoff-lint-gate-batch3-20260724.md`。
- **Batch 1 执行（✅）**：远端分支清理（6 陈旧分支仅 `fix/background-agent-test-ruff` 仍在，已删；其余 5 早已不在远端）；`lint-baseline.md` 纠正（删假 B904 条目，B019 钉 `kws_data_module.py:80,89,94`，加 tool-version-drift 警示）；建隔离 worktree `arch`（`ci/lint-gate-batch2`），PR `docs/lint-gate-adr0011-batch1`（commit `72bd0a3`，已 push）。
- **Batch 2 准备（✅）**：校正审计漂移（repo 无 extend-ignore，B019/B007 本就在报）；重新定性 Batch 2 = 加 **S104/S108/S110/S112/S310** + B019/B007/F841（共 33 处，见后端章）；产出 `reports/handoff-lint-gate-batch2-20260724.md`（精确 file:line + pyproject diff + 单 PR 落地规则），**代码修复归后端对话**。
- **Batch 3 执行（✅ 已合并 #31）**：`ci/lint-gate-batch3` @ `31642f2` → squash 合并 main @ `051e1c5`（2026-07-24，merge 经 REST API，`gh`/fine-grained PAT 不能 `gh pr merge`）；CI 双 run（`30069637157`/`30068390597`）均 success；head 分支合并后已删。门禁现强制 BLE001/S101/S311 + 87 违规基线。
- **陈旧远端分支清理（本架构轮次 ✅）**：`compare/main...<b>` 校验 `ahead_by==0` 安全后删 6 支（`feature/memory-store-v02-hooks`/`fix/adapter-p0-correctness`/`fix/webui-block5-connectws`/`fix/webui-live-refs`/`milestone2-adapter-core-split`/`ci/quality-gate`）；保留 `test/webinfer-context-overflow`（`ahead_by=2`，含未合入工作）；另 `ci/lint-gate-batch3` 随 #31 合并后删。
- **`quality-check.sh` 双跑（✅ 已确认，无需改动）**：L23 `"$RUFF" check .` + L27 `"$RUFF" format --check .` 已双跑；原 Batch 1 建议项落地，无代码改动。
- **待办（归属架构）**：① **配置 flip（Batch 2）✅ 已合并 #35（main=`d90570c`，CI 双跑 success）** — `select` 加 S104/S108/S110/S112/S310 + 17 处 `# noqa`，门禁现守护后端 #24-#30 修复；B019/B007/F841 由 B/F 家族已覆盖未重复加；② Batch 3（✅ 已合并 #31，per-file-ignores 替代 --baseline）；③ quality-check 双跑（✅ 已确认）；④ **frontend-test job 缺失（⚠️ P0，仍 open）** — `quality.yml` 无 `frontend-test`，#28 的 25 Vitest 用例 CI 不跑，补 job 须推 workflow 文件 → 需 fine-grained PAT（见 `handoff-remaining-ci` ITEM B，归测试对话）。合并须用 REST API 或 `gh`/`gho_`（fine-grained PAT 不能 `gh pr merge`）。

---

## 跨角色缺口与可并行节奏

- **S104/S108 已由 PR #35 加 `# noqa` 处理（共 17 处：S104×4/S108×8/S310×2/S110×3）**：门禁现守护，非阻塞。见 `handoff-remaining-ci` ITEM A（✅ 已落地）。
- **陈旧远端分支（部分清理）**：Batch 1 清 `fix/background-agent-test-ruff`；本架构轮次清 6 支(ahead=0)+`ci/lint-gate-batch3`(随#31删)+`feature/frontend-p0`(squash-#28删)；**保留** `ci/lint-gate-batch2`(ahead=3,无 S 子集 flip,仅 Batch2 prep)、`docs/lint-gate-adr0011-batch1`(ahead=2,Batch1 docs,核实后再删)；`test/webinfer-context-overflow`(ahead=2)保留。
- **`quality-check.sh` 双跑（✅ 已确认）**：L23 `ruff check .` + L27 `ruff format --check .` 已双跑，无需改动。
- **前端测试 CI 缺口（⚠️ P0，未补）**：`quality.yml` 无 `frontend-test` job，#28 合并的 25 Vitest 用例不在 CI 跑（测试无人守）；须开 workflow-scope PR（fine-grained PAT）加 job。见 `handoff-remaining-ci` ITEM B。
- **本地悬空 WIP**：`main` 工作树有测试对话未提交 WIP（43 文件级）；禁碰，勿在共享树提交。
- **可并行合并节奏**：**后端 6 PR（#24/#25/#26/#27/#29/#30）+ #31 + #35 均已合并 main（审计收口，main=`d90570c`）**；#28 已合；合并须用 REST API 或 `gh`/`gho_`（fine-grained PAT 不能 `gh pr merge`）。注：#32/#33/#34 为其他对话(test/frontend) open PR，不在审计范围。
- **协调关键（ITEM A ✅ 已合 #35）**：后端 #24–#30 已合 main，flip 以独立 PR #35 落地（`select` 加 S 子集 + 17 处 `# noqa`），CI 双跑绿；审计收口完成。
