# 工作区隔离规范（Workspace Isolation Standard）

> 目的：杜绝 agent / 构建工具把文件外溢到工作区以外的盘符（`D:/c` `D:/d` `D:/Cache` `D:/tmp`），
> 让 JoyAI-VL-Interaction 这一套系统的所有产物都收口到本仓库工作树内。

适用角色：所有操作本项目的对话 / agent（前端、后端、测试、code-review 等）。**本项目仅由 WorkBuddy 操作**，不引入其它 agent 框架。

---

## 1. 缓存收口（关键，杜绝复发）

所有构建 / 工具缓存必须落在 `<workspace>/.cache/`。两套机制配合：

### 1.1 会话内收口（脚本用）
dot-source 以下文件即可把 6 个缓存变量指向工作区：
```powershell
. .\.workbuddy\env\cache.env.ps1
```
覆盖变量：`HF_HOME` `HF_HUB_CACHE` `PIP_CACHE_DIR` `npm_config_cache`
`PLAYWRIGHT_BROWSERS_PATH` `UV_CACHE_DIR` `ELECTRON_CACHE`。

`start-joyai.ps1` 与 Playwright 回归脚本应 dot-source 本文件，确保浏览器 / 包缓存落在 `.cache/`。

### 1.2 永久收口（用户级环境变量）
首次配置时把上述 6 个**用户级**环境变量 `setx` 到工作区 `.cache/*`：
```powershell
setx HF_HOME                   "D:\AI\workspace\JoyAI-VL-Interaction-main\.cache\huggingface"
setx HF_HUB_CACHE             "D:\AI\workspace\JoyAI-VL-Interaction-main\.cache\huggingface\hub"
setx PIP_CACHE_DIR            "D:\AI\workspace\JoyAI-VL-Interaction-main\.cache\pip"
setx npm_config_cache         "D:\AI\workspace\JoyAI-VL-Interaction-main\.cache\npm"
setx PLAYWRIGHT_BROWSERS_PATH "D:\AI\workspace\JoyAI-VL-Interaction-main\.cache\playwright"
setx UV_CACHE_DIR             "D:\AI\workspace\JoyAI-VL-Interaction-main\.cache\uv"
setx ELECTRON_CACHE           "D:\AI\workspace\JoyAI-VL-Interaction-main\.cache\electron"
```
> 改前务必备份旧值（见 `reports/env-backup-20260723.txt` 或自行 `Get-EnvironmentVariable`），
> `setx` 仅改**用户级（User）**，非机器级，可逆。

---

## 2. agent 路径纪律（软规则）

1. **一律使用工作区绝对路径**。禁止依赖 `/tmp`、`D:/tmp`（git-bash 下 `/tmp` 解析为 `D:/tmp`）。
2. **草稿写工作区内**：一次性脚本 / 日志放 `.workbuddy/tmp/`（已被 `.gitignore` 的 `**/tmp/` 忽略），
   或需要留痕的放 `archive/agent-scratch-YYYYMMDD/`（入 VCS）。
3. **HOME 必须正确**：WorkBuddy HOME = `C:/Users/22186/.workbuddy`。若发现落到 `D:/c/...`，立即纠正，
   不要在那棵错位 HOME 下累积产物。
4. **多对话并发用独立 git worktree**，禁止共享同一工作树乱写（曾因此引发“共享工作树无声覆盖”事故）。

---

## 3. 看门狗

`scripts/guard-workspace-paths.ps1`（dry-run，绝不自动删）扫描四盘符是否再冒 Joy 文件：
```powershell
pwsh scripts/guard-workspace-paths.ps1      # 0=无命中, 1=发现外溢
```
建议接入本地定时任务或 CI 门禁，发现外溢即告警人工处理。

---

## 4. 清理历史外溢（2026-07-23 已执行）

- `D:/Cache/playwright` → 迁移到 `workspace/.cache/playwright`（回归继续可用）。
- `D:/Cache/{electron,npm,pip,uv,huggingface}` → 删除（包管理器缓存，可自动重生成）。
- `D:/tmp/*`（103 项 agent 草稿）→ 全部迁移到 `archive/agent-scratch-20260723/`（入 VCS，零丢失）。
- `D:/d/AI/{workspace,envs,tmp_ruff}` 与 `D:/d/tmp/{ruff69,ruff-check-venv,rv3}` → 删除（spillover / lint 临时）。
- `D:/c/Users/22186/.workbuddy` → 删除（错位 HOME，真实 HOME 在 `C:/Users/22186/.workbuddy`）。
