# 决策书（JoyAI-VL-Interaction 项目真值源）

> 本目录是项目**已确定决策的真值源**（"下锤的事实清单"）。AI 跨会话不丢决策的落盘点。
> 配套溯源证据：`.workbuddy/tmp/decision-trace/`（git-log / trace-*/ / decision-inventory.md，防上下文压缩的工作区）。

---

## §0 修改治理协议（最高优先级，强制）

1. **任何条目增删改必须走流程**：① AI 提出具体改动（reason + 建议日期 + 证据）→ ② 用户明确同意 → ③ 才落盘，并在条目末追加 `modified: 日期｜by AI｜approved: 用户`。
2. **🔒 锁死条目**：除治理流程外禁止改动。🔓 软锁条目（标 `待 #XX`）同样走流程，但允许在对应 PR 合入后由 AI 提议关闭。
3. **冲突裁决**：本目录与 `MEMORY.md`/记忆冲突时，**以本目录为准**；反向修正记忆。
4. **本轮（2026-07-28 召回轮）特许**：用户明确"这一版不用我确定、人工逐条确认不现实"，故本轮全量细分撰写**由 AI 直接落盘**（不起子代理、逐条 git/代码核实）。此后任何修改恢复 §0.1 流程。
5. **生产路由（防多端污染）**：各端对话**只写 spec+adr 文件，绝不读其他端对话**——ADR 落 `doc/adr/`，spec 落 `doc/specs/`。**唯一写者=审查组对话**：由用户手动触发，召回 `doc/specs/`+`doc/adr/` 交叉验证（git + 代码 + spec/adr + 日期记忆）后汇编成本目录条目**提案**，按 §0.1 经用户批准才落盘。端点仍须读本目录(SSOT) 但不得互读对话。

---

## §1 召回方法论（2026-07-28 确立，防再漂移）

- **亲力亲为，不起子代理**：子代理会被压缩且无权写盘，不能委托决策。本轮所有 git/代码/记忆核实由主理人直接执行。
- **三源交叉验证**：每条决策日期取自 **git 提交时间**（最权威）＋**ADR/报告原文 Date 字段**＋**代码注释/日志**；运行态与决策态**分开记**。
- **运行态 ≠ 决策态**：配置/启动逻辑写死的值（决策态）与当前进程实际值（运行态）可能背离，凡背离记入 `Drift` 列，不污染决策日。
- **真实溯源日**：`D-YYYY-MM-DD-NNN` 的日期 = 该决策**实际确立或合入日**，不是文档撰写日。git 历史最早仅到 `d75faf6`（2026-07-13 整体快照），早于该日的项标注 `(下限)`。
- **对话记录召回局限**：`conversation_search` 本用户历史索引返回 0（5 次查询均空），跨会话对话内容已沉淀于 `分析/`、`reports/`、`MEMORY.md`、每日日志，本轮已采纳并交叉验证。

---

## §2 文件索引（按 L1-L4 细分）

| 层 | 文件 | 覆盖 D-id | 状态 |
|---|---|---|---|
| L1 | [`启动链路.md`](启动链路.md) | D-001~008 | ✅ 细分 |
| L4 | [`跨域铁律.md`](跨域铁律.md) | D-001~015 | ✅ 细分 |
| L4 | [`AI代码质量约法三章.md`](AI代码质量约法三章.md) | 非 D 编号铁律(2026-08-03) | ✅ 新增 |
| L2 | [`服务-VLM.md`](服务-VLM.md) | D-020/021/022/050 | ✅ |
| L2 | [`服务-webinfer.md`](服务-webinfer.md) | D-023~033 | ✅ |
| L2 | [`服务-webui.md`](服务-webui.md) | D-032~039 | ✅ |
| L2 | [`服务-日志.md`](服务-日志.md) | D-060~062 | ✅ |
| L2 | [`服务-memory-store.md`](服务-memory-store.md) | D-040~044 | ✅ |
| L2 | [`服务-语音栈.md`](服务-语音栈.md) | D-045~047 | ✅ |
| L2 | [`服务-Hermes.md`](服务-Hermes.md) | D-048 | ✅ |
| L2 | [`服务-background-agent.md`](服务-background-agent.md) | D-049 | ✅ |
| L3 | [`业务-LocalWiki.md`](业务-LocalWiki.md) | D-060~074 | ✅ |
| L3 | [`业务-决策记忆.md`](业务-决策记忆.md) | D-075/076 | ✅ |
| L3 | [`业务-审计收口.md`](业务-审计收口.md) | D-077/078 | ✅ |
| L3 | [`业务-上下文架构.md`](业务-上下文架构.md) | D-079/080 | ✅ |
| L3 | [`业务-评测.md`](业务-评测.md) | D-081 | ✅ |
| L4 | [`模型与权重.md`](模型与权重.md) | D-011/012 | ✅ |
| L4 | [`工程规范.md`](工程规范.md) | CI/ruff/gh | ✅ |
| — | [`drift-历史.md`](drift-历史.md) | 集中 🔓 Drift | ✅ |
| — | [`scripts/verify.sh`](../scripts/verify.sh) | 每条校验命令化 | ✅ |

> 完整细分清单见 `.workbuddy/tmp/decision-trace/decision-inventory.md`（L1-L4 约 60 条，含真实日期+证据+目标文件）。

---

## §3 条目七字段格式

每条决策固定七字段：

```
## D-YYYY-MM-DD-NNN  标题
- **事实**: 一句话确定事实
- **来源**: git commit / PR# / ADR-XXXX / 日志 / 代码位置
- **校验**: 可重跑命令（curl/grep/py_compile 等），用于 verify.sh
- **预期**: 校验应满足的断言
- **Drift**: 运行态背离（若有），含发现日+根因+修复
- **Owner**: 责任端（DevOps/前端/后端/ML/架构）
- **锁定**: 🔒 锁死 / 🔓 软锁(待 #XX)
```

---

## §4 当前已知 Drift（🔓，集中，待 #43 等修复）

1. ~~VLM n_ctx 运行态回退 4096~~（**2026-07-29 已闭环** — `start-joyai.ps1 -Mode minimal` 后 `/props` 报 `n_ctx=16384`；详见 `drift-历史.md` DRIFT-1）。
2. **memory-store 端口 8996 vs 8997**：`run-windows.env` 无 `MEMORY_PORT`/`JOYAI_MEMORY_STORE_URL` 覆盖行，当前 8997 靠手动 env。脚本默认拉 8996 空壳。
3. **webui 网关默认 8996**：`Start-Webui` 不导 `JOYAI_MEMORY_STORE_URL`（`run-windows.ps1:485-488`），`server.py:958` 默认 8996；且 memory-store 默认 opt-in（`JOYAI_ENABLE_MEMORY_STORE=1`）。
4. **bge-m3 provider：#38 改 nvidia（无 ADR）→ #42 revert 回 local（2026-07-28，已解决）**。当前默认 `local`，nvidia/siliconflow 仍可选（见 `drift-历史.md` DRIFT-4）。
