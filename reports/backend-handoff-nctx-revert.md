# 后端交接：VLM n_ctx 运行态回退修复（4096 → 16384）

> **类型**：修改交接文档（action ticket），供后端角色执行
> **状态**：⏳ 待后端执行（来源会话明确「不修、不入会话记忆」，已移出）
> **交接日期**：2026-07-28
> **Owner**：后端 / DevOps（VLM 启动链路）
> **关联决策书**：`决策/drift-历史.md` DRIFT-1、`决策/服务-VLM.md` D-027、`决策/README.md` §4

---

## 1. 问题摘要

VLM（`:7060` llama.cpp / vLLM 主推理）**运行态** `n_ctx_slot` 回退到 `4096`，而**决策态**锁定为 `16384`。后果：图片 + 记忆 + Local Wiki 的字符输入直接溢出，用户实测 `[LLM error.]`。

- **决策态（锁死）**：`16384`，commit `4dd4fc3`（2026-07-13「v3.34: llama-server ctx 16384 + webinfer prompt guard」）将 `-c 4096 → 16384`
- **运行态（当前）**：`4096`，`logs/llama-main.log:14`（**2026-07-28 19:15** 启动）`n_ctx_slot = 4096`

> 结论：决策**没有漂移**，是运行态回退。详见 `决策/服务-VLM.md` D-021/D-027 与 `决策/业务-上下文架构.md`。

---

## 2. 证据（后端执行前可自验）

```bash
# 决策态：run-windows.env 锁 16384
grep -n "MAIN_CONTEXT" run-windows.env        # 期望: MAIN_CONTEXT=16384 / MAIN_CTX_TOKENS=16384

# 启动兜底逻辑：缺 MAIN_CONTEXT 时回退 4096
grep -n "MAIN_CONTEXT" start-joyai.ps1 run-windows.ps1   # 期望: 读取 $env:MAIN_CONTEXT；缺失→兜底 4096

# 运行态：当前实例实际 n_ctx
grep -n "n_ctx_slot" logs/llama-main.log      # 期望(坏): n_ctx_slot = 4096

# git 真值
git show 4dd4fc3 --stat | head                   # 期望: 含 -c 16384 改动
```

---

## 3. 根因

2026-07-28 19:15 那次启动进程的环境中 `MAIN_CONTEXT` 未生效（未 source / 未随启动脚本传入），走到 `run-windows.ps1:317` 的兜底分支 `4096`。等于决策值（env 写死 16384）与会话环境脱钩。

---

## 4. 修复步骤（交给后端执行）

**不要**在来源会话执行。由后端按高安全治理 + 用户「需手动」偏好手动跑：

```powershell
powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Restart llama-main
```

该命令会加载 `run-windows.env` → `MAIN_CONTEXT=16384` → 主推理以 `-c 16384` 重新拉起。

---

## 5. 验证（修复后必做）

```bash
# 重启后查新实例日志，确认 n_ctx_slot 回到 16384
grep -n "n_ctx_slot" logs/llama-main.log      # 期望(好): n_ctx_slot = 16384
# 端到端冒烟：让 Pilot 问一个带图片 + 记忆 + wiki 的长问题，确认不再 [LLM error.]
```

也可跑 `scripts/verify.sh` 看 n_ctx 相关项是否从 `DRIFT` 转 `PASS`。

---

## 6. 交接约束

- **不自动执行**：来源会话遵循「高安全治理 + 用户需手动」偏好，未擅自重启。本 ticket 同样**不自动执行**，等待后端在合适窗口手动跑。
- **不污染会话记忆**：本项已从来源会话日志移出，仅以本交接文档 + 决策书 DRIFT-1 为落盘真值。
- **修完后闭环**：后端执行并验证通过后，在 `决策/drift-历史.md` DRIFT-1 追加 `resolved: 日期｜by 后端｜verified: n_ctx_slot=16384`，并在 `决策/README.md` §4 对应项标已解决。
