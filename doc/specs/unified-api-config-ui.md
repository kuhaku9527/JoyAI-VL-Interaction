# 统一 API 配置 UI + 热重载端点（正式）

> 生命周期标记：`<正式>`（retro，as-built 核验于 2026-08-08）
> 作者端点：`<前端 + 后端>`
> 关联：`决策/服务-webui.md`、`doc/adr/0014-log-event-schema.md`、`决策/服务-语音栈.md` D-080、`决策/AI代码质量约法三章.md`、`决策/服务-memory-store.md` D-033
> 合规：本 spec 套用 `决策/spec编写规范.md` 四要素（因果链 / 条件 harness / 负面约束 / 生命周期标记）。
> retro 说明：本功能实际由 PR #118（commit `01eb1f7`，承 #115）实现并合入 main，**未经 spec-first 流程**。本文件为事后补捕（as-built），目的是止血防再漂。原列缺口中「持久化 + PUT 校验硬化」已由 #122（PR #125，2026-08-08）闭合；仅剩 memory-store 跨进程 reload 验证归 #124。

## 1. 因果链（Why / Why-this-choice）

- **Problem**：用户诉求＝本地 + 云 API 都可用，且**绝对不能 fallback（报错就是报错）**。原状各模块 API key 只能靠环境变量注入 + 重启进程才能变更，无统一入口；云 key 一旦填错，要么静默失效要么偷偷回退 local，两种都不合规。
- **Why this choice**：在 webui 进程内建一个**单一运行时配置字典** `_services_config`（slots：`llm` / `summary` / `tts` / `asr`），配 `GET/PUT /api/services/config` 统一端点 + 前端 Services 设置面板 + `_propagate_services_to_runtime()` 在每次 PUT 时把配置推到各模块运行时实例。热重载不靠重启进程，而是靠「运行时实例就地更新 + ASR lazy 重连 + env 镜像」：
  - LLM/VLM：遍历活跃 session 的 `VLMService`，`update_api_settings()` + `set_model()`，并写 `default_vlm_config`；
  - TTS：把 `api_base` 镜像进 `os.environ["JARVIS_TTS_API_URL"]`，下一 session 的 `JarvisConfig.from_env()` 读到；
  - ASR：`invalidate_asr_client()`，下一浏览器 ASR 会话重连时读 live config（连接失败仍 raise，无 local fallback）；
  - Summary：fire-and-forget 代理 `POST /v1/summarizer/route` 到 webinfer，由 webinfer 自改状态（single-webinfer-main-path 原则）。
- **被否方案及理由**：
  1. *各模块各自暴露独立 reload 端点* → 否决：入口分散，前端要对接 N 个端点、契约难守；改为 webui 单一配置字典 + 统一端点，各模块从共享字典读。
  2. *改 key 必须重启进程* → 否决：用户体验差，且直接违反「本地+云随时切换」诉求。
  3. *云 key 无效时 fallback 到 local* → 否决：违反约法三章②与 D-080，静默掩盖故障，给后续埋雷（正是 #115 之前踩过的坑）。

## 2. 范围

- **做什么（as-built）**：webui 内统一 API 配置 UI（llm/summary/tts/asr 的 `api_base` / `model` / `api_key` 输入 + Save + 状态徽章 + probe）、后端 `GET/PUT /api/services/config`、运行时热重载传播 `_propagate_services_to_runtime()`、以及 ADR-0014 脱敏审计日志 `_log_config_change()`。
- **不做什么（负面约束）**：
  1. **不 fallback**：外部 key/url 无效 / 不可达 → 显式报错，绝不偷偷切 local 或跳过调用（见 D-080）。
  2. **不记 key 明文**：日志按 ADR-0014 脱敏（`***set***` / `***cleared***`），PII 红线见 D-061。
  3. **不改 memory-store 默认 provider=local 的立场**（D-033）；云 API 只是可选切换。
  4. **ASR 云 provider ≠ 加个 UI**：当前 ASR 仍是本地-only（whisper.cpp/FunASR/Qwen3-ASR vLLM :8993），真正的「ASR 云 provider」需要另行实现 provider 层，不在本 spec 范围。
- **已知局限 / 闭合状态**：
  - ① 配置**不持久化** → **已由 #122（PR #125）闭合**：`config/services.json` 原子写（tmp+`os.replace`+fsync，`chmod 0600`，gitignored）+ 启动深合并仅已知 slot/key，缺失/损坏回退默认不中止；重启保留。
  - ② PUT 对无效/不可达配置返回 HTTP 200 + `logger.warning` **沉默** → **已由 #122（PR #125）闭合**：格式错 `400` / 不可达 `422` 结构化显式报错（含 `slot`/`field`/`reason`/`status`），无效槽绝不应用/落盘，无静默 fallback（守 D-080）；空 `api_base` 视为有效「用默认/本地」不探活。
  - ③ memory-store 跨进程 reload 是否真正生效 → **仍开放，归 #124**（embedding provider 热重载端点 follow-up，OPEN）。

## 3. 设计（核心决策点）

- **单一配置字典 + 统一端点**（非分散端点）：`_services_config` 是 webui 拥有的唯一真源；`GET` 返回快照、`PUT` 按 slot 增量合并并触发传播 + 审计。
- **热重载靠「运行时实例就地更新 + ASR lazy 重连 + env 镜像」，非进程重启**：保证「改配置不重启」诉求，且不引入多进程状态同步复杂度。
- **审计与脱敏**：每次 PUT 变更走 `_log_config_change` → `logs/events/webui-<UTC-YYYY-MM-DD>.jsonl`，事件 `config.services.patch`；`api_key` 字段一律脱敏为 `***set***` / `***cleared***`，绝不落明文。
- **前端契约**：`static/config_services.js`（`window.JoyConfig`）封装 `load()/save()/probe()`，DOM 字段用 `svc-<slot>-<field>` 命名；`index.html` Services 面板 + Memory Store 子区（后者存 memory-store `/v1/settings/network`）。

## 4. Harness（仅当满足条件才存在）

> **触发条件（满足任一才保留本节，否则整节删除）**：
> - 实现 / 验证涉及「跨 ≥2 任务或 ≥2 agent 复用」的流程；或
> - 是「必须原样复现的仪式」（如跑批 / 封闭回路 / 发布验证）。
>
> 本 spec 的前端（`config_services.js`）与后端（`server.py` 端点 + 传播 + 审计）共守一份契约，且配置端点有必须原样复现的验证仪式 → 保留。

- 可复现工作流：
  - 前端契约：`services/webui/tests/config_services.test.js`
  - 后端脱敏审计：`services/webui/tests/test_config_change_event.py`
  - ASR 不可达显式报错（无 fallback）：`services/webui/tests/test_asr_websocket_failure.py`
- 验证仪式（发布 / 回归必跑）：起 webui → `PUT /api/services/config` 把 `asr.api_base` 改为不可达地址 → 前端 probe 徽章显 `ERR` 且**无 fallback 到 local**（D-080）；`logs/events/webui-*.jsonl` 中 `config.services.patch` 事件 `extra.redacted_values.api_key` 为 `***set***`、**无明文**。
- 注意：harness 是「让机制替人盯」的脚手架，不是业务算法描述。

## 5. 验收 / 排除

- **验收判据（as-built 已满足部分）**：UI 可填/存 4 模块 key；PUT 即时热重载生效（当前会话 / 下一 session）；日志按 ADR-0014 脱敏。
- **未竟之业**：
  - 已由 #122（PR #125）闭合：webui 重启后配置保留（持久化）；无效配置 PUT 显式报错且服务不静默失效（校验硬化）。
  - 仍开放（归 #124）：memory-store reload 行为已验证或已补端点（embedding provider 热重载端点）。
- **明确排除**：bug 修复、bug 验证、运维操作不属本 spec（见 `决策/spec编写规范.md` §3）；相关 runbook 见 `docs/github-runbook.md`。ASR 云 provider 实现另立（见 §2 负面约束 4）。
