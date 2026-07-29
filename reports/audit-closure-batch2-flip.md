# 审计收口 — Batch 2 配置 flip 已合并 (PR #35)

**日期:** 2026-07-24 · **角色:** 架构对话（收口关键） · **状态:** ✅ 已完成并合并 main=`d90570c`

---

## 做了什么

执行 ADR-0011 **Batch 2 的 `select` 配置 flip** —— 把 5 个安全 lint 规则接入仓库门禁，
使已合并的 8 个后端 Batch2 PR 修复被**真正守护**，而不是合并后处于"休眠"状态
（不红 CI、也不被门禁拦截新违规）。

这是整个审计收口的**最后一块拼图**（用户原话："代码都就位了，独立可落"）。

## 改动清单

| 文件 | 改动 |
|------|------|
| `pyproject.toml` (root) | `select` 加 `S104 / S108 / S110 / S112 / S310` |
| `services/webui/pyproject.toml` | 同上（webui 有独立 `[tool.ruff]` 表，须同步 flip） |
| 17 个 `.py` 文件 | 内联 `# noqa` 标记，见下 |

**17 处 `# noqa` 实测分布**（ruff `--add-noqa` 自动落点）：
- `S104` ×4 — asr/tts 适配器 bind `0.0.0.0`（LAN 开发服务器， intentional）
- `S108` ×8 — `/tmp/models` + `/tmp/streaming_adapter_frames` 缓存路径（webinfer ×7, webui ×1）
- `S310` ×2 — `urllib` 开可信内网服务 URL（`scripts/verify-services.py`）
- `S110` ×3 — 测试文件 `try/except/pass`（intentional）
- `S112` ×0 — 规则已生效，当前无违规

**策略选择：** 用内联 `# noqa`（而非 `per-file-ignores`）—— 同一文件若以后新增同类违规，
门禁仍能抓到，不会因整文件豁免而被掩盖。何时可用 `# noqa` 的政策写进了 `select` 注释。

**B019 / B007 / F841 未显式加：** 它们本就在 `B` / `F` 家族中已被强制（自 day one 就在 `select`），
重复加是冗余，已在 config 注释说明。

## 验证（本地 pinned `ruff 0.15.22`）

跑**精确 CI 命令**（7 个 gated 目录各自的 `ruff check` + `ruff format --check`）：
**14/14 PASS**。全仓 `ruff check .` 的 629 处误差均来自 `datasets/`、`kws-training/`、`scripts/`
等 out-of-scope 装饰债（CI 不扫这些目录），与本次改动无关。

## 合并路径

`ci/batch2-flip` 分支 → commit `72861d8` → **PR #35** →
CI 双跑（`30074631951` PR 触发 + `30074642883` workflow_dispatch 兜底）均 **success** →
REST `PUT /pulls/35/merge` squash 合 **main=`d90570c`**（2026-07-24 ~15:12Z）。

推送走 token-URL（`x-access-token:$TOKEN@github.com/...`），因 userinfo 不匹配
gh-proxy 的 `insteadOf` 前缀，自然绕过代理，无需改本地 git config。

## 审计收口状态

- **9 个审计 PR（#24–#31 + #35）全部合并**。Batch 2 后端修复现被门禁守护（不再休眠）。
- 范围外：**#32 / #33 / #34** 为 test/frontend 对话的 open PR（hermes 回归守卫 / regression 守卫 /
  frontend-test job），不在本审计范围，按隔离纪律未触碰。

## 唯一剩余已知缺口（非审计收口阻塞）

**ITEM B — `quality.yml` 无 `frontend-test` job：** #28 合并的 25 个 Vitest 用例不在 CI 跑，
测试无人守。补 job 须 **fine-grained PAT (workflow scope)** 推 workflow 文件
（OAuth `gho_` 被 GitHub 硬拒），归测试对话推进，且非本次"收口最后拼图"所指范围。
