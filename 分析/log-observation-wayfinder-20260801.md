# 日志观察层 — Wayfinder 决策地图 (2026-08-01)

> 导航师产物（决策地图，非交付物）。范围小、路已大体清晰，故只列决策工单 + 推荐路径，不展开 issue 跟踪器。

## Destination（每会话先对齐）
给本地 5 服务一个「日志终端」式实时观察能力，**同时保留**现有文件日志的可追溯/可分析优势。最小工程、零新依赖、不破坏 Windows 进程组管理。

## Notes（领域事实）
- **现状（用户提供，已采信）**：无集中终端，散落文件 + grep/jq。
  - `logs/launcher-<ts>.log`（Start-Transcript，一次性）
  - `services/.logs/<svc>.log` + `.err.log`（Start-Process -Redirect*，运行期）
  - `logs/drift-gate-history/<ts>.json`（校验期）
  - `logs/vlm-probes/<ts>.json`（启动期）
  - `logs/webui-access-YYYY-MM-DD.log`（每个 HTTP 请求）
- **Codex Q2 spec**：commit `e597b10`，规定事件统一 JSONL → `logs/events/<service>-<UTC>.jsonl`（仅文件格式，**不解决实时看**）。Q2 实现未做。*（已确认 e597b10 仍是 main 的 HEAD，2026-08-01 核验：`git rev-parse main` = e597b10）*
- **约束**：`start-joyai.ps1` 用 `WindowStyle="Hidden"` 启动；进程组管理依赖此，不能简单去掉 Hidden。→ **D3 结论：不改 Hidden**。
- **纪律**：改码必进 worktree；`.ps1` 用 CRLF（Windows 原生；`.gitattributes` 未约束 `*.ps1`，CI 门禁不查）；零外部依赖优先（PowerShell 自带 `Get-Content -Wait`）。

## Decisions so far
- **D1 [resolved] 观察层方案 → 自带 PS**。已实现 `scripts/tail_logs.ps1`（PowerShell 7+，`#requires -Version 7.0`）。零外部依赖：用 `Get-Content -Wait` + 每文件 `Start-ThreadJob`，按服务上色（`[Console]::ForegroundColor`），支持 `-Filter` / `-Since` / `-Services` / `-All` / `-Once` / `-IncludeLauncher`。验证过的真实行为：每服务前缀 `[llama-main]`/`[memory-store]`/`[webinfer]`/`[webui]`，`-Filter WARNING` 可隔离级别，`-Since 1h` 时间窗生效，实时 follow 标记实时出现。
- **D2 [resolved] Q2 JSONL 范围 → 分开**。tail 只做观察层；Q2（改造 emit → `logs/events/*.jsonl`）仍是独立 ticket，本次未动任何 emit 站点。tail 的 JSONL 模式与 Q2 **互补不竞争**：检测到 `logs/events/*.jsonl` 时切彩色 `ts|service|event|msg` 渲染，否则优雅回退文本模式（修复了空数组 `Get-Content -Path @()` 崩溃）。
- **D3 [resolved] start-joyai.ps1 → 不改 Hidden**。保持 `WindowStyle="Hidden"`（进程组安全）。观察与启动解耦由 tail 负责。
- **D4 [resolved] 彩色/过滤 → 内置够**。未引外部工具（lnav/multitail）。
- **e597b10 确认**：仍是 `main` 的 HEAD（2026-08-01 核验）。
- **落地**：worktree `JoyAI-VL-Interaction-wt-log-obs` @ 分支 `fix-log-obs-tail`（== main tip e597b10），commit `be242f1`（236 行 `.ps1`，CRLF）。**仅本地提交，未推送、未合并**——其他对话端（drift-gate / ui-i18n）活跃，等协调后再决定是否开 PR / 合并。

## Fog / 待决工单（轻量）
- **D1 [grilling / HITL] live 观察层方案**
  做 `scripts/tail_logs.ps1`（多源 tail + 按服务上色 + `-Filter`/`-Since` + Q2 JSONL 兼容模式）？还是引外部工具（lnav/multitail）？
  → 推荐自带 PS 方案，零依赖、跨机器可复现、符合纪律。
- **D2 [task / AFK，较大] Q2 JSONL 实现范围**
  本次是否一并实现 Q2（改造所有 emit 站点 → JSONL）？还是只做观察层、Q2 留独立 ticket？
  → 推荐分开：观察层是 ~40 行小脚本即赢；Q2 是跨多服务的较大改造，单独排期。
- **D3 [grilling] start-joyai.ps1 是否改**
  保持 `Hidden`（进程组安全），观察与启动解耦？还是改成前台跑？
  → 推荐不改 Hidden。`tail_logs.ps1` 把「观察」从「启动」解开，正是为此。
- **D4 [research] 彩色 / 过滤选型**
  `Get-Content -Wait | ForEach-Object` 够不够？Q2 落地后 `ConvertFrom-Json | Format-Table` 够不够？
  → 内置够，不引外部；JSONL 模式只在 `logs/events/*.jsonl` 存在时启用。

## Out of scope（永不毕业）
- ELK / Loki / Grafana 等集中日志后端（本地 5 服务过度工程）
- 把文件日志全换成 stdout 集中（丢可追溯优势 + Windows 进程组风险）

## 推荐路径（若本会话动手）
1. 开 worktree（如 `wt-log-obs`）
2. 写 `scripts/tail_logs.ps1`（~40 行：tail `*.err.log`+`*.log`，按服务上色，`-Filter`/`-Since`，检测 `logs/events/*.jsonl` 时切 JSONL 彩色模式）
3. 自检（`-WhatIf` / 实际 tail 一个服务验证）
4. 交 review，**不擅自合**

## 导航师裁决（实话实说）
- **script-based 是不是问题？** 部分是。文件日志对「追溯/分析/对比」是**优势**，不该丢。真正缺的只是「实时观察层」。所以不是替换架构，而是**补一层**。
- **更好办法？** 你的 `tail_logs.ps1` 方向对。补强点：与 Q2 JSONL **互补不竞争**——Q2 是分析层，tail 是观察层，别用 Q2 替代 tail。
- **是否开 worktree？** 要。任何改码（新脚本 + 可能微调启动逻辑）都进 worktree，遵守纪律。
