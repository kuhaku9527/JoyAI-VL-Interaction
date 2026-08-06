# Spec: F-3/F-4 live_adapter 状态一致性 + drift-gate 启动守卫安全批

- 关联 ADR: 0016-live-adapter-drift-gate-safe-batch.md
- 状态: Implemented（PR #87 → `bcc1543`，2026-08-05；原 commit `fec9c6f`）
- 来源: Wayfinder 地图 F-3/F-4 雾区（地图 102-107 行），由"安全高价值批"（q-0）选定
- 评审: joyai-code-reviewer 初判 BLOCK（F3-P1a 锁饥饿）→ 修复后 r-f34b APPROVED

## 1. 背景与问题

F-3/F-4 是 2026-08-05 探清的两块迷雾，按用户选定的"安全高价值批"实施（F3-P0/P1a/P1b/约法 + F4-P1c/约法）；F4-P0 显式延迟到独立 spec/adr。

**F-3（webinfer `live_adapter` 状态一致性）**
- **P0**：Local-Wiki 召回走 fire-and-forget task，但 `SessionState` 没有持有该 task 的引用集合 → `memory_io.py:273` 的 `getattr(state, "_memory_wiki_tasks", None)` 永远返回 `None` → tracking 从未生效 → 仅被局部变量引用的 task 可能在飞行中被 GC 回收（静默丢失召回）；且 `session.py:stop_background_tasks` 不取消这些 task。
- **P1a（关键 stall/死锁）**：`_handle_text_payload`（infer_loop.py）在持有 `state.lock`（`async with state.lock:` 跨越整个调用）时 `await asyncio.wait_for(state._memory_warmed.wait(), timeout=5.0)`，而后台 `_memory_warmup` task 需要 `state.lock`（memory_io.py:180 注释明确 `asyncio.Lock` 不可重入）。→ 后台 warmup 被饿死 → 每个会话首条文本请求**确定性 5s 卡顿 + 空 `_memory_block_cache`**。比原始"双拉"还糟。
- **P1b**：`_chat_payload_build_and_infer` 文本聊天路径未触发 `_memory_recall`，与文本/多模态主路径行为不一致。
- **约法**：warmup 失败日志为 DEBUG（不告警）；`DEBUG v0.2` try/except 静默吞异常。

**F-4（drift-gate v2.1 启动顺序/健康守卫）**
- **P1c**：#1/#2 把默认端口翻到 8997 后，`drift-contract.json` 的 `memory-store-port` / `webui-gateway-port` 检查只断言 `pattern: 8997`，未否定 `8996` → 若再出现 8996 残留（空壳回归）能蒙混过关，DRIFT-2/3 拦截失效。
- **约法**：`run-windows.ps1` 的 `Emit-Event` 调用 `} catch { }` 静默吞异常，Emit 失败不可见。

## 2. 目标

- F-3：Local-Wiki 召回 task 被 `SessionState` 持有（防 GC 回收）+ 会话停止时取消；消除文本首请求 5s 确定性 stall；统一文本聊天路径的 memory recall；去除静默吞异常。
- F-4：恢复 drift 契约对 8996 残留的拦截；消除 `Emit-Event` 异常静默。

## 3. 文件/接口变更

### F-3
- `services/webinfer/adapter_types.py`：`SessionState` 新增字段 `_memory_wiki_tasks: set = field(default_factory=set, repr=False)`（P0）。
- `services/webinfer/memory_io.py`：`getattr(state, "_memory_wiki_tasks", None)` 现解析为真实空集合 → `existing.add(task)` + `task.add_done_callback(existing.discard)` 生效（P0，无代码改动，依赖上一项）。
- `services/webinfer/session.py:stop_background_tasks`：取消 `_memory_wiki_tasks` 中未完成的 task（P0）。
- `services/webinfer/infer_loop.py`：
  - **删除** `_handle_text_payload` 内 "Slice 2" 内联 warmup 块（原 238-247 行）；改仅依赖后台 `_memory_warmup_task`（与多模态路径一致）（P1a，死锁修复）。
  - `_chat_payload_build_and_infer`（546 行）docstring 后触发 `_memory_recall(state, last_user_text)`（fail-open WARNING）（P1b）。
  - warmup 失败日志 DEBUG→WARNING；删除 `DEBUG v0.2` try/except 静默块（约法）。
- 新增测试：`services/webinfer/tests/test_f3_p0_wiki_task_tracked.py`、`test_f3_p1a_no_double_warmup.py`（后者在 `async with state.lock:` 下调用 `_handle_text_payload` + `asyncio.wait_for(timeout=3.0)` 捕捉 5s 回归）。

### F-4
- `config/drift-contract.json`：`memory-store-port` 与 `webui-gateway-port` 检查在 `pattern: 8997` 后均追加 `not_pattern: "8996"`（P1c）。
- `services/scripts/run-windows.ps1`（~249 行）：`} catch { }` → `} catch { Write-Warning "Emit-Event failed: $_" }`（约法）。

## 4. 不变 / 兼容性

- 后台 `_memory_warmup_task` 机制不变（session.py:98）；文本路径与之对齐而非新增内联拉取。
- drift 契约为纯新增 `not_pattern` 否定项，不破坏既有 8997 断言；fail-open 默认不变。
- 全部为修复/收紧，向后兼容。

## 5. 测试

- `test_f3_p0_wiki_task_tracked.py`：断言 wiki recall task 被记入 `state._memory_wiki_tasks` 且 cache 被填充（证 P0）。
- `test_f3_p1a_no_double_warmup.py`：持锁调用 `_handle_text_payload` + 3s 超时，断言 prompt 快速返回、cache 由后台 task 填充、恰好 1 次 warmup 拉取（捕捉原回归）。
- webinfer 全量回归：65 passed / 0 failed（reviewer r-f34b APPROVED）。

## 6. 验收

- 文本首请求不再确定性 5s stall；`_memory_block_cache` 由后台 warmup 填充。
- wiki recall task 在 `state._memory_wiki_tasks` 中可见、会话停止时被取消。
- drift 契约：含 8996 的候选配置被 `not_pattern` 拦截（DRIFT-2/3 恢复）。
- `run-windows.ps1` Emit-Event 异常现以 WARNING 可见。

## 7. 遗留 / follow-up

- **F4-P0（延迟，需独立 spec/adr）**：launcher 接线 `drift_gate` 到启动链路 + `verify.sh` / `drift_gate.py` 统一；且 `scripts/drift_gate.py` 非 `--json` 分支存在 `UnboundLocalError`（`out` 在 ~L263 未绑定）→ 无 `--json` 调用直接 rc1，阻塞 F4-P0，须在该 follow-up 一并修。
- F4-P1a/b/d/e、F3-P2a（summarizer_routing.py:68 全局 cache clear）、F3-P2b（prompt_assembly.py:171 char profile 缓存）：低优先，待后续工单。
