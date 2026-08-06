# ADR 0016: webinfer 文本路径对齐后台 warmup + drift 契约恢复 8996 拦截

- 状态: Accepted
- 日期: 2026-08-05
- 上下文: doc/specs/f34-live-adapter-drift-gate-safe-batch.md

## 决策

1. **F-3 文本首请求 stall 修复**：删除 `_handle_text_payload` 内"持有 `state.lock` 时 `await state._memory_warmed.wait()`"的内联 warmup 块（P1a 死锁根因）；文本路径改与多模态路径一致，**仅依赖后台 `_memory_warmup_task`**（session.py:98）。理由：`asyncio.Lock` 不可重入（memory_io.py:180），持锁 await 跨 task 事件必然饿死后台 warmup → 确定性 5s stall + 空 cache。
2. **F-3 wiki task 防 GC 回收**：`SessionState` 新增 `_memory_wiki_tasks` 集合持有 fire-and-forget 召回 task 引用 + done_callback 自动 discard；`stop_background_tasks` 取消未完成项（P0）。
3. **F-3 文本聊天路径统一 recall**：`_chat_payload_build_and_infer` 触发 `_memory_recall`（P1b）。
4. **F-4 drift 契约收紧**：`drift-contract.json` 的 8997 端口检查追加 `not_pattern: "8996"`，恢复对 8996 空壳残留的拦截（P1c，DRIFT-2/3）。
5. **约法三章落地**：webinfer warmup 失败日志 DEBUG→WARNING + 删除静默 try/except；`run-windows.ps1` Emit-Event 异常由 `} catch { }` 改为 `Write-Warning`。

## 不变 / 边界

- 后台 warmup 机制不变；不引入"持锁 await warmup"的二次实现。
- drift 契约为 fail-open 默认不变；仅新增否定项。
- 文本路径与多模态路径 warmup 行为现对齐（单一真相：后台 task）。

## 后果

正面：
- 消除每个会话首条文本请求的确定性 5s stall 与空 cache（P1a 修复是行为级，影响真机首响延迟）。
- Local-Wiki 召回 task 不再可能被 GC 回收（P0）。
- drift 契约重新能拦 8996 回归（与 #1/#2 同源治理线）。
- Emit-Event 失败可见（约法）。

负面 / 取舍：
- 文本首请求"等待 warmup 填充 cache"的语义从"内联等待"变为"依赖后台"，若后台 warmup 本身失败，首请求 cache 仍为空（但已有 WARNING 告警，且 fail-open）——与多模态路径行为一致，属有意的统一。
- 新增 2 个测试文件。

## 替代方案（拒了）

- **A. 保留内联 warmup 但释放锁再 await**。仍造成"首请求双拉"（背景 + 内联）且时序复杂，违背 #1/#2 已确立的"单一后台 warmup"设计。拒。
- **B. 把 `state.lock` 换成可重入锁**。`asyncio.Lock` 不可重入是 CPython 的事实约束；改可重入锁会掩盖真正问题（warmup 不应在请求关键路径持锁等待）。拒。
- **C. drift 契约只断言 8997 不否定 8996**。等价于放弃 DRIFT-2/3 拦截，8996 空壳回归能蒙混——与 #1/#2 治理目标矛盾。拒。
- **D. Emit-Event 异常继续静默**。违反约法三章（不静默）。拒。

## 引用

- PR #87 → `bcc1543`（2026-08-05，squash 合入 main；原 commit `fec9c6f`）
- Wayfinder 地图 F-3/F-4 块（`.workbuddy/tmp/wayfinder-map-health-audit.md` 102-107 行）
- 关联约法：`决策/AI代码质量约法三章.md`
- 关联治理：#1（PR #83）、#2（PR #84）8996 清零同源线
- 关联 spec：`doc/specs/f34-live-adapter-drift-gate-safe-batch.md`
- 遗留：F4-P0（launcher 接线 + drift_gate.py UnboundLocalError，待独立 spec/adr）
