# Handoff: pytest gate 顺序合并

**From**: 后端对话 (software-pytest-gate)
**To**: 测试对话
**Date**: 2026-07-23

## 背景
后端已把 `pytest` job 写进 `.github/workflows/quality.yml`（本地分支 `ci/add-pytest-gate`，已 commit 未推送），让 `memory-store`(16) + `background-agent`(7) 共 23 个测试进门禁，守住 [Local Wiki] 召回契约。

本地联调已验证：**23/23 全绿**（memory-store 16 + background-agent 7，Python 3.12 + `-o asyncio_mode=auto`）。YAML 解析校验通过（`matrix=[memory-store, background-agent]`，`fail-fast=false`）。

## 你的任务（测试对话）
按"测试交给测试对话"分工，background-agent 的 7 个测试由你方负责落地。它们目前在**未推送的本地分支** `test/hermes-api-enrich-glue`（commit `a6ab947`），含：
- `services/background-agent/tests/conftest.py`（把 `services/background-agent` 加 sys.path，使 `import hermes_api` 可用）
- `services/background-agent/tests/test_hermes_api_enrich.py`（7 个测试，覆盖 `_enrich_with_memory` 的 recall 契约：top_k=5 / min_score=0.4、有块返 `- {content}`、空块/4xx/网络异常/空问题均返 `""`、跳过无 content 块）

请：
1. 验证这 7 个测试（必要时补强），推送到 origin 并合并到 `main`。
2. 合并后通知后端对话。

## 合并顺序（用户已定：顺序合并）
1. 测试对话先把 `test/hermes-api-enrich-glue` 合并到 `main`。
2. 后端随后推送 `ci/add-pytest-gate`（仅 `quality.yml`）。

→ 这样 CI 全程无红门禁窗口，且守住"测试交给测试对话"的分工。

## 注意
- `background-agent` 的 `pyproject.toml` 无 `[tool.pytest.ini_options]`、无 dev extra，CI 已显式 `pip install pytest pytest-asyncio` + `-o asyncio_mode=auto`。
- `memory-store` 自带 `asyncio_mode=auto`，显式 `-o` 幂等无害。
- 将来接 Obsidian 等外部库时**必须守 recall 契约**（top_k=5 / min_score=0.4 / `limit=max(top_k,1)`），否则这 7 个测试会红——它们是真·契约守卫。
- `obsidian_backend.py` 目前是 `NotImplementedError` 桩（v0.3+ 才落地）。
- CI 装的是浮动最新版（fastapi/pydantic/uvicorn/httpx/pytest/pytest-asyncio 未锁版本），后续可锁版本。

## 测试对话完成 ✅（2026-07-23）

**背景修正（重要）**：动手前发现本地 `main` 已先 PR #12（`3ab7881`）合并，而 `test/hermes-api-enrich-glue` 仍基于旧的 `origin/main`(`96aba52`)——即 `6e32123`（jarvis-mode.md 路径引用修正）与 PR #12 内容**重复**。故两分支在 `96aba52` 分叉，**非快进**。

**操作**（独立 worktree `<workspace>/workspace/joyai-merge-wt`，未触碰根树 `ci/add-pytest-gate`）：
1. `git merge --no-ff test/hermes-api-enrich-glue`（ort 策略）→ 合并提交 `52a6cc6`。git 识别 `6e32123` 的 docs 改动已在 PR #12 落地，故**仅纳入 2 个测试文件**（`conftest.py` + `test_hermes_api_enrich.py`），无冲突、无重复 docs 改动。
2. 本地验证 7 测试：venv `D:\AI\envs\joyai-main\python.exe`（pytest 9.1.1 / pytest-asyncio 1.4.0 / py3.12，`-o asyncio_mode=auto`）→ **7 passed in 0.47s**（conftest 用 `Path(__file__).parents[1]` 插 `sys.path[0]`，绑定 worktree 内 `services/background-agent`，无 editable-install 陷阱；7 测全 mock `httpx.AsyncClient`，不需起 memory-store）。
3. 推送：`GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 git push https://x-access-token:$TOK@github.com/... main:main`（gh-proxy/GCM tty 走 token 直连旁路）→ `3ab7881..52a6cc6  main -> main`，**API 复核远端 HEAD=52a6cc6 一致**。
4. 清理 worktree；本地 `origin/main` ref 同步到 `52a6cc6`；根树 `ci/add-pytest-gate` 工作区（含未提交 `.gitignore` 改动 + 未跟踪文件）原封未动。

**结论**：background-agent 的 7 个 [Local Wiki] recall 契约测试已进 `main`。**后端对话现可推送 `ci/add-pytest-gate`**（仅 `quality.yml`），此时 `main` 已含 background-agent 测试，pytest job 的 `background-agent` 矩阵有测试可跑、不会因空矩阵非零退出而红——顺序合并目标达成。
