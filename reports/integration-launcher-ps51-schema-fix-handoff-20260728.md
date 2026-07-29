# 跟进文档：Launcher PS 5.1 修复 + memory-store schema 迁移修复（2026-07-28）

> 用途：本文件是后端/Hermes 对话的**真相源快照**。后续任何对话谈"launcher 修复 / schema 迁移 / 起服务验证"时，先读这份，别凭记忆或过长上下文推断。
> 关联对话域：后端记忆 / Hermes 桥接优化（本对话归属域）。

## 0. 一句话结论
两个 bug 都已**运行时真验通过**，并各自独立成 PR（刻意解耦，便于 review/回滚）：
- **PR #40** — memory-store schema 迁移幂等（**已合 main=47cfa58**，CI 全绿）
- **PR #41** — `run-windows.ps1` 的 PS 5.1 `ProcessStartInfo.EnvironmentVariables` NullArray 崩溃（**已合 main=52fcbb8**）

## 1. PR #41：Launcher PS 5.1 修复（本会话交付）
- **分支**：`fix/run-windows-ps51-env-inherit`（从 `main` c91b22c 拉出，仅 1 文件改动）
- **commit**：`c0fc916` — `fix(launcher): avoid PS 5.1 NullArray on ProcessStartInfo.EnvironmentVariables`
- **改动**：`services/scripts/run-windows.ps1` `Start-Background` 内，把 `$psi.Environment[$k] = ...` 改为 `[Environment]::SetEnvironmentVariable($k, $v)`（6 插入 / 1 删除）
- **根因**：本机 PS 5.1.19041 / .NET 下 `ProcessStartInfo.EnvironmentVariables`（非泛型 StringDictionary）首次访问 getter 返回 `$null`，索引器 SET 必抛 `Cannot index into a null array`。原 launcher 在 spawn 第一个服务（llama-main）时就崩，**任何服务都起不来**。
- **修复原理**：`[Environment]::SetEnvironmentVariable` 写入当前进程环境；子进程以 `UseShellExecute=$false` 启动继承父环境块（Windows 铁律），注入值仍传到被拉服务（含 webui 的 `JOYAI_MEMORY_STORE_URL`）。
- **验证**：本机 PS `5.1.19041` 实测 `run-windows.ps1 -Mode minimal` + `JOYAI_ENABLE_MEMORY_STORE=1` 顺利 spawn llama-main，**不再抛 NullArray**（修复前正是在此步崩）。
- **状态**：PR #41 已开，待 CI + review。

## 2. PR #40：memory-store schema 迁移幂等（先前交付，状态未变）
- **分支**：`fix/memory-store-schema-migrate-idempotent`（工作树已还原干净，仅 d716363 一个 commit）
- **改动**：`services/memory-store/.../sqlite_backend.py` 删 `_SCHEMA` 两行冗余 namespace 索引，让 `_migrate` 在 ALTER 加列后建索引 → 旧库（无 namespace 列）迁移幂等。
- **验证（金标准运行时）**：构造真实旧库（`memory_blocks` 无 namespace 列）→ 独立拉 memory-store → import 即迁移不崩 → `/health` HTTP 200 `{"ok":true,"blocks":2}` → 迁移后补齐 4 列、2 条 legacy 数据零丢失。
- **CI**：PR #40 已开，pytest 61 passed/6 skipped + ruff 全绿（run 30320631554, 7 job SUCCESS）。
- **状态**：CI 绿，**待用户授权合 main**（合后可顺手更新《交叉验证与各端方案-20260727.md》§1.1/§2.1 陈旧 GitHub 状态表）。

## 3. 起服务验证时的关键发现（防误判）
- **VLM(llama-main) "exited before ready" 是假警报**：模型 GGUF 实际存在（`D:\AI\models\main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\`，4.79GB），用正确 Windows 路径 `D:/AI/...` 能正常加载到 "warming up the model"。第一次 bash 探针报 `No such file` 是我误用 `/d/AI/...` POSIX 路径、Windows 原生 exe 不认所致，**不是模型缺失、也不是代码问题**。重新拉带修复的 launcher 时 VLM 应能起来（GPU 识别正常：RTX 5060 Ti 16GB）。
- **另发现本机 PS 5.1 还有 `Start-Process` 因 `Path`/`PATH` 大小写重复键直接抛异常的坑**，与本次修复无关（项目 launcher 用 `New-Object Process` 不受影响）。

## 4. 启动纪律（固化，跨对话必须遵守）
- **绝不用** `D:/tmp/start-stack.sh`（setsid 致后端 abort + 违反工作区隔离纪律）。
- 用项目自带脚本：`start-joyai.ps1` 或 `powershell -ExecutionPolicy Bypass -File services\scripts\run-windows.ps1 -Mode minimal`。
- webui 连 memory-store 地址**必须显式设对**：默认 8996 是废弃空壳，要 `JOYAI_MEMORY_STORE_URL=http://127.0.0.1:8997`；memory-store 端口由 `MEMORY_PORT`（默认 8996→改 8997）控制，且仅当 `JOYAI_ENABLE_MEMORY_STORE=1` 才拉起。
- venv = `D:\AI\envs\joyai-main\python.exe`（非 `services/.venv`）。

## 5. 待办（未授权不动）
- ~~PR #40 合 main~~ **已合 main=47cfa58**（squash）。
- ~~PR #41 走 CI + review 后合 main~~ **已合 main=52fcbb8**（squash）。
- `app.py` 导入时即连默认 `./data/memory.sqlite` 的副作用（code-reviewer nit，测试性 follow-up）→ 可延迟到 lifespan/首请求。

## 6. Git 操作踩坑备忘（gh-proxy 环境）
- 本机 `insteadOf` 在 **local + global 两层**都有，键名是**小写 `insteadof`**。清 local 时若写成 `insteadOf`（大写 O）会静默不匹配 → 远程永远被改写回 gh-proxy，gh 不认 GitHub host。
- 正确流程：`git config --local/global --unset-all 'url.https://gh-proxy.com/https://github.com/.insteadof'`（两个层级都要清）→ `git remote set-url origin https://github.com/...` → `gh pr create`（无 `--repo`，避免某 gh 版本的 GraphQL fragment bug）→ 还原两层 insteadOf + remote 回 gh-proxy。
- 直连 `github.com` 的 git 协议会被 reset（走 gh-proxy 才行）；但 `gh` API（api.github.com）在远程指向 github.com 时正常。

## 7. 2026-07-28 下午更新：两 PR 已合 + CPU 真机 wiki 实建（防偏移）
- **状态收口**：#40/#41 均已 squash 合 main，**main=`52fcbb8`**，与 origin/main 同步，工作树干净。
- **CPU 真机 wiki 建立（本次新做）**：把真实源 `.workbuddy/tmp/wiki-acceptance-corpus/`（3 个 elden-ring md）经 HTTP `POST /v1/external/sync` 建进 `data/`：
  - 入口：`python -m memory_store.app`（joyai-main venv，torch 2.13.0+cpu + st 5.6.1）+ env `MEMORY_PORT=8997 MEMORY_SQLITE_PATH=data/memory.sqlite MEMORY_VEC_DIR=data/vec MEMORY_BACKEND=sqlite EMBEDDING_PROVIDER=local EMBEDDING_LOCAL_MODEL=D:/AI/models/bge-m3`，`PYTHONPATH=services/memory-store/src`。
  - 建库 `{namespace:"wiki:elden-ring", dir:"D:/AI/workspace/.../wiki-acceptance-corpus", drop_first:true}` → `files:3, chunks:3, embedded:3, dropped:true, errors:[]`。
  - 落盘：`data/memory.sqlite` 3 行 + `data/vec/wiki-elden-ring.usearch`（12832 bytes）。
  - 端到端离线 recall（Python urllib 显式 UTF-8）：ASCII/中文查询均 200、3 block 命中 score 1.0。
  - ⚠️ curl 在 git-bash 传中文 JSON 报 422 "parsing the body" 是**编码坑、非代码 bug**（用 urllib 发即可）；dir 必须 Windows 原生路径 `D:/...`。
- **补 .gitignore 漏洞**：新增 `*.usearch`（紧跟 `*.db`），避免建库侧车被 `git add -A` 误提交。当前唯一 tracked 改动 = `.gitignore`(M)，未提交（用户控提交）。
