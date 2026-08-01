# Drift Gate 演化（v1 → v2 → v3）— 工程记忆

> **目的**：记录 JoyAI-VL-Interaction 项目 drift-gate 实施的三次演化，**防止未来会话误恢复废弃的 v1 文件**。
> **位置**：`reports/drift-gate-evolution.md`（reports/ 是 workbuddy 私有目录，不抢 `决策/` SSOT 写权）。
> **作者**：Codex 端点（2026-08-01）—— 回应 workbuddy "v1 恢复事故"。

---

## 0. 一次性警告（任何会话启动时必读）

> ⚠️ **v1 产物已永久废弃**——以下文件**永远不要恢复**（即使 git history 里能 checkout 出来）：
>
> - `config/drift-contract.json` （v1 contract schema）
> - `scripts/drift_gate.py` （v1 executor）
> - `scripts/drift_gate_smoke_test.py` （v1 smoke test）
>
> **原因**：v1 在 Windows 上有致命 bug（`subprocess(shell=True)` + 单引号 grep 全部误报），已被 workbuddy 的 v2 接管（`bbab6d7` commit 修复）。任何"恢复 v1"的尝试**会被 workbuddy 审查组立即 G0 阻断**（见 `reports/drift-gate-codex-feedback.md` §1 P0-1）。
>
> 如果 git status 显示这些文件是 `D`（已删）或不在 untracked 列表，**保持现状**。如果显示为 `??`（untracked 出现），**立即删除**（`cmd del /q <path>` 或 `rm <path>`）并写一条新 commit 说明"v1 cleanup"。

---

## 1. 时间线

### v1（2026-07-29）— Codex 初始实施

| 项 | 详情 |
|---|---|
| **作者** | Codex 端点（基于 workbuddy `drift-gate-handoff.md`） |
| **commit** | `bbab6d7 fix(drift-gate): cross-platform Python executor + v2 contract schema`（workbuddy 修复了 v1 Windows bug） |
| **实施** | `config/drift-contract.json`（4 条契约）+ `scripts/drift_gate.py`（执行器）+ `scripts/drift_gate_smoke_test.py`（smoke test）+ `.github/workflows/quality.yml` 末尾 drift-gate job |
| **评价** | **过度的工程化设计**——单一 agent（workbuddy）主开发场景不需要"3 层防线 / MCP 决策注册表 / 32KB AGENTS.md 限制 / 决策路由"那套 |
| **结局** | 已于 2026-08-01 由 Codex 回退（A 方案） |

### v2（2026-07-31）— workbuddy 接管

| 项 | 详情 |
|---|---|
| **作者** | workbuddy 审查组 |
| **commit** | `feat(drift-gate): runtime probe + integration smoke test for end-to-end n_ctx check` + `fix(drift-gate): cross-platform Python executor + v2 contract schema` |
| **实施** | `scripts/vlm_runtime_probe.py`（stdib only，4.9KB）+ `scripts/log_maintenance.ps1`（dry-run by default，4.5KB）+ log retention + cross-platform Python executor |
| **评价** | **克制、实跑、严格**——4/4 PASS Windows 本地测试；v1 的 Windows bug 修复 |
| **当前状态** | **现行版本**——workbuddy 主开发维护 |

### v3（2026-08-01）— Codex 回退 v1 产物

| 项 | 详情 |
|---|---|
| **作者** | Codex 端点 |
| **触发** | 用户反馈"是否过度防御了"+ workbuddy 审查组反馈（`reports/drift-gate-codex-feedback.md`） |
| **动作** | 1. 删 `config/drift-contract.json` / `scripts/drift_gate.py` / `scripts/drift_gate_smoke_test.py`<br>2. `git checkout HEAD -- .github/workflows/quality.yml AGENTS.md 决策/README.md 决策/跨域铁律.md`（还原我越权改的）<br>3. 移动 `docs/ADR-0012-v6-proposal.md` → `doc/adr/`<br>4. 删 `.workbuddy_tmp/`<br>5. `.gitignore` 加 `nul` / `-w` / `archive/agent-scratch-20260723/` / `会话记录/` 规则 |
| **后续事故** | v1 文件**被其他会话从 git history 恢复**（"以为是好 commit 状态"）—— 本文件就是为防止再次发生而写 |
| **本记忆** | 写于事故后 |

---

## 2. 验证清单（Codex 启动时可跑）

```bash
# v1 文件应该都 gone
ls config/drift-contract.json scripts/drift_gate.py scripts/drift_gate_smoke_test.py 2>&1
# 应该全 ls: cannot access

# v2 文件应该都在
ls scripts/vlm_runtime_probe.py scripts/log_maintenance.ps1
# 应该都在
```

## 3. 引用

- `reports/drift-gate-codex-feedback.md` — workbuddy 审查组反馈（G0 越权红线）
- `doc/specs/drift-gate-harness-spec.md` — 最初 spec
- `reports/drift-gate-handoff.md` — 最初 handoff
- `决策/跨域铁律.md` — D-019（**审查组维护，Codex 不可改**）

## 4. 未来会话注意

- **不要**写 `config/drift-contract.json` / `scripts/drift_gate.py` / `scripts/drift_gate_smoke_test.py` —— 已有 v2 替代
- **不要**改 `决策/跨域铁律.md` 等治理文档 —— G0 红线
- **如果**看到 v1 文件出现（git status ?? 显示），**立即删除 + 不 commit**（这文件就是永久废弃标记）
- **Codex 的角色** = 后端/DevOps 接线实现者，不是主开发、不是审查组（不写 `决策/`，不写 v1 残留）
- **如果**workbuddy 进一步演化 v2 → v3+ ，请更新本文件 §1 时间线
