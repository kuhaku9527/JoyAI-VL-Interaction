# Drift Gate 实施 Handoff（交后端 / DevOps 接线）

> 来源：审查组提案 `doc/specs/drift-gate-harness-spec.md`（2026-07-29）
> 受众：**后端 / DevOps 端点**
> 性质：本文件是 handoff，**不含批准**。运行配置（`run-windows.ps1` / `start-joyai.ps1` / `quality.yml`）属高危，须走"用户批准 → 落盘 `决策/` → 同 PR 更新契约"后再动。

---

## 0. 一句话背景

`决策/drift-历史.md` 记录的三类"运行态≠决策态"漂移（n_ctx 回退、端口 8996↔8997、webui 默认 8996）**现已闭环**，但根因是"没有门禁、漂移只能事后发现"。本 handoff 让你把这类漂移**前移为自动拦截**：启动自检 + CI 合并前检查。

---

## 1. 你要做的事（三步）

### 步骤 A — 建立契约（机器可读投影）
新建 `drift-contract.json`（建议放仓库根 `config/` 或 `决策/` 下）。内容是"运行不变量清单"，每条带：
`id` / `decision_ref`（指向 `决策/` 条目）/ `phase`(`static`|`runtime`) / `command` / `expected_regex` / `severity`。
**值从 `决策/` 当前记录取，不要拍脑袋**；本文件 §3 有模板。

### 步骤 B — 接线启动自检
在 `run-windows.ps1` / `start-joyai.ps1` 加调用：
- 拉起服务**前**跑 `static` 阶段（查 env/配置/代码常量）。
- 拉起服务**后**跑 `runtime` 阶段（查 `/props`、端口监听、日志 `n_ctx_slot`）。
- 初期 `--mode open`（不符只 warning）；稳定后对新不变量切 `--mode closed`。

### 步骤 C — 接线 CI
在 `.github/workflows/quality.yml` 增一步：跑执行器的 `static` 阶段（合并前）。模式同上，先从 open 起。

---

## 2. 执行器骨架（已就绪，可复制）

文件：`reports/drift-gate-check-skeleton.py`（纯 stdlib、零业务侵入、fail-open 默认）。
直接复制为 `scripts/drift_gate.py` 或并入现有 CI 工具，按 §1 调用。
**不要**在脚本里硬编码任何端口/`n_ctx` 值——值全在契约里。

```bash
# 示例调用
python scripts/drift_gate.py --contract drift-contract.json --phase static --mode open
python scripts/drift_gate.py --contract drift-contract.json --phase runtime --mode closed --report drift_report.txt
```

---

## 3. 契约模板（JSON）

```json
{
  "version": 1,
  "source_of_truth": "决策/",
  "checks": [
    {
      "id": "vlm-n_ctx",
      "decision_ref": "决策/业务-上下文架构.md D-050 / drift-历史.md DRIFT-1",
      "description": "VLM 运行时 n_ctx 必须等于 webinfer main_ctx_tokens=16384",
      "phase": "runtime",
      "command": "grep -n 'n_ctx_slot' logs/llama-main.log",
      "expected_regex": "16384",
      "severity": "block"
    },
    {
      "id": "memory-store-port",
      "decision_ref": "决策/drift-历史.md DRIFT-2 / 服务-memory-store.md",
      "description": "memory-store 默认端口须为 8997（非废弃 8996）",
      "phase": "static",
      "command": "grep -n 'MEMORY_PORT\\|8997\\|8996' run-windows.env memory-store/app.py",
      "expected_regex": "8997(?!.*8996)",
      "severity": "block"
    },
    {
      "id": "webui-gateway-port",
      "decision_ref": "决策/drift-历史.md DRIFT-3 / 服务-webui.md",
      "description": "webui 网关 MEMORY_STORE_URL 默认须指向 8997",
      "phase": "static",
      "command": "grep -n 'JOYAI_MEMORY_STORE_URL\\|8996\\|8997' run-windows.ps1 services/webui/server.py",
      "expected_regex": "8997",
      "severity": "warn"
    }
  ]
}
```

> 上述 `command`/`expected_regex` 为示意，后端按实际校验方式调整；契约是**你维护的投影**，不是决策书本身。

---

## 4. 闸门纪律（务必遵守）

- **任何"改运行不变量"的 PR，必须同 PR 更新 `drift-contract.json`**。否则 CI 门禁会因"契约 vs 新运行态不符"拦下——这正是想要的：逼着走正规渠道。
- **用户批准的落点是 `决策/`**；契约是 `决策/` 的机器投影，随同更新，不要在脚本里另立真值。
- **不要**让门禁改写 `决策/`，也不要 fail-closed 全量起步（先用 open 观察）。

---

## 5. 收尾回执

实施完成后，回执给审查组：触发收敛 `决策/跨域铁律.md`（补"运行态=决策态 门禁"铁律）+ 把本 handoff 状态记为"已实施"。审查组据此闭环 spec→adr→决策。
