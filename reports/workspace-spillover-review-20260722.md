# 工作区外溢审查 & 防外溢修改方案

日期：2026-07-22 ｜ 角色：code-review（仅产出方案，不执行破坏性移动）

## 1. 确认：全部是 Joy/WorkBuddy 产物，无个人数据 ✅

| 位置 | 内容 | 体量 | 判定 | 泄漏来源 |
|---|---|---|---|---|
| `D:/c/Users/<user>/.workbuddy` | `binaries/python`（managed runtime 骨架） | ~36K | WorkBuddy HOME 错配 | 某会话 HOME 被解析成 `D:/c/Users/<user>` |
| `D:/d/AI/workspace/JoyAI-VL-Interaction-main` | 仅空 `services/`，**无 .git** | 36K | 错误路径的残缺 clone 壳 | 某 agent 把基准写成 `D:/d` 再拼 `/AI` |
| `D:/d/AI/envs/ruff-migrate` | ruff 迁移 venv | 13M | lint 工作副产物 | code-review 对话 |
| `D:/d/AI/tmp_ruff` | ruff 0.15.22 安装 | 小 | lint 工作副产物 | code-review 对话 |
| `D:/d/tmp` | `ruff69` / `ruff-check-venv` / `rv3` | 小 | lint 临时 | code-review 对话 |
| `D:/Cache/*` | electron / npm / pip / playwright / uv / huggingface 缓存 | **~1.9GB** | 工具缓存被重定向 | `HF_HUB_CACHE`/`PIP_CACHE_DIR`/npm/playwright/uv 指向 `D:/Cache` |
| `D:/tmp/*` | `patch_*.py` `fix_*.py` `block5-*.cjs` `mcp_verify.py` `p0-pr-body.md` `*.png` `codebuddy` `joyai-ms2` `joyai-shots` | 散 | agent 临时脚本/截图 | 多对话把 `/tmp` 当草稿盘（git-bash `/tmp` → `D:/tmp`） |

**重要排除项**：未发现任何个人文件（无 `Documents`/`Desktop`/`Pictures`/照片/其他项目源码）。`D:/c/Users/<user>/.workbuddy` 只是错位的工作目录，不是真实用户档案。`D:/d/AI/workspace/...` 是空壳（无 `.git`、仅 2 个顶层条目）。**全部判定为 Joy/WorkBuddy 相关，可安全清理。**

## 2. 外溢根因（4 条泄漏通道）

1. **HOME 错配**：WorkBuddy 在某会话中 `HOME` 被解析到 `D:/c/Users/<user>`，managed python runtime 落到那里。
2. **缓存重定向**：HF/npm/pip/playwright/uv 的 cache 环境变量指向 `D:/Cache`，累计 ~1.9GB，且随项目漂移。
3. **`/tmp` 草稿盘**：多个对话把临时脚本/截图写到 `/tmp`，git-bash 下 `/tmp` 解析为 `D:/tmp`，全部外溢到系统盘根。
4. **基路径写错**：`D:/d/AI` 是某 agent 把基准路径写成 `D:/d` 再拼 `/AI`（或相对 `d/AI`）生成了第二份残缺 AI 工具链目录。

叠加既有「共享工作树」事故（并发 `git checkout` 互相覆盖），多对话在同一棵树并发写放大了外溢面。

## 3. 修改方案（防外溢 + 单一管控 = 仅 WorkBuddy）

### 3.1 锁定缓存与 HOME（根因 1/2 的硬修复）
新增 `<workspace>/.workbuddy/env/cache.env.ps1`，WorkBuddy 启动前 source，把全部缓存收口到 `<workspace>/.cache/`：

```powershell
$root = "<workspace>/workspace/JoyAI-VL-Interaction-main"
$env:HF_HOME                  = "$root/.cache/huggingface"
$env:PIP_CACHE_DIR            = "$root/.cache/pip"
$env:npm_config_cache         = "$root/.cache/npm"
$env:PLAYWRIGHT_BROWSERS_PATH = "$root/.cache/playwright"
$env:UV_CACHE_DIR             = "$root/.cache/uv"
$env:ELECTRON_CACHE           = "$root/.cache/electron"
```

- `.cache/` 加入 `.gitignore`。
- 确认 WorkBuddy `HOME` 回到 `C:/Users/<user>/.workbuddy`（删掉 `D:/c` 那份错位 HOME）。
- 效果：`D:/Cache` 停止增长，1.9GB 可回收。

### 3.2 Agent 路径纪律（根因 3/4 的软修复）
写入 `doc/standards/workspace-isolation.md`（或并入 `code-review-checklist.md`）：

- 一律用**绝对工作区路径**；禁止 `/tmp`、禁止相对 `d/...`、禁止未确认 `$HOME`。
- 草稿/临时一律写 `<workspace>/.workbuddy/tmp/`（gitignored），不碰系统 `/tmp`。
- 多对话协作时，每个对话用**独立 git worktree**（已记教训），不在共享树并发写。

### 3.3 单一管控（「就 workbuddy」）
- 项目声明为 **WorkBuddy-only**：除 WorkBuddy 外无其他 AI agent 触碰本仓。
- code-review 对话作为协调者，跨对话任务经 `reports/*.md` handoff，不跨对话直接改码（既有约定）。
- 加**防外溢看门狗**：`scripts/guard-workspace-paths.ps1`（默认 dry-run），扫描 `D:/c` `D:/d` `D:/Cache` `D:/tmp` 是否出现新的 Joy 相关文件，有则告警（不自动删）。

### 3.4 既有外溢的安全清理（即你最初要求的「安全移动至工作区」）
> ⚠️ 按个人文件安全规则，**每步删除/移动前必须列出清单并获你确认**。分阶段执行：

- **P1 缓存（可重生成，最安全）**：`D:/Cache/*` → 重指后直接删（`rmdir /s`），或先移入 `<workspace>/.cache/` 复用。
- **P2 Agent 草稿（`D:/tmp`）**：`patch_*`/`fix_*`/`block5-*.cjs`/`mcp_verify.py`/`p0-pr-body.md`/`joyai-*` 等 → 归档到 `<workspace>/.workbuddy/archive/agent-scratch-20260722/`，确认后再删原文件；`*.png` 截图同归档或删。
- **P3 残缺副本（`D:/d/AI`）**：`workspace/JoyAI-VL-Interaction-main`（空壳、无 .git）、`envs/ruff-migrate`、`tmp_ruff` → 确认无价值后删。
- **P4 错位 HOME（`D:/c`）**：`D:/c/Users/<user>/.workbuddy` → 确认真实 HOME 正常后删 `D:/c` 整棵。

## 4. 待你确认

1. 是否认可「全部 Joy 相关、可清理」的结论？
2. 防外溢配置（3.1 / 3.2）属纯新增、无破坏性，是否现在落地（建 `cache.env.ps1`、`.gitignore` 追加、写 `workspace-isolation.md`）？
3. 既有清理执行顺序：先 P1（缓存，最安全）还是整批推进？**每步我都会先列出文件清单再等你 confirm，绝不静默删除。**
