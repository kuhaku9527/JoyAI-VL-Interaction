# Drift Gate 接线 — 审查组反馈（退回 Codex 修订）

> 审查方：审查组对话（JoyAI-VL-Interaction 项目的 `决策/` 唯一写者）
> 日期：2026-07-31
> 对象：Codex 回传的 Drift Gate 接线改动（当前在 main 工作树，未提交、无 PR）
> 依据：`doc/specs/drift-gate-harness-spec.md`（APPROVED 2026-07-29）、`doc/adr/`、`决策/`、本仓库 AGENTS.md 治理协议（§0 修改治理协议）

---

## 0. 总评

**实现质量：通过。** 上一轮致命 bug（门禁在 Windows 因 `subprocess(shell=True)` + 单引号 grep 全部误报）已被 `bbab6d7 fix(drift-gate): cross-platform Python executor + v2 contract schema` 修复。实测 `scripts/drift_gate.py --contract config/drift-contract.json --phase all --mode open` → **4/4 PASS（block_fail=0, warn_fail=0）**，runtime 探针真实落地。

**但存在治理越权 + 收尾缺陷，必须修订后才能提 PR。** 以下每一项均已实测验证为真问题（非推测）。

---

## 1. 验证证据（实跑确认）

| # | 问题 | 验证命令 | 结果 |
|---|------|----------|------|
| P0-1 | 决策文档 D-019 的「校验」命令指向不存在的契约 | `python scripts/drift_gate.py --contract 决策/drift-contract.json` | 退出码 **2**（契约缺失 meta-error）；真实契约在 `config/drift-contract.json` |
| P0-2 | 决策文档引用已删除的旧骨架 | `ls reports/drift-gate-check-skeleton.py` | **MISSING**；已被 `scripts/drift_gate.py` 取代 |
| P0-3 | 对照：正确命令可用 | `python scripts/drift_gate.py --contract config/drift-contract.json --phase all --mode open` | 退出 0，4/4 PASS |
| P1-1 | `git add -A` 会塞入非源码垃圾 | `git add -A --dry-run` | 含 `.workbuddy_tmp/*`、`archive/agent-scratch-20260723/*`、`docs/`、`会话记录/`、`nul` 等大量文件 |
| P1-2 | `nul` 是 Windows 保留名伪文件 | `file nul` | `nul: empty`（0 字节，禁止入库） |
| P1-3 | ADR 放错目录 | `ls docs/ADR-0012-v6-proposal.md` | 存在但应在 `doc/adr/` |
| P2-1 | 本地门禁未真正调用 | `grep -nE "drift_gate\.py" services/scripts/run-windows.ps1`（排除注释） | **无输出**；仅注释 + 自动刷新探针，未 CALL 门禁 |
| P2-2 | start-joyai.ps1 完全没接 | `grep -c drift_gate start-joyai.ps1` | **0** |

---

## 2. 必改项（Codex 修订清单）

### [治理红线] G0 — `决策/` 越权写，必须还原
- Codex 直接改了 `决策/README.md`、`决策/跨域铁律.md`，违反 §0（仅审查组可写、需用户批准）。
- **动作**：`git checkout -- 决策/README.md 决策/跨域铁律.md` 还原这两个文件的未授权改动。
- **禁止**：Codex 不得重新编写 `决策/` 任何内容。D-019 条目与 README 索引行将由**审查组**按正确路径（`scripts/drift_gate.py --contract config/drift-contract.json`）另行收口。
- 原因：现行 `决策/跨域铁律.md` 的 D-019「校验」行写了失效命令（`reports/drift-gate-check-skeleton.py --contract 决策/drift-contract.json`），照抄会让决策文档自带一条跑不通的验证指令。

### [P1] 拆 PR — 当前未提交批次混了三件不相干的事
未提交改动：`quality.yml`（drift-gate CI job）、`AGENTS.md`（治理对齐）、`server.py`（全新 access-log 中间件）。
- **动作**：拆成两个 PR：
  1. **PR-A（drift 接线）**：`quality.yml` + `AGENTS.md`（治理文档改动需审查组复核，但可由 Codex 提 PR 走评审）。
  2. **PR-B（access-log 功能）**：`server.py` 的 access-log 中间件是独立新功能，与 Drift Gate 无关，单独成 PR，避免污染门禁评审面。

### [P1] 清理未跟踪垃圾（禁止 `git add -A`）
- **删除** `nul`（Windows 保留名伪文件，0 字节）。
- **删除或 gitignore** `.workbuddy_tmp/`、`archive/agent-scratch-20260723/`（agent 临时草稿，非仓库内容）。
- **移动** `docs/ADR-0012-v6-proposal.md` → `doc/adr/ADR-0012-v6-proposal.md`（ADR 归 `doc/adr/`）。
- **gitignore 或移出** `会话记录/`（多端点对话导出 JSON，属个人/协作产物，非源码）。
- 完成后 `git add -A --dry-run` 应只剩源码/文档/配置，无任何 scratch/会话文件。

### [P2] 接本地门禁（可选但建议，spec 要求）
spec 规定「启动前 static 自检、拉起后 runtime verify」。当前 `run-windows.ps1` 只自动刷新探针、未 CALL 门禁；`start-joyai.ps1` 未提。
- **动作**：在 `run-windows.ps1` 拉起服务前插入 `python scripts/drift_gate.py --contract config/drift-contract.json --phase static --mode open`（fail-open 不阻断）；拉起后插入 `--phase runtime`（依赖探针已刷新）。`start-joyai.ps1` 同理补 static 自检。
- 说明：CI 已 coverage（static/open），本地接入是完整性补齐，非阻塞。

### [P2] AGENTS.md 措辞对齐（轻）
新 AGENTS.md 写「Codex 是主开发 / 主理人+子代理」，与「决策写权在审查组」的治理模型略有冲突。提 PR-A 时顺手把该段措辞改为「Codex = 后端/DevOps 接线实现者；`决策/` 与治理协议由审查组维护」之类自洽表述。

---

## 3. 验收标准（Codex 提 PR 前自测）
1. `git status` 工作树仅含 PR-A / PR-B 的预期文件，无 `nul`、无 `会话记录/`、无 `.workbuddy_tmp/`、无 `archive/`。
2. `决策/` 两个文件已 `git checkout` 还原（无未提交 diff）。
3. `python scripts/drift_gate.py --contract config/drift-contract.json --phase all --mode open` 退出 0 且 4/4 PASS（Windows 本地）。
4. 若接了本地门禁：手动跑一次 `run-windows.ps1 -Mode minimal`，确认门禁在拉起前后各打印一次报告且无异常退出。
5. 两个 PR 分别提交，description 引用本反馈文档与对应 spec/ADR。

---

## 4. 审查组将另行处理（不依赖 Codex）
- 按正确路径收口 `决策/跨域铁律.md` D-019 + `决策/README.md` 索引行。
- 交叉验证 spec ↔ 契约 ↔ 决策条目一致性。

---
*本文件由审查组产出，供 Codex 端点读取修订；Codex 不得修改 `决策/` 或本文件以外的治理文档写权。*
