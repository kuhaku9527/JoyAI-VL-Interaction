# CI / 格式门禁诊断 — 2026-08-01

> 审查组落盘产物。背景：上一轮诊断怀疑 `ci/*` 分支的 CI 红是"门禁过严"，
> 计划拉真实 CI 日志核实；本轮核实发现分支已不存在，并顺带定位到 main 自身的格式门禁问题。

## 1. 远程分支现状（核实 B 路径）

- `git remote -v` 走 `gh-proxy.com` 中转；`gh` CLI 已登录 `kuhaku9527`（token 含 `repo`）。
- `gh api repos/.../branches` 返回远程**仅 `main` 一个分支**。
- 此前提到的 `ci/*` 那批分支（约 13 个）**已不在远程**——要么合并、要么被清理。
- 结论：**"拉 CI 日志看 ci/* 分支红因"这条路已无意义**（无分支可查）。
  上一轮"那些红是分支自身改动导致、非门禁过严"的判断，仍是最终结论，但无可再验证的实时日志。

## 2. CI 格式门禁的真实范围（读 quality.yml 确认，非凭记忆）

`quality.yml` 的 `ruff` job **按服务目录分 scope** 跑 `ruff format --check`，不是全仓：

| scope | 命令 |
|---|---|
| services/webinfer | `ruff format --check services/webinfer` |
| services/webui (Python) | `ruff format --check .`（working-dir=services/webui） |
| services/memory-store / voice-clone / asr / tts / background-agent | 同上各自目录 |

- 全仓 `ruff format --check .` 会扫到 scripts/、install/ 等 **scope 外**文件（约 21 个"需重排"），但 CI **不查**这些，属噪音。
- 关键：CI 用**钉死的 `ruff==0.15.22`**。

## 3. 发现：main 自身有 6 个文件过不了格式门禁

用 `git show HEAD:<file> | ruff format --check`（提交态）核实，CI scope 内：

- `services/webinfer`：**5 个文件**会被重排 → 该 scope 的 `ruff format --check` 在 main 上**红**
  - `memory_io.py`、`memory_store_client.py`、3 个 `tests/*.py`
- `services/webui`：**1 个文件**会被重排 → 该 scope 在 main 上**红**
  - `src/joy_interaction_webui/server.py`（Codex 加的 access-log 代码）

其余 CI scope 内文件全部通过；问题严格限定在这 6 个文件。

## 4. 修复

- 对这 6 个文件执行 `ruff format`（**仅格式重排，无逻辑改动**）。
- 恢复后验证：`ruff format --check services/webinfer` → 34 files formatted；
  `services/webui` → 42 files formatted（两个 scope 全绿）。
- 已提交为 `d1631f0`（style: ruff format — fix webinfer/webui format-check failures）。

## 5. 结论与遗留

- **门禁不是"过严"**：它正确地拦下了提交态里 6 个未格式化的文件。这反而是门禁在工作的证据。
- 之前 `ci/*` 分支的红，与本次 main 的格式漂移是**两件事**：前者是分支自身改动问题（已随分支清理消失），后者是 main 上长期存在的格式债务，现已修。
- 遗留：`scripts/`、`install/` 等 scope 外文件仍有格式漂移（约 21 个），但 CI 不查，暂不处理；若日后要把格式门禁扩到全仓，需先做一轮全仓 `ruff format`。
- 待办：3 个本地提交（含本修复）尚未推到 `origin/main`，需走 push 或开 PR 评审。
