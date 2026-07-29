# 分支整洁度复核 — 2026-07-25

> 用户提问："你这个有分支没清干净吗验证"。本文为 git 实证的核查结论（非记忆推断）。

## 0. 验证方法
- `git worktree list` / `.git/worktrees/` 目录 — 看活 worktree。
- `git branch --merged main` — **不可靠**：本项目 PR 全 squash 合入，squash 不产生 merge commit，故 `--merged` 检测不到。
- `git cherry main <branch>` — 按 patch-ID 判落地。`-` = 已落（含 squash 单提交）；`+` = 未落 / 或多提交 squash 假阳性。
- `git merge-base --is-ancestor <sha> main` + `git diff main <branch>` — 对多提交分支做**确定性**判定。

## 1. 核心更正（记忆误差）
此前 MEMORY.md 记录 **"#36 已合 main(`d871616ac8`)" 为假**。

| 检查 | 结果 |
|---|---|
| main HEAD | `2be0779` (#34)，历史含 #32/#33/#34/#35 |
| `git merge-base --is-ancestor d871616ac8 main` | **NO** — d871616ac8 不是 main 祖先 |
| `git cat-file -t d871616ac8` | commit（孤立对象，存在但不入主线） |
| `git diff main feature/local-wiki-vector` | **18 文件 / +1760 行**不在 main |
| main 是否含 `services/memory-store/tools/seed_wiki.py` 等 | 否 |

**结论：#36 从未合入 main。** `feature/local-wiki-vector` 是一条带着真实实现的活分支。

## 2. feature/local-wiki-vector 内容（即用户要的"方案 C"）
基于 main(#34) 上两提交：
- `f14399c` feat(memory-store): [Local Wiki] semantic recall (ADR-0012) — USearch HNSW + bge-m3 dual-mode + namespace 隔离
- `a4ac926` ci(memory-store): install editable with [dev] extras (usearch/numpy) + fix format

真实文件（均未在 main）：`tools/seed_wiki.py`、`tools/fetch_wiki.py`、`tools/verify_embedding_parity.py`、`tests/test_embedder.py`、`tests/test_vector_index.py`、`tests/test_wiki_ingest.py`、`tests/test_wiki_sync_and_recall.py` 等。
⚠️ **这是实打实的活儿，禁止删除，待合入。**

## 3. 当前 worktree（4 个）
| Worktree | 分支 | 状态 | 处理建议 |
|---|---|---|---|
| `...-main` | main | HEAD #34 | — |
| `...-arch` | ci/batch2-flip | #35 已合(squash→d90570c)，clean | 安全移除 |
| `...-frontend-p0` | feature/frontend-p0 | #28 已合(a4493ab)，clean | 安全移除 |
| `...-local-wiki` | feature/local-wiki-vector | **#36 未合**，clean，含真实实现 | **保留，待合** |

后端 3 个 wt-backend-* 已于本日早些时候清理（worktree+本地分支+远端分支全清），无残留。

## 4. 悬空本地分支（无 worktree、基底不在 main = 废稿）
| 分支 | tip | 说明 |
|---|---|---|
| ci/lint-gate-batch2 | 593c93d | 基底 95c7c7/72bd0a3 不在 main，被 #31/#35 取代 |
| ci/lint-gate-batch3 | 31642f2 | 同上 |
| docs/lint-gate-adr0011-batch1 | 72bd0a3 | 同上 |

（`git cherry` 显示其提交均为 `+`，且共享基底 95c7c7/72bd0a3 经 `is-ancestor` 验证不在 main → 确为被取代的废弃稿。）

## 5. 远端 tokenpush/* 残留
**已合、可安全删（远端）：**
- tokenpush/fix/backend-batch2-groupA (c0cc897 `-`)
- tokenpush/fix/backend-f841-deadvar (5138965 `-`)
- tokenpush/fix/backend-p3-swallow-logging (5ecd6c4 `-`)
- tokenpush/ci/batch2-flip (`-`)

**未合 / 待定（勿动）：**
- tokenpush/feature/local-wiki-vector（镜像未合本地分支）
- tokenpush/fix/backend-p1-asr-kwstraining-s101、tokenpush/fix/backend-p1-hermes-webinfer、tokenpush/fix/backend-p1-kws-datamodule-b019、tokenpush/test/webinfer-context-overflow
- tokenpush/ci/lint-gate-batch2、tokenpush/docs/lint-gate-adr0011-batch1（废稿镜像）

## 6. 行动建议（按优先级，需用户拍板后执行）
1. **合 #36**（最高优先）：`feature/local-wiki-vector` 含 ADR-0012 真实实现，走 PR + squash 合 main。合后清其 worktree。
2. 清 2 个已合 worktree：`git worktree remove` arch / frontend-p0 + 删本地分支 ci/batch2-flip、feature/frontend-p0。
3. 删 3 个废稿本地分支：ci/lint-gate-batch2 / ci/lint-gate-batch3 / docs/lint-gate-adr0011-batch1。
4. 清 tokenpush 已合远端 4 个（token-URL + 临时 unset gh-proxy insteadOf，沿用已验证可靠流程）。

> ⚠️ 所有删除均破坏性，需用户确认后执行；feature/local-wiki-vector 在任何情况下都**不删**。
