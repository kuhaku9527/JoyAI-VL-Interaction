# 合并完成报告 — JoyAI-VL-Interaction (2026-07-22)

## 结论

两个待合并 PR 已成功合并进 `origin/main`，源码级验证全部通过。

| PR | 标题 | 合并提交 | 合并时间 (UTC) |
|----|------|----------|----------------|
| #3 | fix(webui): 修复 modelSelect/apiBaseUrl/apiKey 陈旧引用 + 接入 Reset Session | `51e790d` | 2026-07-22T04:15:36Z |
| #2 | fix(webinfer): P0 正确性修复 (#2/#3/#4) | `bbf8b61` | 2026-07-22T04:15:39Z |

合并后 `origin/main` HEAD = `bbf8b61`。PR #2 head `2d53508` 与 PR #3 head `029370c` 均已确认为 `origin/main` 的祖先（可达）。

## 合并前的预处理

- **PR #2 base 重定向**：原 base 为 `milestone2-adapter-core-split`（该分支已随 PR #1 合并进 main）。先用 `gh pr edit 2 --base main` 重定向到 `main`，避免合进已废弃分支。
- **冲突预检（破坏性前先试）**：在临时分支 `_merge_test` 上对 `origin/main` 分别做 `git merge --no-commit --no-ff` 试合并：
  - PR #3（改 `index.html`）：rc=0，无冲突文件。
  - PR #2（改 `services/webinfer/*` + `doc/`）：rc=0，无冲突文件。
  - 试合并均 `--abort` 回滚，工作树未受污染。

## 合并后源码验证（在 `origin/main` 上直接 `git show` 抽查）

- `services/webinfer/memory_io.py` ✅：`_memory_warmed` 已是 `asyncio.Event`，填充后置 `.set()`，多处用 `.is_set()` 守卫（#4 并发竞态修复落地）。
- `services/webinfer/response_format.py` ✅：`parse_model_decision` 检测 `<delegation>`/`</delegation>` **任意位置**即判 delegation，覆盖真实 `</response>…</delegation>` 格式（#2 决策解析统一修复落地）。
- `services/webui/.../index.html` ✅：`processEvery`/`framesPerBatch` 两 `<input>` 已恢复；`apiKeyField && apiKeyToggle` 守卫；`resetSessionBtn` 已接线（PR #3 修复落地）。
- 回归测试 ✅：`test_decision_parser_regression.py` / `test_live_adapter_memory_hooks.py` / `test_video_chat_endpoint.py` 均在合并后 main 中。

## 残留事项 / 注意点

1. **本地 `main` 仍陈旧**：本地 `main` 停在 `a7328c8`，需 `git fetch` + `git branch -f main origin/main` 才能对齐远程（不影响远程，仅本机引用滞后）。
2. **CI 门禁未恢复**：`quality.yml` 的 package-smoke CI gate 此前因 workflow scope 受限被摘掉，若需 CI 卡质量需另开 PR（与本次合并无关）。
3. **后续回归建议**：合并已完成且前端 PR #3 已在 `029370c` 经测试对话 Playwright 验收（①②③④⑤ 全 PASS，9 项尺子 7/9 仅因 7060 关机环境阻断）。建议测试对话再对合并后的 `main` 跑一次 `services/webinfer/tests/` 的 P0 回归套件（含 #2/#4 新测试），确认跨分支合并未引入回归。

## 分支状态一览（合并后）

- `main` → `bbf8b61`（含 milestone2 + PR #2 + PR #3）
- `fix/adapter-p0-correctness`、`fix/webui-live-refs`：已合并，远端分支保留（未删除，便于追溯）
- `feature/memory-store-v02-hooks`：未参与本次合并，仍独立演进
- 本地备份分支 `backup/*` 保留完好

## 合并态 P0 回归验证（测试对话执行，2026-07-22）

- **目标**：确认跨分支合并（milestone2 + PR #2 P0 #2/#3/#4 + 前端 PR #3）未引入 webinfer 后端回归。前端 PR #3 已在 `029370c` 经 Playwright 全验收，按建议不重测。
- **陷阱规避（关键）**：`joyvl-webinfer-adapter` 以可编辑模式安装、指向**主工作树** `services/webinfer`（`import adapter_core` 等会解析到主树旧代码）。若在主工作树或普通 worktree 直接跑 pytest，测的并非合并态。对策：建独立 worktree `D:/tmp/joyai-main-merged`（from `bbf8b61`），并从 worktree 内 `services/webinfer` 目录运行 `python -m pytest`（cwd 成为 sys.path[0]），导入验证 `adapter_core`/`memory_io`/`response_format`/`prompt_constants` 的 `__file__` 均指向 worktree 合并态代码。
- **结果**：`services/webinfer/tests/` → **93 passed in 2.01s**（与 PR #2 特性分支 86+7=93 一致）。含 #2 决策解析（`test_decision_parser_regression.py` / `test_video_chat_endpoint.py`）+ #4 并发竞态（`test_live_adapter_memory_hooks.py`）新测试。
- **结论**：合并后 `main` 后端零回归。合并质量三层验证（源码抽查 + 逐行复审 + 合并态运行时回归）一致全绿。worktree 已清理（`git worktree remove` + prune，物理 dir 删除），未启动任何服务、未占显存，共享工作树未触碰。
