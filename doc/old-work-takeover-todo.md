# 旧活儿接手 TODO（分支大扫除后）

> 背景：2026-08-02~03 分支大扫除删了 18 条旧分支（本地+远端），其中 7 条有真货的打了
> `archive/<名>` 标签兜底（**本地标签、不推送、不占工作分支数**）。
> 本文件逐条判断是否值得接手，按「一个一个来、少开分支、做完即删」的纪律执行。
> 接手纪律以 `决策/AI代码质量约法三章.md` 为准。

## 接手前置流程（每条都走）

1. **复活**：`git branch <原名> archive/<原名>` → 从原 commit 变成工作分支。
2. **范围核验（spec/adr 框定）**：核对该分支对应的 spec/adr 是否仍在 `doc/specs/` / `doc/adr/` 且能框住本次改动范围。
   - 框得住 → 继续第 3 步。
   - 框不住 / 缺失 / 已 stale → **先补 spec**（走 spec→adr→落地 流程），再开工。**禁止无 spec 框定就直接写代码**——这正是「AI 从零做漂亮 demo 但不对接创作者需求」的根因。
3. **精确核验**：对比标签版改动文件 vs `origin/main` 同名文件，确认 main 是否已有等价实现（标签独有 ≠ main 没有等价，可能已被别的 PR 取代）。
4. **开工**：只建这一条工作分支，遵守约法三章（禁静默/禁 fallback/必 log/增新删旧）。
5. **收尾**：合 PR → 删远端+本地分支 → 此时 `archive/<名>` 标签可保留兜底或 `git tag -d` 清掉。

## 逐条清单（依据 `git diff --stat origin/main...archive/<tag>` 实测）

### ① `feat-q2-emit` —— ★ 最高优先，建议第一个接手
- **内容**：把 ADR-0014 JSONL 事件流接线进 cold services（webinfer / memory-store / webui）
- **相对 main 独有**：15 提交，31 文件，+1782/−772；核心改动 `memory_io.py` / `memory_store_client.py` / `webui/server.py` + `index.html` + `决策/` 文档
- **判断**：**真·未完**。main 里 JSONL 仅 `background-agent/codex_api/main.py` 一处；webinfer/memory-store/webui 侧接线缺失 = 用户说的「模块 log 没做完」本体，也是约法三章生效的前提。
- **spec/adr 痕迹**：ADR-0014 + `doc/specs/log-event-schema` ✅ 齐全，框得住。
- **复活**：`git branch feat-q2-emit archive/feat-q2-emit`
- **开工核验**：比对标签版 memory_io.py / memory_store_client.py 与 main 同名文件，找出缺的 logger 调用

### ② `feat-drift-gate-runtime-v2.1` —— 大概率跳过，待精确核验
- **内容**：drift-gate v2.1 运行时门禁 + D-038 决策 + T-06 spec
- **相对 main 独有**：15 提交，23 文件；但 main 的 `quality.yml` 已有 `drift-gate-runtime` 段、`doc/adr/0015` 也存在
- **判断**：主体已落地；15 个提交可能是 D-086 微调或后续。复活后精确比对，大概率无活儿可接。
- **spec/adr 痕迹**：spec `drift-gate-harness-spec` + main 已含 ADR-0015 ✅ 齐全。
- **复活**：`git branch feat-drift-gate-runtime-v2.1 archive/feat-drift-gate-runtime-v2.1`

### ③ `fix-backend-p3-swallow-logging` —— 建议接手（直接对应用户痛点）
- **内容**：记录 `webinfer/session.py` 与 `memory-store/sqlite_backend.py` 里被静默吞掉的异常
- **相对 main 独有**：1 提交，2 文件，+9/−3
- **判断**：小修复、正面（符合约法三章「要有 log」），价值高、风险低。
- **spec/adr 痕迹**：与日志 schema(ADR-0014) 沾边 ✅ 部分（非专门 spec，属小修复，按治理可不强制 spec）。
- **复活**：`git branch fix/backend-p3-swallow-logging archive/fix-backend-p3-swallow-logging`

### ④ `fix-backend-p1-asr-kwstraining-s101` —— 接手
- **内容**：把 asr/kws/hermes 里的生产 `assert` 换成显式 `raise` + 测试（`test_hermes_api_enrich_guard.py`）
- **相对 main 独有**：3 提交，6 文件，+126
- **判断**：方向正确（把静默 assert 变显式 raise，正是约法三章鼓励的）。复活后核验 main 是否已有等价。
- **spec/adr 痕迹**：对应 ADR-0008（p0-adapter-fixes）✅。
- **复活**：`git branch fix/backend-p1-asr-kwstraining-s101 archive/fix-backend-p1-asr-kwstraining-s101`

### ⑤ `fix-backend-p1-kws-datamodule-b019` —— 接手
- **内容**：`lru_cache` 误用在实例方法的修复
- **相对 main 独有**：2 提交，3 文件，+13/−7
- **判断**：小修复，低风险。
- **spec/adr 痕迹**：对应 ADR-0008（p0-adapter-fixes）✅。
- **复活**：`git branch fix/backend-p1-kws-datamodule-b019 archive/fix-backend-p1-kws-datamodule-b019`

### ⑥ `fix-webinfer-context-overflow-bound` —— 接手
- **内容**：webinfer 上下文溢出边界测试 + 实现边界
- **相对 main 独有**：2 提交，5 文件，+229；含 `test_context_overflow_bounds.py`
- **判断**：测试类，低风险，接手。
- **spec/adr 痕迹**：ADR-0013 + spec `memory-client-resilience` ✅ 齐全。
- **复活**：`git branch fix/webinfer-context-overflow-bound archive/fix-webinfer-context-overflow-bound`

### ⑦ `feat-webui-i18n-tests` —— 待定（前端测试）
- **内容**：前端 device-label i18n 抽出做测试
- **相对 main 独有**：1 提交，3 文件，+126（`i18n_device_label.js` + `i18n_device_label.test.js`）
- **判断**：前端测试，价值取决于是否要 i18n。先排队。
- **spec/adr 痕迹**：❌ 无专门 spec/adr（大概率直接 PR 没走流程）→ **接手前须先补 spec 框定范围**。
- **复活**：`git branch feat/webui-i18n-tests archive/feat-webui-i18n-tests`

## 建议接手顺序

| 序 | 条目 | 理由 |
|----|------|------|
| 1 | `feat-q2-emit` | 模块 log 接线 = 用户痛点本体 + 约法三章前提，最高优先 |
| 2 | `fix-backend-p3-swallow-logging` | 静默异常记录，契合约法三章，小低风险 |
| 3 | `fix-backend-p1-asr-kwstraining-s101` | 显式 raise，方向正确 |
| 4 | `fix-backend-p1-kws-datamodule-b019` | 小修复 |
| 5 | `fix-webinfer-context-overflow-bound` | 测试，低风险 |
| 6 | `feat-drift-gate-runtime-v2.1` | 核验后大概率跳过 |
| 7 | `feat-webui-i18n-tests` | 待定 |

## 状态追踪（每条开工 / 合入后更新）

- [ ] ① feat-q2-emit — 待接手
- [ ] ② feat-drift-gate-runtime-v2.1 — 待核验（大概率跳过）
- [ ] ③ fix-backend-p3-swallow-logging — 待接手
- [ ] ④ fix-backend-p1-asr-kwstraining-s101 — 待接手
- [ ] ⑤ fix-backend-p1-kws-datamodule-b019 — 待接手
- [ ] ⑥ fix-webinfer-context-overflow-bound — 待接手
- [ ] ⑦ feat-webui-i18n-tests — 待定
