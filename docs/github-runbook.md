# GitHub 操作钉死手册（Runbook）

> **目的**：本项目在 GitHub / git 上踩过的所有坑，集中钉死成一份可检索参考。任何对话端（本端或其他端）要做 GitHub/git 操作前，**先读这份，不要重新踩坑、不要重新推导**。
> **维护纪律**：本文件是「GitHub/git 操作知识」的 SSOT。新增坑须附 **实证日期 + 根因 + 正确动作**；删旧换代时同步删旧。它与 `决策/`（架构/L1–L4 决策）互补但不重叠——决策讲"为什么这样设计"，本文件讲"怎么安全操作 git/GitHub"。
> **关联**：`docs/local-wiki-methodology.md`（测试资产钉死）、`决策/`（单源真值）、`~/.workbuddy/MEMORY.md`（操作硬约束指针）。

---

## 0. 总纲领（三句话）

1. **先验证再动手**：任何 git 操作前先 `git status --short` 探工作树；遇异常先确认文件是否真丢（`HEAD`/`origin` 是否还在），再决定动作。
2. **VPN 是前提**：GitHub 网络走用户 VPN 直连；VPN 断开立即停手并提醒用户，自己不要改代理。
3. **破坏性操作你（用户）来，或先给精确清单拍板**：`rm -rf` / `git reset --hard` / `git branch -D` / `git clean -fd` 等，agent 不擅自动。

---

## 1. 访问与网络（VPN / gh-proxy / 沙箱）

- ✅ 走用户 **VPN 直连 github.com**；沙箱内任何网络命令（含 `git push`/`gh`）须 `dangerouslyDisableSandbox:true`。
- ❌ **禁用 gh-proxy**：代理会顶掉 VPN，导致推送失败 / 错连。曾误记"有 gh-proxy `insteadOf` 规则"——核查 `.gitconfig` **无此规则**，旧 token-URL 绕路已作废。
- ⚠️ **VPN 断开 = 立即暂停并提醒用户**；不得自改 `.gitconfig` 代理 / `insteadOf`，不得重启 gh-proxy。
- 实证：2026-08-02 立；误记纠正 2026-08-02。

---

## 2. PAT / Token 权限

- ⚠️ **沙箱遮蔽 gh 凭据（重点坑）**：宿主 keyring 的 `gho_` token **本身带 `workflow` scope**（scopes 含 `gist, read:org, repo, workflow`）。但 **WorkBuddy Bash 沙箱下 `gh auth status` 会露出缺 `workflow` 的影子 OAuth token**——这是沙箱遮蔽宿主凭据造成的**误判**，并非真实缺 scope。
- ✅ 修法：**`dangerouslyDisableSandbox:true` 逃沙箱**后 `gh auth status` 即显示宿主 keyring 真实 token（含 workflow），直接 `git push` / `gh` 改 `.github/workflows/*` 即可成功。本会话改 `quality.yml` 直接 `git push`（带 sandbox 逃逸）即成功，无需 MCP 通道。
- ❌ **沙箱下 `gh auth status` 不可信**：遇 gh 凭据/网络权限（如 push 被拒、403）问题，**先逃沙箱复核 token scopes**，不要急着 `gh auth refresh -s workflow` 或走 MCP 绕路——那是基于误判的多余动作。
- fine-grained PAT 缺其它 scope 仍会静默失败 → 报错先看 scope，不是重试推送。
- 实证：2026-08-07（本会话核实，推翻 2026-08-01 / 2026-08-02 旧记）。

---

## 3. 行尾 CRLF 陷阱

- 症状：push 的 `*.sh` / `.yml` / Makefile / markdown 代码块在 GitHub runner（Linux）解析 `\r` 报错，CI 红。
- 根因：Windows 写盘默认 CRLF。
- ✅ 仓库 main 已含 `.gitattributes`（`* text=auto eol=lf` + 二进制豁免，PR #70 / 2026-08-02 合入）→ 检出强制 LF。但**已提交 blob 不回溯重归一化**（全仓 `--renormalize` 是独立大任务）。
- ✅ 本地编辑仍须自觉转 LF：Python 写文件用 `open(p,'wb').write(s.encode())` 或 `newline=''`；自检含 CRLF：`python -c "..."` 数 `b'\r\n'`。
- ❌ 不要依赖"提交后自动归一化"——旧 blob 仍是 CRLF。
- 实证：2026-08-02 立。

---

## 4. git 沙箱陷阱（文件静默丢失）

- `git stash` 会**丢 ref**（stash 静默丢引用）。
- `git checkout` / `merge` 会**静默丢文件**（曾出现 34 个文件 ` D`，gh 警告 "uncommitted changes"）——实际文件都在 HEAD 历史中、非有意改动。
- ✅ 还原：`git checkout HEAD -- <dir>`（**不** `reset --hard`）。
- ✅ **文件缺失先验证**：`git cat-file -e HEAD:<path>` / `git ls-files <path>` 确认是否真丢；多数只是 checkout/reset 静默丢，历史无损。
- 实证：2026-08-06 §4（`docs/startup-minimal-doc-fix` 合入时 34 文件误删，`checkout HEAD` 还原，无数据损失）。

---

## 5. worktree 陷阱

- 路径坑：`git worktree add` 用 **Windows 绝对路径 `D:/AI/...`**（勿 `/d/AI/...`，会畸形成 `D:/d/...`）。
- ref 不持久：Bash 沙箱跨调用 ref 可能不持久，但 loose object 留 `.git/objects`。
- 本地 ref 丢 → push 报 **refspec 不符** → 改推 `<sha>:refs/heads/<branch>`。
- 注册跨会话静默丢失：`git worktree list` 不列，但工作目录 + 指针仍在 → `git -C` 报 not a git repo。
  - 恢复：备份改动（二进制写回 LF）→ `rm -rf` 孤儿 → `git worktree prune` → `git worktree add <同路径> <branch>` → 拷回 → **精确 `git add` 具体文件**（禁 `git add -A`）。
- 本地验证：缺 node_modules 时从 main 软链跑 npm test/eslint，**提交前 `rm -f` 软链**。
- 实证：2026-08-01（路径坑 / 软链）、2026-08-03（注册丢失）。

---

## 6. 仓库被 agent 弄坏（read-tree --empty 清空 index）

- 症状：agent 跑 `git reset` / `read-tree --empty` → `.git/HEAD` 指坏分支 + index 空（`git ls-files`=0），整棵工作树被当未跟踪。
- ⚠️ **盲目 `git clean -fd` 会删光整棵树**——数据丢失级。
- ✅ 修复（不动未跟踪，先重建 tracked）：
  ```bash
  git symbolic-ref HEAD refs/heads/main
  git update-ref refs/heads/main origin/main
  git read-tree origin/main
  git checkout-index -f -a        # 重建 index + 工作树对齐 origin/main
  git clean -fd                   # 此时只删真正未跟踪残留
  ```
- 实证：2026-08-03 立。

---

## 7. CI 红了必须修到绿，禁止绕过

- 本项目仓库已 **开源 public**，使用 GitHub 免费 Linux runner，**不存在 runner 配额耗尽**问题；`steps:[]` 全 FAILURE 不是配额问题。
- CI 红 = **真实代码 defect**（lint / format / pytest / drift-gate 等门禁真失败），不是误报；必须**在本地复现并修复、跑绿本地门禁**后再推。
- ❌ 禁止 `gh pr merge --squash --admin` 这类 `--admin` 绕过门禁的路径；门禁红着绝不合入。
- ✅ 建议给 `main` 加 **branch protection**：required status checks 全绿才允许 merge，从机制上杜绝 `--admin` 绕过。
- ⚠️ **lint 工具版本对齐**：CI 用 `pip install ruff==0.15.22` 精确钉死（`.github/workflows/quality.yml:49`），本机也应保持 `ruff 0.15.22` 与其一致。若本地 ruff 版本 **高于** CI 钉的版本，新规则可能本地不报但 CI 报（本地过 ≠ CI 过）。PR 提交后**务必看 CI run 结果**，别盲目信任本机 lint。实证：2026-08-07（#96 收尾时曾误记"CI 钉 0.6.9"，实为 0.15.22，本机/CI 已一致——订正见此条）。
- 实证：2026-08-01 旧记"配额耗尽"已纠正——公开仓库无配额风险，CI 红即真实失败。

---

## 8. PR 合并

- 正常：`gh pr merge --squash`（需 reviewer 通过，且 **CI 门禁全绿**）。
- CI 红了先**本地复现并修复**，跑绿本地门禁（`scripts/quality-check.sh`）再推；修到绿才合。
- ❌ 绝不用 `gh pr merge --squash --admin` 这类 `--admin` 绕过门禁。
- 改 `.github/workflows/*` 须 `workflow` scope——宿主 token 本就带，沙箱下 `gh auth status` 误判缺（见 §2）。
- 实证：PR #53 / #54 / #78 / #87 / #88（旧记"CI 假红可 --admin 绕过"已纠正）。

---

## 9. verify-branch-merged 假阳性（三点 diff）

- 症状：用 `git diff A...B`（三点）判断"分支已合"会**假阳性**，导致开冗余 PR（5+ 个）。
- ✅ 改用两点 diff / `git merge-base` / `gh pr view` 确认真实未合状态。
- 实证：videcoding 反向研究报告候选 A（`verify-branch-merged` skill）。

---

## 10. push 失败两种常见病

- **force-push 卡死**：不要反复 force-push；先确认远程状态再决定。
- **`pull_request` 事件不触发 CI**：workflow `on:` 触发条件配置问题，不是代码问题；检查事件配置。
- 实证：07-20 ~ 07-23 一波 PR #10–#23 翻车循环（force-push 卡死 / CI 事件不触发 / gh-proxy 绕路 / fine-grained PAT 缺 scope）。

---

## 11. 缓存变量作用域铁律

- `npm_config_cache` / `HF_HOME` / `PIP_CACHE_DIR` / `PLAYWRIGHT_BROWSERS_PATH` / `UV_CACHE_DIR` / `ELECTRON_CACHE` 等**只能会话 / 进程级临时设**。
- ❌ 严禁写用户级持久 env（HKCU:\Environment / `setx`）——会跨工作区污染（hermes 事故）。
- HERMES_HOME 等由 `start-hermes-gateway.ps1` 钉死，JoyAI 端绝不碰。
- 实证：2026-08-02 立。

---

## 12. 工作区隔离（防多端互相踩）

- 单 canonical main worktree；并行开发用独立 worktree，改码只在本 worktree。
- ❌ 禁止本地 main 堆叠未推提交（新任务先 `worktree add` 或独立分支）。
- ⚠️ 子代理共享主工作树陷阱：Agent 子代理收尾若跑 `git reset --hard` / `git checkout -- .` / `git checkout -b`，会冲掉主理人**未提交**的本地编辑。
  - 防御：**未提交改动先 commit+push，或改用独立 worktree 隔离**，勿依赖共享树保留未提交编辑。
- 实证：2026-08-03（前端 agent 收尾重置冲掉 `决策/服务-webui.md` 的 D-2026-08-03-004 编辑，commit 落空后重做）。

---

## 13. 合并 / 审查 PR 前先刷新本地 tracking 引用（避免"PR 污染"假象）

- 症状：判断 PR 范围 / 是否"污染"时，看到分支相对 `origin/main` 多出一大串**早已合进 main 的历史提交**（如 40+ 提交、98 文件 diff），误以为 PR 混入了无关改动（如 webcam #77 等）。
- 根因：**本地 `origin/main` 跟踪引用过期**（停在远古 SHA）。此时 `git log/fetch/diff origin/main..HEAD` 会把 main 上**已合的历史**全当成"分支独有"列出——与 §9 三点 diff 假阳性**不同源**（三点 diff 是 merge-base 把已合提交当 diff；本项是本地 tracking ref 过期，两点 diff 也会被它骗）。
- ✅ 修法：**合 PR / 判断 PR 范围前，先 `git fetch origin` 刷新本地 tracking 引用**，再用两点 diff `origin/main..HEAD` 看真实增量（应只有本分支的 1~N 个提交）。
- ✅ 确认真实远端 main：`git ls-remote origin main` 看 SHA；用 `git merge-base --is-ancestor <远端SHA> HEAD` 确认"分支纯超前"还是"存在分叉"。
- ✅ `gh pr view <n>` / `gh pr diff` 始终以 GitHub 服务端真值为准，不被本地过期 ref 误导。
- 实证：2026-08-07（本会话 #96 审查组初报"混入了 webcam #77 等 40+ 提交"，实为本地 `origin/main` 停在 `606f44c` 过期；`git fetch` 后两点 diff 仅 `ca75e39` 一个提交、2 文件 +97，PR 干净）。

---

## 14. 速查表

| 要做 X | 先查 |
|---|---|
| push / 开 PR | VPN 开？`git status` 干净？refspec 对？ |
| 改 `.github/workflows/*` | 宿主 token 本带 `workflow`；沙箱下 `gh auth status` 误判缺 → 逃沙箱 `dangerouslyDisableSandbox:true` 再推（见 §2） |
| push `.sh` / `.yml` / Makefile | 转 LF 了吗（`.gitattributes` 会归一化新 blob） |
| 工作树异常（` D` / 全未跟踪） | `git ls-files` / `git cat-file -e HEAD:<path>` 确认真丢没 |
| 想 `git clean -fd` | index 空吗？空 = 先按 §6 重建 tracked，否则删光树 |
| 合并时 CI 全红 | = 真实失败，必须本地复现修绿再合，禁止 `--admin` 绕过 |
| 开新 PR 前 | 真没合？两点 diff 确认，别信三点 diff |
| 合 PR / 看 PR 范围 | 先 `git fetch` 刷新 `origin/main`；本地 trackref 过期会假报"PR 污染"，两点 diff 看真实增量 |

---

> 本手册随新坑持续追加。任何端发现新 GitHub/git 坑，回填此处并标注实证日期，避免下一端重蹈。
