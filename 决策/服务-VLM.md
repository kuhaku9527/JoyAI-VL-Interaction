# 服务-VLM / :7060 llama-server（主模型）

> 范围：`:7060` 主 VLM 推理服务（llama-server.exe + IQ4_NL 8B 量化）。
> 真相源：`services/scripts/run-windows.ps1` + `services/webinfer` 调用约定 + 实测。
> **修改走 §0 治理协议（AI 提议 → 用户同意 → 落盘）。**

---

### D-2026-07-13-020 | VLM 端口与进程
| 字段 | 内容 |
|---|---|
| **事实** | `:7060` 由 `llama-server.exe` 监听（PID 写入 `services/.pids/llama-main.pid`）；进程名 `llama-server.exe` |
| **来源** | `services/scripts/run-windows.ps1`（快照 2026-07-13 即含此启动逻辑；日期取下限） |
| **校验** | `tasklist 2>/dev/null | grep -i llama-server; netstat -ano 2>/dev/null | grep ":7060" | grep LISTENING` |
| **预期** | 1 个 llama-server 进程；LISTENING 状态 |
| **Drift** | 2026-07-28 进程在但 `0 字节响应`（瞬态，复测 health 200；详见 Drifts 段） |
| **Owner** | 运维 |
| **锁定** | ✅ |

---

### D-2026-07-13-021 | VLM 模型精确路径
| 字段 | 内容 |
|---|---|
| **事实** | 主模型 = `D:\AI\models\main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\joyai-vl-interaction-preview-iq4_nl-imat.gguf`（8B 参数，IQ4_NL 4.5 bpw 量化，n_embd=4096；**上下文窗口 `n_ctx` 是运行时启动参数，非模型固有属性，见 D-2026-07-13-027**） |
| **来源** | `services/scripts/run-windows.ps1` + `curl :7060/v1/models` 实测（快照 2026-07-13 起） |
| **校验** | `curl -fsS http://127.0.0.1:7060/v1/models -m 3 | jq -r '.data[0].id'` |
| **预期** | 输出路径以 `...joyai-vl-interaction-preview-iq4_nl-imat.gguf` 结尾 |
| **Drift** | 2026-07-25 误以为模型在 `D:\AI\bin\llama.cpp\models\` |
| **Owner** | 运维 |
| **锁定** | ✅ |

---

### D-2026-07-13-022 | VLM 推理接口契约
| 字段 | 内容 |
|---|---|
| **事实** | llama-server 暴露 OpenAI 兼容接口：`/v1/chat/completions`（POST）、`/v1/completions`（POST）、`/v1/models`（GET）、`/health`（GET）；支持流式（`stream: true`） |
| **来源** | `services/webinfer/adapter_core.py` + `curl :7060/v1/models` 实测（快照 2026-07-13 起） |
| **校验** | `curl -fsS http://127.0.0.1:7060/v1/models -m 3 | jq '.data[0].id'` |
| **预期** | HTTP 200 + JSON |
| **Drift** | 🟥 2026-07-28 直连 POST `/v1/chat/completions` 出现 0 字节超时（瞬态；复测 :7060 health 200 模型在线，根因未定，详见 Drifts） |
| **Owner** | 运维 |
| **锁定** | ✅ |

---

### D-2026-07-13-023 | VLM 端到端配置（webinfer 视角）
| 字段 | 内容 |
|---|---|
| **事实** | webinfer 调 VLM 用 `ADAPTER_MODEL=streaming-infer-adapter`（OpenAI 兼容协议）；`MAIN_MODEL=streamingharness-8b`（内部模型名）；`REQUEST_TIMEOUT_SECONDS=300.0`（5min） |
| **来源** | ADR-0006（2026-07-13 LLM 网关单入口：所有 LLM 经 webinfer :8070，webui 不直连 :7060）+ `services/webinfer/adapter_types.py:75` |
| **校验** | `curl -fsS http://127.0.0.1:8070/health -m 3 | jq -r '.model'` |
| **预期** | `streaming-infer-adapter` |
| **Drift** | webinfer 端健康 + 配置正确，问题在 VLM 自身（见 D-022 Drifts） |
| **Owner** | 后端 |
| **锁定** | ✅ |

---

### D-2026-07-11-024 | VLM 重启子命令
| 字段 | 内容 |
|---|---|
| **事实** | `start-joyai.ps1 -Restart llama-main` 会杀 7060 进程并按当前 env 重新拉起，无需重启整套服务 |
| **来源** | `start-joyai.ps1` + `services/scripts/run-windows.ps1`（重启能力由 ADR-0004 2026-07-11 决定；`#41` 2026-07-28 修 PS5.1 后稳定） |
| **校验** | `powershell -NoProfile -Command "& 'start-joyai.ps1' -Restart llama-main -DryRun"` |
| **预期** | 打印"would restart llama-main"类似提示，**不真的启动** |
| **Drift** | 2026-07-28 VLM 死时本应执行此命令而非手动操作 |
| **Owner** | 运维 |
| **锁定** | ✅ |

---

### D-2026-07-13-025 | VLM 不会自动重启
| 字段 | 内容 |
|---|---|
| **事实** | `run-windows.ps1` **不**配置 watchdog / supervisor；VLM 进程崩溃后端口 7060 不会被自动重启；需手动 `-Restart llama-main` |
| **来源** | `services/scripts/run-windows.ps1` 全文（无 watchdog 逻辑；快照 2026-07-13 起即如此） |
| **校验** | `grep -n "watchdog\|supervisor\|restart.*on.*fail" services/scripts/run-windows.ps1` |
| **预期** | 0 命中 |
| **Drift** | 🟥 2026-07-28 VLM 死后用户问"AI 也忘了"，根因无 watchdog（待 #43 加 supervisor） |
| **Owner** | 运维 |
| **锁定** | 🔓（待加 watchdog） |

---

### D-2026-07-13-026 | VLM 启动日志
| 字段 | 内容 |
|---|---|
| **事实** | VLM 启动日志在 `services/.logs/llama-main.log`（stdout）+ `services/.logs/llama-main.err.log`（stderr） |
| **来源** | `services/scripts/run-windows.ps1`（`$LogDir = Join-Path $ServicesDir ".logs"`；快照 2026-07-13 起） |
| **校验** | `tail -n 50 services/.logs/llama-main.err.log` |
| **预期** | 看到 `llama_model_loader_internal: loaded meta data` 等启动成功消息 |
| **Drift** | 2026-07-28 VLM 死时若需查根因，本目录是首查 |
| **Owner** | 运维 |
| **锁定** | ✅ |

---

### D-2026-07-13-027 | VLM 上下文窗口 n_ctx = 16384（运行时，非模型固有）
| 字段 | 内容 |
|---|---|
| **事实** | llama-server 运行时上下文窗口 = **16384 tokens**（`-c 16384`），由 2026-07-13 的 4096 提升而来；模型本身 `n_ctx_train=262144`（见 `logs/llama-*.log`），16384 是**部署窗口**而非模型上限 |
| **来源** | commit `4dd4fc3`「v3.34: llama-server ctx 16384 + webinfer prompt guard」（2026-07-13）+ `services/scripts/run-windows.env:35 MAIN_CONTEXT=16384` + `MAIN_CTX_TOKENS=16384` + `services/scripts/run-windows.ps1:317`（读 `$env:MAIN_CONTEXT`，缺失才兜底 4096） |
| **校验** | `grep -n "n_ctx_slot" logs/llama-main.log` → 预期 `n_ctx_slot = 16384`；或确认启动参数含 `-c 16384` |
| **预期** | 运行实例 `n_ctx_slot = 16384` |
| **Drift** | 🟥 **2026-07-28 19:15 启动实例 `n_ctx_slot = 4096`**（env 未注入进程，`run-windows.ps1:317` 走 4096 兜底）→ 图片+记忆+wiki 字符输入溢出。这是**运行态回退**，决策(16384)与提交配置(env=16384)均未漂移。修复：经 `run-windows.ps1`（`-Mode llama` 或 `start-joyai.ps1 -Restart llama-main`）重启，加载 `.env` → `MAIN_CONTEXT=16384` → `-c 16384` |
| **Owner** | 运维 |
| **锁定** | ✅ |
| **modified** | 2026-07-28 21:23 由主理人据 `git show 4dd4fc3` + `logs/llama-main.log:14` + `run-windows.ps1:317` 三方核对新增；推翻此前 D-021 误写的"n_ctx=4096 模型固有" |

---

## Drifts（漂移历史，仅追加）

### 2026-07-28 23:20（VLM 0 字节瞬态事故）
- **症状**：用户在 webui 提问，两次都收到 `[LLM error.]`，UI 显示 `LLM 30s`。
- **诊断**：
  1. `curl -fsS http://127.0.0.1:7060/v1/models` ✅ 200（模型已加载）
  2. `curl -X POST http://127.0.0.1:8070/v1/chat/completions` ❌ 8008ms 超时 0 字节 → webinfer→VLM 链路断
  3. 复测（同日稍后）：`:7060/health` 200、模型在线 → **0 字节为瞬态**，非持久崩溃
- **可能原因**：VLM 启停态不稳 / CUDA 13.3 移植版边界 / 中间层 Accept-Encoding 头处理
- **缓解**：`start-joyai.ps1 -Restart llama-main`；查 `services/.logs/llama-main.err.log`；必要时降级到 `andgihat-9150-backup` 或 `b10155` 旧版（见 MEMORY.md 模型框架段）

### 2026-07-28 19:15（日志时间）/ 21:23（发现）｜ VLM 上下文窗口运行态回退至 4096
- **症状**：`logs/llama-main.log:14` 显示本次启动 `n_ctx_slot = 4096`，与锁定决策 16384 不符；用户反馈「图片+记忆+wiki 字符输入直接爆」。
- **根因（已定位，三源交叉验证）**：
  1. 决策未漂移：`git show 4dd4fc3` 改 `run-windows.env MAIN_CONTEXT 4096→16384`；`doc/main/00-main-direction.md:108` 记载 07-13 ctx 4096→16384。
  2. 提交配置未漂移：工作树与 `git HEAD` 的 `run-windows.env:35` 均为 `MAIN_CONTEXT=16384`。
  3. 启动逻辑正确：`run-windows.ps1:317` 读 `$env:MAIN_CONTEXT`，仅当其缺失才兜底 4096；env 加载器 `:74-87` 会把 `.env` 的 `MAIN_CONTEXT` 注入进程。
  4. **结论**：本次 19:15 启动的 llama-server 进程环境里 `MAIN_CONTEXT` 未生效（启动路径未加载 `.env` 或被覆盖），故走了 `:317` 的 4096 兜底。属**运行态回退**，非决策/配置漂移。
- **修复（已执行 2026-07-29）**：`powershell -ExecutionPolicy Bypass -File start-joyai.ps1 -Mode minimal`（加载 `run-windows.env` → `MAIN_CONTEXT=16384` → `-c 16384`）拉起后实测 `curl http://127.0.0.1:7060/props | jq .default_generation_settings.n_ctx` = **`16384`**。DRIFT-1 闭环（详见 `决策/drift-历史.md` DRIFT-1）。
- **文档教训（方法论）**：本决策书 D-021 曾误把运行态 `n_ctx=4096` 当作模型固有事实写入，未做「运行值 vs 决策值」交叉验证，且子代理 trace 被要求压缩(150字)、范围未含 LLM ctx，导致遗漏。**规则：关键事实必须直接读源码+git+日志三方核对；运行值与决策值须分别记录，不得互相覆盖。**

---

## 待补充

- D-XXX：VLM 启动参数（-ngl / -c / --mmproj 等）— 待 run-windows.ps1 后段确认
- D-XXX：VLM 启动耗时（实测首字节延迟）
- D-XXX：VLM 多并发槽位（slots）
- D-XXX：VLM 显存/NVML 监控命令
