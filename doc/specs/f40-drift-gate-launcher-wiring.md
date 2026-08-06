# Spec: F4-P0 — drift-gate launcher 接线 + 崩溃修复 + verify.sh 统一

- 关联 ADR: `doc/adr/0017-drift-gate-launcher-wiring.md`
- 来源: Wayfinder 地图 F-3/F-4 块 follow-up（F4-P0 显式延迟到独立 spec/adr，治理纪律）
- 日期: 2026-08-06

---

## 1. 背景 / 为什么

F-3/F-4 安全批（PR #87 → `bcc1543`，ADR-0016）收尾时，把 F4-P0 作为 follow-up 延迟，原因是它属于**跨模块 launcher 改动**，按治理 §0 应先落 spec/adr。

本次 recon（`f40-recon` 只读）纠正了一个关键前提：

> **原以为"CI 走 `--json` 调 `drift_gate.py`"是错的。** 实际情况：
> - CI `quality.yml` 的 `drift-gate`(L105) / `drift-gate-runtime`(L186) 两个 job 跑的是 **`bash scripts/verify.sh`**，不是 `drift_gate.py`。
> - `services/scripts/run-windows.ps1` 仅在 L316 / L797 有**注释**提及 drift_gate runtime 消费，无实际调用。
> - `start-joyai.ps1` **零引用** drift_gate / verify.sh。
> - `drift_gate.py` 目前仅被 `drift_gate_smoke_test.py`（本地测试，**不在 CI**）调用。

因此"launcher 接线"不是改已有接线，而是**把 drift-gate 真正接进启动/CI 守卫**（新工作）。

另外 recon 确认了一个**真实崩溃 bug**：

> `scripts/drift_gate.py` 的 `out` 仅在 `--json` 分支（L237）赋值；非 `--json` 分支赋的是 `text`（L242）。但 L263 无条件引用 `out` 写历史报告（默认不带 `--no-history` 即触发）。所以**不带 `--json` 且未带 `--no-history`** 时（如 `--phase static --mode closed`、`--phase all --mode closed`），控制流到达 L263 → `UnboundLocalError` → rc≠0 提前崩。是潜伏缺陷（CI 因走 verify.sh 一直没暴露）。

---

## 2. 目标 / 非目标

**目标（三个子项）：**
- **P0-1**：修 `drift_gate.py` 的 `out` `UnboundLocalError`，并把烟雾测试接入 CI 防回归。
- **P0-2**：把 drift-gate 接进启动编排——`run-windows.ps1` 起服务前 pre-flight（fail-closed 中止），并把 `quality.yml` 的 drift-gate job 切到 `drift_gate.py`。
- **P0-3**：`drift_gate.py` 与 `verify.sh` 统一为**单一真值**（契约驱动、机器可读），消除双轨维护。

**非目标：**
- 不改 `--json` 输出契约（下游 `drift_gate_smoke_test.py` 依赖）。
- 不扩大 drift 契约检查项，除非 P0-3 统一需要（属本 spec 内增长，不另开票）。
- 不动 review 组（决策文档唯一写者）职责。

---

## 3. 范围 / 涉及文件

| 文件 | 子项 | 改动 |
|---|---|---|
| `scripts/drift_gate.py` | P0-1 | L236-245 else 分支 `text`→`out` |
| `scripts/drift_gate_smoke_test.py` | P0-1 | 增"非 `--json` 路径"断言 |
| `.github/workflows/quality.yml` | P0-1 / P0-2 | drift-gate job 改/加 drift_gate.py；新增 smoke step |
| `services/scripts/run-windows.ps1` | P0-2 | 起服务前 pre-flight（fail-closed） |
| `scripts/verify.sh` | P0-3 | 退化为 live `/health` 探针 + 委托 `drift_gate.py`；修 `--ci` no-op |
| `config/drift-contract.json` | P0-3 | 扩静态断言覆盖（可选，最小可用） |

---

## 4. 详细设计

### P0-1 修 `out` UnboundLocalError

- **位置**：`scripts/drift_gate.py` L236-245，历史写 L249-263。
- **根因**：`out` 仅在 `if args.json:` 分支绑定（L237）；`else:` 分支绑 `text`（L242）；L263 `history_path.write_text(out, ...)` 无条件引用 `out`。
- **改法（最小、保原意）**：`else` 分支把 `text` 统一改名为 `out`：
  - L242 `out = format_text(report)`
  - L243 `print(out)`
  - L245 `Path(args.report).write_text(out + "\n", encoding="utf-8")`
  - L263 复用已绑定的 `out`。
- **不动**：`--json` 分支、`report` 结构、退出码逻辑。`drift_gate_smoke_test.py` 的 `json.loads` 路径不受影响。
- **已知轻微不一致（非阻塞）**：历史文件命名 `ts_safe + ".json"`，非 `--json` 路径下内容是文本而非 JSON。这是原设计的命名约定（json 分支写 JSON、非 json 写文本，都用 `.json` 扩展名）。统一为 `out` 后行为一致：**历史文件内容 = 当时 stdout 打印的内容**。spec 接受此命名；调用方可用 `--no-history` 跳过。

### P0-2 launcher 接线

- **`run-windows.ps1` pre-flight**（建议放在"起各服务"函数之前、确认 venv 就绪之后）：
  ```powershell
  # Drift-gate pre-flight: 配置/代码级漂移静态守卫（fail-closed）
  & $Python scripts/drift_gate.py --contract config/drift-contract.json --phase static --mode closed --no-history
  if ($LASTEXITCODE -ne 0) {
      Write-Error "drift-gate (static/closed) 检测到配置漂移，中止启动（rc=$LASTEXITCODE）"
      exit 1
  }
  ```
  - 用与启动相同的解释器 `$Python`（launcher 已解析的 venv python）。
  - `--phase static`：只校验配置/代码（L204-209），无需运行实例，适合 pre-flight；`runtime` 阶段（vlm-n_ctx）依赖运行态，留给 CI `drift-gate-runtime` job。
  - `--no-history`：pre-flight 不写历史日志（避免污染；且修 P0-1 后非 json 路径已安全）。
- **`quality.yml` 切换**：`drift-gate` job（L105）由 `bash scripts/verify.sh --ci` 改为 `python scripts/drift_gate.py --contract config/drift-contract.json --phase static --mode closed`；`drift-gate-runtime` job（L186）可改用 `drift_gate.py --phase runtime --mode closed`（需 vlm-runtime-props.json 已由 vlm_runtime_probe 写出）。
- **⚠️ 风险护栏（必做）**：fail-closed 直上 CI 前，**必须先在 clean main 手动跑** `python scripts/drift_gate.py --contract config/drift-contract.json --phase static --mode closed --no-history` 确认 rc=0（当前代码全过），否则 CI 全红。且 `quality.yml` 的 drift-gate job **保持不进 `needs` 链**（已知 runner 配额耗尽会全 FAILURE 且 steps:[] 的陷阱，见 ADR-0016 引用 / `决策/` 历史）。

### P0-3 verify.sh / drift_gate 统一

- **方向**：`drift_gate.py` 作**单一真值**（契约驱动、机器可读 JSON）；`config/drift-contract.json` 是声明源。
- **搬运规则**：`verify.sh` 的 `grep_file` 静态文本断言（覆盖 D-020..049、DRIFT-2、D-022 n_ctx、D-030 timeout、D-008/031、D-015 8996、D-034 vitest、D-007 ruff==0.15.22、D-033/036 前端、D-076）——能表达为 `paths`+`pattern`(+`not_pattern`) 的，搬进 `config/drift-contract.json`；搬不动的（live `/health` 探活、vitest/ruff 实跑、耗时构建）留在 `verify.sh`。
- **`verify.sh` 退化**：保留 live `/health` 探针（契约 grep 无法替代运行态探活）；其余静态断言可委托 `python scripts/drift_gate.py --json` 或留 shell 子集。**不删运行态探活能力。**
- **⚠️ 修 `verify.sh` L20 的 `--ci` no-op**：注释承诺"static-only 子集"但未实现（仅当 QUIET 判断）。统一时要么实现该子集、要么删掉 `--ci` flag，避免误导。
- **范围控制**：采用**最小可用统一**，不激进搬运全部；优先消除"双轨维护同一断言"的漂移风险。

---

## 5. 测试 / 验收

- **P0-1**：`drift_gate_smoke_test.py` 增两类断言——(a) 不带 `--json` 跑 rc0 不崩；(b) `--phase static --mode closed` 不带 `--json` 也不崩（直接覆盖 L263 回归）。并把该烟雾测试接入 `quality.yml`（新增 `drift-gate-smoke` step/job）——这是**唯一能防 `out` bug 回归的自动化**。
- **P0-2**：在 clean main 手动验证 pre-flight rc=0 不中止；再临时把 `run-windows.env` 端口改 `8996` 验证 fail-closed 中止（rc≠0）。
- **P0-3**：`verify.sh` 仍能跑通 live `/health`；`drift_gate.py` 静态覆盖集与原 `verify.sh` 静态断言**等价**（逐条核对决策引用）。
- **全量回归**：webinfer 单测 + `quality.yml` 全绿（注意 §4 P0-2 护栏的 runner 配额全红陷阱）。

---

## 6. 风险 / 取舍

| 项 | 风险 | 缓解 |
|---|---|---|
| P0-2 fail-closed 上 CI | 若当前代码有静默 block 不符，CI 全红 | 先本机 clean main 验证 rc=0；job 不进 needs 链 |
| P0-1 历史文件扩展名 | 非 json 路径写文本到 `.json` | 接受（=stdout 内容）；调用方可用 `--no-history` |
| P0-3 统一范围过大 | 引入回归 / 丢运行态探活 | 最小可用统一；保留 `/health` 探针 |
| verify.sh `--ci` no-op | 误导维护者 | 实现子集或删 flag |

---

## 7. 实施顺序建议

1. **P0-1** 修 bug + 测试接入 CI（低风险，先止血 + 建防回归网）。
2. **P0-2** launcher 接线：先在 `run-windows.ps1` 做 pre-flight，本机验证全过后**再**切 `quality.yml`。
3. **P0-3** 统一（最后，最小可用）。

---

## 8. 遗留 / out of scope

- F4-P1a/b/d/e 仍 follow-up（低优先）。
- F3-P2a / F3-P2b 缓存清理 follow-up（低优先）。
- P0-3 若需扩契约，属本 spec 内增长，不另开票。
