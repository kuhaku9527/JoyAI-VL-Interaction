# 现状审查（架构端视角）— 2026-07-26

> 独立验证，与 `2026-07-26.md` 运营端日志交叉印证。结论：运营端记录准确，本端仅补架构判断。
> 真相源 = `gh` CLI + live GitHub（本地 `origin/main` ref 陈旧，不可信）。

## 1. 已核实真相（live）
- **`origin/main` HEAD = `9692d017`** = #36(语义召回 `d871616`) + #37(前端 F1-F4) 均 MERGED。
- **Open PR = 1**：仅 **#38** `feature/local-wiki-vector`（B1-B4 代理/health/settings + B9 金标评测）。
- **#38 `mergeable_state = dirty`（冲突，不可合）**。
- 远端分支干净：`main` / `ci/batch2-flip`(合残留) / `feat/wiki-frontend-f1-f4`(合残留) / `feature/local-wiki-vector`(#38)。**昨天标的 `tokenpush/*` 重复分支已清**。
- 本地 `main` 仍停 `d871616`（落后远端一个 #37，需 ff/pull）；主 worktree checkout 在 `feat/wiki-frontend-f1-f4` 未回 main。
- 本地 `feature/local-wiki-vector` tip=`a4ac926`，落后 #38 head `4660adee` 一个提交。

## 2. 唯一真实阻塞：#38 合并冲突
**根因（已定位）**：#38 分支三提交 `f14399c4 → a4ac926f → 4660adee`。
- `f14399c4` 的提交信息与 #36 的 `d871616` **逐字相同**（都是「USearch HNSW + bge-m3 语义召回」），内容即 #36 已合入 main 的那份实现。
- #38 重带了这份已合并代码 → 合 main 时 **13 文件冲突、8 个 add/add**（vector_index/wiki_service/wiki_ingest/embedder/models/test_* 等）。
- 这是**典型的「分支在 #36 合并前分叉、事后没 rebase」源码管理卫生问题**，不是架构缺陷。

**安全解开方案（推荐）**：
```bash
cd <local-wiki worktree>
git fetch origin main && git rebase -i origin/main
# 在交互列表里删掉 f14399c4 那一行，保留 a4ac926f + 4660adee
git push --force-with-lease origin feature/local-wiki-vector
# 重跑 quality gate → squash merge #38
```
- **为什么删 f14399c4 安全**：#36 已用完全相同的实现合入 main，dropping 不会丢代码，只去掉重复。
- **a4ac926f（ci dev extras: usearch/numpy）大概率仍唯一**（不属于 #36  feature 提交，也不属 #37 前端）→ 必须保留；rebase 时若它也与 main 撞，git 会显式报冲突，不会静默丢。
- 解冲突后 `#38 CI 未跑`（statusCheckRollup 空），须先过 quality gate 再合。

## 3. 架构完备性：ADR-0012 在 #38 合后完整
| 能力 | 落地 PR | 状态 |
|---|---|---|
| 语义召回核心（USearch HNSW + bge-m3 双栖 + namespace 隔离） | #36 | ✅ main |
| 前端 F1-F4 UI + webui 网关代理胶水 | #37 | ✅ main |
| NVIDIA bge-m3 provider + 每 provider 网络配置 + health/settings | #38 | ⏳ OPEN/冲突 |
| 金标召回评测（B9） | #38 | ⏳ OPEN/冲突 |

→ **#38 合入即 ADR-0012 全量收口**。唯一外部依赖 = 硅基流动 API 欠费（真机 parity 未验），非代码问题。

## 4. 待办 / 决策（均需用户授权，本端不擅动）
1. **授权 rebase + 合 #38**（最高优先，且是唯一真阻塞）。
2. 清理陈旧 `arch` worktree + 删远端 `ci/batch2-flip`、`feat/wiki-frontend-f1-f4`（均合残留）。
3. 本地 `main` ff 到 `9692d017` + 主 worktree 切回 `main`。
4. （运维，非架构）后端服务未起（llama/webinfer/asr/memory-store 全 free，仅 webui :8099 活），Local Wiki 端到端尚无法实测；拉起后 webui 须 `JOYAI_MEMORY_STORE_URL=:8997`（非默认 8996 空壳）。

## 5. 结论
架构层面 Local Wiki 设计已实质落地：**语义召回 + 命名空间隔离（`wiki:<游戏>`）+ 前端知识库 UI** 全部就位，无架构缺陷。剩余全是**源码管理卫生 + 1 个可机械解开的合并冲突**，不涉及重新设计。

> 经验：本项目 squash 合入频繁，`git branch --merged` 失效；多对话并发下「本地 ref 永远滞后」，任何分支状态判断必须以 `gh`/live GitHub 为准，绝不凭本地 `git` 推断。
