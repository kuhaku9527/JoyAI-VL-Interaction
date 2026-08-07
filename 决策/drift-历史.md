# Drift 历史（集中记录所有 🔓 运行态背离）

> 本文件集中记录决策书各条目中的 **运行态（regression）背离决策态（decision）** 的漂移。
> 原则（见 `README.md` §1）：运行态 ≠ 决策态，凡背离记于此，不污染决策日。每条含发现日 / 决策态 / 运行态 / 根因 / 修复 / 关联 D-id。
> 待对应修复 PR 合入后，由 AI 提议关闭并追加 `closed: 日期｜by AI｜approved: 用户`。（注：**#43 仅指视频采集端到端延迟调研**，端口/env/watchdog 类漂移各有独立归属 PR，不得混用 #43 为通用"待修"编号）

---

## DRIFT-1  VLM `n_ctx` 运行态回退 4096（决策态 16384）

- **发现日**: 2026-07-28（主理人核验 `logs/llama-main.log:14` `n_ctx_slot = 4096`）
- **决策态**: `n_ctx = 16384`，git `4dd4fc3`（2026-07-13 由 4096 提升治本溢出），`run-windows.env:35` `MAIN_CONTEXT=16384`
- **运行态**: 当前 llama-server `n_ctx_slot = 4096`
- **根因**: 启动路径未 source 到 `MAIN_CONTEXT`；`run-windows.ps1:317` `$ctx = if ($env:MAIN_CONTEXT){...} else {4096}` 走了 4096 兜底
- **修复**: 走正确启动路径 `powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Restart llama-main`（加载 `.env` → `MAIN_CONTEXT=16384` → `-c 16384`）；重启后 `grep n_ctx_slot logs/llama-main.log` 应见 16384
- **关联**: D-021（决策态）/ D-022（运行态）/ 业务-上下文架构 D-079
- **状态**: ✅ **已闭环 2026-07-29｜by AI｜approved: 主理人**
  - 验证：`powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Mode minimal` 拉起后 `curl http://127.0.0.1:7060/props | jq .default_generation_settings.n_ctx` 返回 `16384`
  - 决策态 = 运行态一致；启动路径固定为 `start-joyai.ps1 -Mode <mode>`（加载 `run-windows.env` → `MAIN_CONTEXT=16384`），手动 `start-llama-server -c 4096` 路径已识别为反模式（详见 `决策/服务-webinfer.md` 备注）
- `closed: 2026-07-29｜by AI｜approved: 主理人`

---

## DRIFT-2  ~~memory-store 端口 8996 vs 8997~~（脚本默认缺覆盖）

- **发现日**: 2026-07-28（主理人自验 grep `run-windows.env` 零命中 MEMORY_PORT/8997/JOYAI_MEMORY_STORE_URL）
- **决策态**: `:8997` 真后端（bge-m3 语义召回，#36）；`:8996` 废弃空壳（D-L4-001 端口铁律）
- **运行态**: `run-windows.env` **无** `MEMORY_PORT`/`JOYAI_MEMORY_STORE_URL` 覆盖行；当前 8997 靠手动 env 拉起；脚本默认拉 8996 空壳
- **根因**: 脚本默认端口写在 `memory-store/app.py:332`（=8996），env 未覆盖为 8997
- **修复**: #43 统一（脚本默认改 8997，或 `run-windows.env` 补 `MEMORY_PORT=8997` + `JOYAI_MEMORY_STORE_URL=http://127.0.0.1:8997`）
- **关联**: D-008（启动链路）/ D-031（webinfer 默认 8996）/ D-040/D-041（memory-store 端口铁律）
- **状态**: ✅ **已闭环 2026-07-29｜by AI｜approved: 主理人**
- `closed: 2026-07-29｜by AI｜approved: 主理人`

---

## DRIFT-3  ~~webui 网关默认连 8996~~（env 未导出 + memory-store opt-in）

- **发现日**: 2026-07-28（主理人自验 `run-windows.ps1:485-488` `Start-Webui` 不导 `JOYAI_MEMORY_STORE_URL`；`:553-556` memory-store 默认 opt-in）
- **决策态**: webui 网关应连 `:8997`（真后端）
- **运行态**: `server.py:958` `MEMORY_STORE_URL = os.environ.get("JOYAI_MEMORY_STORE_URL", "http://127.0.0.1:8996")` 默认 8996；`Start-Webui` 不导出该 env；memory-store 需 `JOYAI_ENABLE_MEMORY_STORE=1` 才拉
- **根因**: 启动脚本未导出 env + memory-store 默认关闭
- **修复**: #43 同 DRIFT-2 一并修（导出 env + 默认开启 memory-store）
- **关联**: D-015（跨域铁律）/ D-037（网关代理路由）/ D-038（网关超时）
- **状态**: ✅ **已闭环 2026-07-29｜by AI｜approved: 主理人**
- `closed: 2026-07-29｜by AI｜approved: 主理人`

---

## DRIFT-4  #38 默认 bge-m3 provider = nvidia → #42 revert 回 local（已解决）

- **发现日**: 2026-07-27（#38 `0ac6d10` 合入后）
- **决策态**: 默认 embedder 应为 `local`（离线建库优先）或硅基流动（国内可达）；provider 切换须有 ADR 记录
- **运行态(历史)**: #38 将 `BgeM3Embedder` 默认 provider 改为 `nvidia`（`integrate.api.nvidia.com/v1`，默认 `use_proxy=false`，国内通常不可达），**无对应 ADR 记录**（ADR-0012 diff=0）
- **根因**: #38 改默认 provider 但未走 ADR 流程，注释"see ADR-0012 provider switch"但设计文档无对应条目
- **修复(已落盘)**: **#42（2026-07-28）已 revert 默认回 `local`** —— `services/memory-store/src/memory_store/embedder.py:15-17,83-89` 明示 "The default was switched from `nvidia` to `local`; #42 reverted #38's ad-hoc change to `nvidia`"，当前 `EMBEDDING_PROVIDER` 默认 `"local"`。`nvidia`/`siliconflow` 仍可选（ADR-0012 §6 provider switch），但非默认。
- **对话证据(第三源)**: `会话记录/审查本地Wiki向量检索架构设计.json`（07-24 22:52）设计选定 **硅基流动 BAAI/bge-m3 免费 API**（"它不配做默认路径"指付费/云端项）；`会话记录/有关于记忆和hermes的架构方案…json`（07-25 13:31）PR #38 创建。印证"设计意图=SiliconFlow，#38 临时改 nvidia 是偏离，#42 回归 local"。
- **关联**: D-040（v5 默认 siliconflow）/ D-045（B1 三 provider）/ 业务-LocalWiki Drift
- **状态**: ✅ 已解决（#42 revert 回 local，2026-07-28；原 P1 待裁决关闭）
- `modified: 2026-07-28｜by AI｜approved: §0.4召回轮特许（交叉验证修正陈旧漂移）`

---

## DRIFT-5（备注，非运行时）  KWS 训练脚本外溢路径 `<workspace>`

- **发现日**: 2026-07-28（亲验 `services/kws-training/train_kws.py:5-16`）
- **事实**: 自训脚本内数据/产物路径写 `<workspace>/data/kws/...` 与 `<workspace>/models/sherpa-onnx/...`，属工作区外溢（违反隔离纪律 D-L4-002）。
- **影响**: 仅限**训练期**（非运行时服务）；运行时 KWS 用进程内 sherpa-onnx 加载，不受影响。
- **修复**: 建议训练脚本路径改为工作区内（`.cache/` 或 `data/`），与隔离纪律对齐。非阻塞。
- **关联**: D-046（KWS）/ D-L4-002（隔离）
- **状态**: 🔓 建议整改（非阻塞）

---

---

## DRIFT-6  chat 主路径被 memory-store 串行拖累（5s timeout per turn）

- **发现日**: 2026-07-29（实测：memory-store 关闭时连发 8 条 chat 延迟 846ms → 2078ms → 174/190/147/315/315/320ms，前 2 条带 5s timeout 拖尾）
- **决策态**: chat 延迟应与 memory-store 状态解耦；wiki recall 是富化不是阻塞
- **运行态**: `services/webinfer/memory_io.py:_memory_recall` 原版 `await self._memory_wiki_recall(...)` inline 调用；`MemoryStoreClient` 无熔断器，每次失败重试满 5s
- **根因**: memory-store 是 webinfer chat 热路径必经；D-023 锁定"不回退"语义叠加客户端无韧性 → 单点放大
- **修复**: 2026-07-29 本轮 — D-032（wiki recall fire-and-forget）+ D-033（客户端熔断器 v0.3：3 失败 / 30s 冷却），配套 spec `doc/specs/memory-client-resilience.md` + ADR `doc/adr/0013-webinfer-memory-client-resilience.md`
- **验证**: 修复后连发 8 条 chat 最大延迟 2078ms（首条），第 3 条起 <320ms（修复前预期 5s+/条）
- **关联**: D-023（webinfer 单入口 SPOF）/ D-031（memory_store url 默认 8996 漂移）/ 决策/服务-VLM.md D-022 Drift（0 字节瞬态事故可能同源）
- **状态**: ✅ 已闭环 2026-07-29｜by AI｜approved: 主理人
- `closed: 2026-07-29｜by AI｜approved: 主理人`

---

## 漂移汇总（一眼看全）

| # | 漂移 | 决策态 | 运行态 | 根因 | 修复 | 状态 |
|---|---|---|---|---|---|---|
| 1 | VLM n_ctx | 16384 | 4096 | 启动未 source MAIN_CONTEXT | `start-joyai.ps1` 重启 | ✅ 2026-07-29 |
| 2 | memory-store 端口 | 8997 | 8996(默认) | env 无覆盖 | run-windows.env + Start-MemoryStore 默认开 | ✅ 2026-07-29 |
| 3 | webui 网关端口 | 8997 | 8996(默认) | env 未导出+opt-in | Start-Webui 导 JOYAI_MEMORY_STORE_URL + server.py 9997 | ✅ 2026-07-29 |
| 4 | bge-m3 provider | local(当前) | nvidia(#38临时) | #38 无 ADR→#42 revert local | 已解决 | ✅ |
| 5 | KWS 训练路径 | 工作区内 | <workspace> | 脚本硬编码 | 建议整改 | 🔓 |
| 6 | chat 主路径被 memory-store 拖累 | 独立 | 5s+/条 | inline await + 无熔断器 | D-032/033 fire-and-forget + 熔断器 v0.3 | ✅ 2026-07-29 |
