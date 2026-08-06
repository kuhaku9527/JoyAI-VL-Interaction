# ADR 0017: drift-gate launcher 接线 + 崩溃修复 + verify.sh 统一

- 状态: Proposed（待用户审）
- 日期: 2026-08-06
- 上下文: doc/specs/f40-drift-gate-launcher-wiring.md

## 决策

1. **P0-1 修 `out` UnboundLocalError**：`scripts/drift_gate.py` L236-245 的 `else` 分支把 `text` 统一改名为 `out`（L242 `out = format_text(report)`、L243 `print(out)`、L245 `write_text(out + "\n")`），L263 复用已绑定的 `out`。不改 `--json` 分支、不改 `report` 结构、不改退出码。并把 `drift_gate_smoke_test.py` 接入 `quality.yml` 防回归。
2. **P0-2 launcher 接线**：`services/scripts/run-windows.ps1` 起服务前加 pre-flight，运行 `python scripts/drift_gate.py --contract config/drift-contract.json --phase static --mode closed --no-history`，rc≠0 则 **fail-closed 中止启动**；`.github/workflows/quality.yml` 的 `drift-gate` job 由 `verify.sh` 切到 `drift_gate.py`（保持不进 `needs` 链）。
3. **P0-3 统一为单一真值**：`drift_gate.py` 作唯一执行器（契约驱动、机器可读）；`verify.sh` 的 `grep_file` 静态断言能搬进 `config/drift-contract.json` 的搬过去，`verify.sh` 退化为仅 live `/health` 探针 + 委托；修 `verify.sh` L20 `--ci` no-op。采用**最小可用统一**，保留运行态探活。
4. **关键前提纠正（记录）**：CI 当前**未**调用 `drift_gate.py`（走 `verify.sh`），故 P0-2 的"接线"是**新工作**而非改已有接线；`start-joyai.ps1` 零引用。

## 不变 / 边界

- `--json` 输出契约不变（下游 `drift_gate_smoke_test.py` 依赖 `json.loads`）。
- drift 契约为 fail-open 默认不变（仅 F4-P1c 已加 `not_pattern:"8996"` 否定项）。
- 不扩大契约检查项，除非 P0-3 统一需要（属本 ADR 内增长）。
- 文本路径 / 多模态路径 warmup 行为（ADR-0016 已对齐）不受影响。

## 后果

正面：
- 消除 `drift_gate.py` 非 `--json` 路径的 `UnboundLocalError` 崩溃（潜伏缺陷，CI 因走 verify.sh 一直未暴露）。
- drift-gate 真正接进启动守卫（pre-flight fail-closed）+ CI（quality.yml 切 drift_gate.py），配置漂移在启动/合并前被拦。
- `verify.sh` / `drift_gate.py` 单一真值，消除双轨维护的契约漂移风险。

负面 / 取舍：
- P0-2 fail-closed 上 CI 有全红风险（已加护栏：先本机 clean main 验证 rc=0；job 不进 needs 链）。
- 历史文件命名 `*.json` 但非 `--json` 路径内容是文本（非阻塞，=stdout 内容；调用方可 `--no-history`）。
- P0-3 统一需逐条核对决策引用，工作量中等。

## 替代方案（拒了）

- **A. 只把 L263 的 `out` 改成 `text`**（历史写文本）。能跑，但破坏了 L250-252 注释明确表达的"写 JSON 供 operator 日后看 drift_gate 说 X at 09:00"意图；且 json 分支写 `out`、else 分支写 `text` 不一致。统一为 `out` 更符合原意且最干净。拒 A，选统一 `out`。
- **B. launcher 接线用 `open` 模式（不 fail-closed）**。失去启动守卫意义，与"接线"目标矛盾。拒。
- **C. 不统一，保留 verify.sh + drift_gate.py 双轨**。重复维护、契约易漂移（这正是要解决的问题）。拒；但采用最小可用统一，不激进搬运全部（折中）。
- **D. quality.yml drift-gate job 进 `needs` 链**。一旦该 job 因 runner 配额全红会拖垮整条链（已知陷阱）。拒，保持独立。

## 引用

- 来源：Wayfinder 地图 F-3/F-4 块 follow-up（F4-P0 延迟到独立 spec/adr）
- 关联 ADR-0016（F-3/F-4 安全批，F4-P0 同源）
- 关联约法：`决策/AI代码质量约法三章.md`（不静默、fail-open 仍有日志）
- 涉及文件：`scripts/drift_gate.py`、`scripts/drift_gate_smoke_test.py`、`.github/workflows/quality.yml`、`services/scripts/run-windows.ps1`、`scripts/verify.sh`、`config/drift-contract.json`
- 遗留：F4-P1a/b/d/e、F3-P2a、F3-P2b（低优先 follow-up）
