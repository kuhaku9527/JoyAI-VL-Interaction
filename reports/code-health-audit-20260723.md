# JoyAI-VL-Interaction — 全局代码质量体检报告

> 审查者：review 对话端（独立质量体检，不写业务代码）
> 日期：2026-07-23
> 靶子：`main` @ `3fed7f8`（HEAD，PR #21）
> 方法：`git cherry` 核实未合并分支 → `ruff 0.15.22` 全仓高价值缺陷探针（绕过 ignore 暴露被隐藏项）→ 热点模块人工审查（XSS / 错误链 / 上下文溢出边界 / 构建产物追踪）
> 组织方式：**按角色分章**（前端 / 后端 / 测试 / 架构），每章给「发现 + 该角色该做的事」，便于对应对话/成员直接读自己那节。

---

## 0. TL;DR（给所有人）

- **CI 门禁有系统性盲区**（架构角色主责）：`S`（安全/Bandit）和 `BLE`（盲捕获）根本不在 `select` 里；`B904/B019/B007` 被各服务的 `extend-ignore` 压掉。结果：**生产代码里 ~104 处盲 `except Exception`、8 处硬编码 `/tmp`、4 处 bind 0.0.0.0 全对 CI 不可见**。
- **后端高价值缺陷集中**：盲异常 104 / `assert` 生产路径 14 / `try-except-pass` 7 / `S108 /tmp` 8 / `S104` 0.0.0.0 4 / `B019` 实例方法缓存 3 / 死变量 3。无 `F821`/`B904` 实锤（baseline 文档已过时）。
- **前端防线扎实**：XSS 防护（DOMPurify 白名单 + VLM token 转义 + CSP + iframe 清洗）到位；主要短板在**测试**（0 前端测试，与测试角色共担）。
- **好消息**：`memory-store/app.py` 错误链正确；webinfer 上下文溢出修复（#22）正确 + 6 回归测试；pytest 门禁在跑（memory-store 16 / background-agent 7 / webinfer ~99）。
- **文档 + 流程漂移**（架构角色）：`lint-baseline.md` §4 已失效；6 个陈旧/重复远端分支待清。

> 角色对照：前端 = `joyai-frontend-webui`（浏览器静态 + XSS）；后端 = `joyai-backend`（全部 Python 微服务）；测试 = 质量门禁/覆盖率（pytest + 前端测试）；架构 = `joyai-devops` + 架构文档 + 仓库流程（CI 配置 / 文档一致性 / 分支保洁）。

---

## 1. 前端（joyai-frontend-webui 读这章）

**范围**：浏览器前端（`services/webui/src/.../static/`、`index.html`、WebSocket/WebRTC、DOMPurify XSS 防护、screen/webcam/rtsp 捕获）。

### 发现

- ✅ **XSS 防线扎实（健康项，保持）**
  - `render_markdown.js:128` 用 DOMPurify 白名单（`ALLOWED_TAGS`/`ALLOWED_ATTR` 收紧）+ `rel="noopener noreferrer"`。
  - VLM 决策 token `</silence></response>` 在 parse 前转义；库缺失/出错 fallback 到 `escapeHtml`。
  - `sanitize_static_html.js` 同样 DOMPurify + fallback。
  - `server.py:1103`、`local_file_server.py:92` 设了 CSP；`iframe.srcdoc`（index.html:5647）走 `sanitizeStaticHtml`。
  - 9.4k 行 `index.html` 里的 `innerHTML` 要么是静态图标 `<i data-lucide>`，要么经 `renderMarkdown`/`sanitizeStaticHtml` 清洗。
- ⚠️ **0 前端测试（与测试角色共担）**：CI 仅 eslint，9.4k 行命令式 UI 裸奔，无单测/集成守护。
- ℹ️ **ruff 不覆盖 JS**：本次探针是 Python 工具，前端静态 JS 的盲异常未被覆盖；CI 的 eslint job 也未配安全规则（S 等价项）。
- ℹ️ **已知非本次范围**：来自前端专项审查（`reports/frontend-review-20260723.md`）——CSS 内联（3 style 块 + 78 硬编码 hex）、a11y 浅（16 aria-* / 1 tabindex，WCAG 2.1 AA 未达标）、无构建/TS/框架（0 `type=module`、0 `import()`）。

### 该做的事（前端建议）

| 优先级 | 建议 | 说明 |
|---|---|---|
| 保持 | 守住 XSS 白名单纪律 | 任何新增 `innerHTML` 路径必先过 `renderMarkdown` / `sanitizeStaticHtml`；CSP 头勿删 |
| P0（协作） | 与测试角色补前端测试底座 | 至少覆盖消息渲染 / 捕获控制 / WebSocket 协议解析，让 9.4k 行 UI 有回归守护 |
| P1（可选） | 推 CSS 令牌外置 + WCAG a11y pass | 详见前端专项报告，不推荐 React 整体重写 |

---

## 2. 后端（joyai-backend 读这章）

**范围**：所有 Python 微服务（`webinfer` / `webui` 服务端 / `asr` / `tts` / `voice-clone` / `memory-store` / `background-agent` / `kws-training`）+ 服务内脚本。

### 发现（生产代码高价值缺陷，已绕过 ignore 暴露）

统计口径：非测试代码（`/tests/`、`test_*.py` 已排除）；`S101` 在测试里合理，此处只计生产路径。

**🔴 Medium-High — 正确性与可观测性**

- **BLE001 盲 `except Exception`：生产 ~104 处**
  | 服务 | 数量 | 代表位置 |
  |---|---|---|
  | webui（服务端） | 77 | `server.py`、`vlm_service.py`、`background_model.py` 等请求处理 |
  | webinfer | 16 | `app.py`、`memory_summarizer.py`、`infer_loop.py` |
  | background-agent | 5 | `codex_api/main.py:141,254,410`、`hermes_api/main.py:111,262` |
  | scripts | 3 | `verify-services.py` 等 |
  | tts / memory-store / kws-training | 各 1 | — |

  > **最该修的一处**：`background-agent/hermes_api/main.py:262` —— `_enrich_with_memory` 用 `except Exception: return ""` **吞掉所有 recall 失败**（网络/超时/4xx/JSON 错）。后果：memory-store 挂了或慢了，`[Local Wiki]` 静默降级（hermes 自行决定是否联网搜），**零日志、零指标**。该模块连 `import logging` 都没有。checklist 明确要求"不得静默改变行为"。→ 至少 `logger.warning("Local Wiki recall failed: %s", err)`；传输层错误与 `status>=400` 显式返回 `""`（已做，:252）分开处理。

- **S101 `assert` 出现在生产路径：14 处**
  - `asr/jarvis/asr.py:104-106`、`asr/jarvis/kws.py:187-189`（6）
  - `background-agent/codex_api/main.py:210,221,235`（3）
  - `kws-training/export_kws_onnx.py:177,310`（2）
  - `webinfer/app.py`、`memory_summarizer.py` 等（2）
  - `webui` 生产代码（1）
  > `python -O` 会剥掉 `assert` → 生产校验被悄悄关掉。改为显式 `if not x: raise ValueError(...)`，或仅留在测试里。

**🟠 Medium — 安全 / 资源**

- **S104 绑定 0.0.0.0（所有网卡）：4 处**
  - `asr/asr_adapter.py:348,380`、`tts/tts_adapter.py:496,540`
  > 本地助手若需 LAN 访问可接受，但应可配置（默认 `127.0.0.1`）并写进文档，避免误暴露。

- **S108 硬编码 `/tmp/...` 模型/缓存路径：8 处**
  - `webinfer/adapter_types.py:52,54,86`、`app.py:138,151,270`、`memory_summarizer.py:294`、`webui/background_model.py:68`
  > 全部是 `/tmp/models/Qwen3-VL-4B-Instruct`、`/tmp/streaming_adapter_frames`。**直接违反本项目"缓存→workspace/.cache/"的隔离纪律**（见 MEMORY），且多用户主机上可预测 `/tmp` 路径有 symlink 攻击面。→ 改为 `env` 可配，默认指向 workspace 本地缓存。

- **S110 `try-except-pass` 吞异常：7 处**
  - `webui`（5，含 `server.py`、`vlm_service.py`）、`webinfer`（1）、`memory-store/src/.../sqlite_backend.py:184`
  > 静默吞掉、无日志。至少 `logger.debug/warning`。

- **S112 `try-except-continue` 吞异常：2 处**
  - `webui/src/joy_interaction_webui/server.py:371`、`vlm_service.py:665`
  > 同上，跳过前记一笔日志。

- **B019 实例方法上用 `lru_cache`/`cache`：3 处**
  - `kws-training/kws_data_module.py:80,89,94`
  > 每个实例把缓存绑在 `self` 上 → 跨实例内存泄漏（baseline §4 所列的 3×，但位置在 kws 不在 memory-store）。→ 提到模块级缓存，或改成以参数（非 self）为键的缓存。

**🟡 Low-Medium — 死代码 / 次要**

| 规则 | 数 | 位置 | 说明 |
|---|---|---|---|
| F841 死变量 | 3 | `kws-training/export_kws_onnx.py:238 token_table`、`scripts/record_kws_corpus.py:146 dt`、`scripts/test_jarvis_kws_e2e.py:80 logger`(测试) | 前两个可能藏逻辑 bug，确认意图 |
| B007 未用循环变量 | 1 | `scripts/analyze_kws_captures.py:64 duration` | 疑似笔误 |
| S310 URL open scheme | 2 | `scripts/verify-services.py:32,36` | 内部服务探测，低风险 |
| S311 弱随机数 | 1 | `scripts/prep_kws_data.py:70` | 非加密用途，低风险 |

### 健康项（后端值得肯定）

- ✅ **`memory-store/app.py` 错误链正确**：`except NotImplementedError as exc: raise HTTPException(...) from exc` —— 保留因果链（正是 B904 要的写法，已做对）。
- ✅ **webinfer 上下文溢出修复（#22）正确且有测试**：`memory_io.py:163-165` 按 `qa_history_window` 丢最旧；`summarizer_routing.py:190-212` 按 `long_term_memory_max_tokens` 预算重建；`main_ctx_tokens=16384` 硬兜底。6 个回归测试（`test_context_overflow_bounds.py`）覆盖窗口/预算/`window==0` 三路径。

### 该做的事（后端建议）

| 优先级 | 建议 | 对应发现 |
|---|---|---|
| P1 | `hermes_api/main.py:262` 召回失败加 `logger.warning`（先 `import logging`） | BLE001 最该修处 |
| P1 | 14 处生产 `assert`(S101) 改显式 `raise` | S101 |
| P1 | `B019` 3 处提到模块级缓存 | kws_data_module.py |
| P2 | `S104` bind 改为可配，默认 `127.0.0.1` | asr_adapter / tts_adapter |
| P2 | `S108 /tmp` 改 `env` 可配，默认指向 workspace `.cache/` | webinfer / webui |
| P2 | `S110`/`S112` 吞异常处补 `logger` | webui / webinfer / memory-store |
| P3 | 核查 F841/B007/S310/S311 是否藏逻辑 bug | 脚本类 |

---

## 3. 测试（质量门禁 / 覆盖率 读这章）

**范围**：pytest 门禁、前端测试、覆盖率、CI 信号有效性。

### 发现

- ✅ **pytest 门禁在跑**：memory-store 16 + background-agent 7 + webinfer ~99（webinfer 由 PR #23 加进矩阵后真守护）。
- ⚠️ **0 前端测试（与前端角色共担）**：CI 仅 eslint，9.4k 行命令式 UI 无单测/集成守护。
- ⚠️ **CI 信号被稀释（与架构角色共担）**：`S`/`BLE` 不在 `select`，`B904/B019/B007` 被 `extend-ignore` 压掉 → 104 盲异常 / 8 `/tmp` / 4 bind 对门禁不可见，测试信号无法反映真实质量。
- ⚠️ **半门禁蒙混**：`ruff format --check` 与 `ruff check` 分两道跑，但本地常被只跑 `ruff check` 蒙混（历史 PR #11 红门禁教训）。

### 该做的事（测试建议）

| 优先级 | 建议 | 说明 |
|---|---|---|
| P0（协作） | 补前端测试底座 | 与前端角色协作，至少覆盖消息渲染 / 捕获控制 / WS 协议解析 |
| P0（推动） | 推动架构角色把 `S`+`BLE` 加进 `select` | 否则 pytest + ruff 守护不到安全/盲捕获类缺陷 |
| P1 | 确保 `scripts/quality-check.sh --fix` 同时跑 `ruff check` **和** `ruff format --check` | 杜绝半门禁，避免 PR #11 类回滚 |
| P2 | 考虑把 KWS/ASR 服务也纳入 pytest 矩阵 | 当前矩阵仅 memory-store/background-agent/webinfer |

---

## 4. 架构（joyai-devops + 架构文档 + 仓库流程 读这章）

**范围**：CI 门禁配置（`pyproject.toml` / `quality.yml`）、ruff 基线、文档一致性、分支/PR 流程。

### 发现

- 🔴 **CI 门禁盲区（最该先修）**
  | 问题 | 证据 | 影响 |
  |---|---|---|
  | `S`（安全）与 `BLE`（盲异常）**根本不在** repo `[tool.ruff.lint].select` | `pyproject.toml` 选了 `E,F,W,I,UP,B,C4,SIM,N,RUF,D`，**无 `S`/`BLE`** | 所有安全/盲捕获缺陷对门禁透明 |
  | `B904/B019/B007` 被各服务 `extend-ignore` 压掉 | `memory-store` 的 CI `ruff check` 产出 0 个 B 类告警（实测），但 baseline 声称有 B904 | 正确性高优项不报错 |
  | `ruff format --check` 与 `ruff check` 分两道跑，本地常只跑 `check` 蒙混 | 见历史 PR #11 红门禁教训 | 格式门禁形同虚设 |

- ⚠️ **文档漂移**
  - `doc/standards/lint-baseline.md` §4 写"`B904` @ `memory-store/app.py:85,95`"——**实测该处为 `except NotImplementedError as exc: raise HTTPException(...) from exc`，正确无 B904**。baseline 已漂移，建议重生成。
  - §4 的 `B019 3×` 实际在 `kws-training/kws_data_module.py`（见后端 §2），不在 memory-store。

- ⚠️ **仓库保洁（陈旧分支）**：`git cherry`（patch-id）核实 6 个"未合并"远端分支实为已 squash 合入的重复/分叉分支：
  | 分支 | 状态 | 处理 |
  |---|---|---|
  | `ci/add-pytest-gate` | 已合入（#18）重复 | 删远端 |
  | `ci/webinfer-pytest-matrix` | 已合入（#23）重复 | 删远端 |
  | `ci/webui-ruff-config-and-doc-paths` | 已合入（#10/#12）重复 | 删远端 |
  | `fix/background-agent-test-ruff` | 已合入重复 | 删远端 |
  | `fix/webinfer-context-overflow-bound` | #22 的旧/被取代版本 | 删远端 |
  | `docs/mem-hermes-audit-align` | 与 #21 分叉的重复分支 | 丢弃，勿合 |

  > 根因：多对话并行 + squash-merge 导致远端堆积分叉/重复分支。建议合完即删远端分支，或加一条 `branchclean` 流程。

- ℹ️ **workflow 触发失灵历史**：PR #13–#17 因 force-push 分支 `refs/pull` 卡死 + GitHub 偶发不投递 `pull_request` 事件；已在 `quality.yml` 加 `workflow_dispatch:` 作确定性兜底（PR #23）。推 workflow 文件须走 fine-grained PAT（workflow scope）。

### 该做的事（架构建议）

| 优先级 | 建议 | 对应发现 |
|---|---|---|
| P0 | repo `select` 增加 `S` 与 `BLE`（或先 `S3xx`/`BLE001`） | CI 盲区 |
| P0 | 移除各服务 `extend-ignore` 中的 `B904/B019/B007`，改为真正修掉 | CI 盲区 |
| P0 | `quality-check.sh --fix` 同时跑 `ruff check` + `ruff format --check` | 半门禁 |
| P3 | 重生成 `lint-baseline.md`（B904 位置 + B019 落点纠正） | 文档漂移 |
| P3 | 删除 §4 表格 6 个陈旧远端分支 + 加 `branchclean` 流程 | 仓库保洁 |

---

## 5. 建议落地顺序（跨角色汇总）

1. **P0（架构 + 测试）**：CI `select` 加 `S`+`BLE`；各服务 `extend-ignore` 去掉 `B904/B019/B007`；`quality-check.sh` 双跑 `ruff check`+`ruff format --check`（架构）。同步补前端测试底座（前端 + 测试协作）。
2. **P1（后端）**：`hermes_api/main.py:262` 召回失败加日志；生产 `assert`(S101) 14 处改显式 raise；`B019` 3 处提到模块级缓存。
3. **P2（后端）**：`S104` bind 可配默认 127.0.0.1；`S108 /tmp` 改 workspace 本地缓存 env；`S110/S112` 补日志。
4. **P3（架构）**：重生成 `lint-baseline.md`；删除 6 个陈旧远端分支 + 加 `branchclean`。

---

## 附录：探针命令（可复现）

```bash
# 用 pinned ruff 0.15.22，绕过 ignore 暴露高价值项
RUFF=D:/AI/ruffmig/bin/ruff.exe
HV="B904,B019,B007,B011,B006,S,BLE,C4,UP006,UP007,PL,RUF,F841,F821"
for d in services/*/; do
  $RUFF check "$d" --select "$HV" \
    --config "lint.ignore=[]" --config "lint.extend-ignore=[]" \
    --output-format concise
done
# 生产过滤（去测试）：tr '\\' '/' | grep -vE '/tests/|/test_'

## 验证（测试对话，2026-07-24）

> 验证者：测试对话（独立复现，不写业务代码）
> 靶子：同 main @ 3fed7f8
> 方法：复用附录探针（pinned ruff 0.15.22），修正 Windows 反斜杠路径过滤

### 修正点（重要）
原附录过滤 `grep -vE '/tests/|/test_'` 在 **Windows 上失效**——ruff 输出反斜杠路径（`services\webui\tests\...`），正斜杠 pattern 匹配不到，测试代码会混入。正确做法：先 `tr '\\' '/'`，再 `grep -vE '/tests/|/test_'`。

- 未修正：1856 行（含测试）
- 修正后：**934 行**（生产代码）

### 对账结果

| 规则 | 报告声明 | 实测（生产） | 结论 |
|------|----------|--------------|------|
| BLE001 盲 except | ~104 | **106** | ✅ 一致（差 2 可忽略） |
| S104 bind 0.0.0.0 | 4 | 4 | ✅ 一致 |
| S108 /tmp | 8 | 8 | ✅ 一致 |
| S110 try-pass | 7 | 7 | ✅ 一致 |
| S112 try-continue | 2 | 2 | ✅ 一致 |
| B019 实例缓存 | 3 | 3 | ✅ 一致 |
| S310 URL open | 2 | 2 | ✅ 一致 |
| B904 | 无实锤 | 0 | ✅ 一致 |
| S106 | — | 0 | ✅ 无 |
| **S101 assert** | **14** | **97** | ⚠️ **报告严重少报** |
| **S311 弱随机** | **1** | **13** | ⚠️ **报告少报** |
| **B007 未用循环变量** | **1** | **3** | ⚠️ 报告少报 |
| **F841 死变量** | **3** | **5** | ⚠️ 报告少报 |

### 重点确认：hermes_api:262 静默吞错 ✅
直读 `services/background-agent/hermes_api/main.py:262`：
```python
    except Exception:
        return ""
```
`import logging` 缺失；网络超时 / 连接拒绝 / JSON 错 / 5xx（252 行已处理 `>=400`，但 5xx 落在 try 内）→ **全部静默转 `""`**，零日志零指标。`[Local Wiki]` 静默降级成立。报告"最该修的一处"坐实。

### 结论
- 报告**核心结论成立**：BLE001 盲异常 ~104 属实、CI 盲区（S/BLE 不在 select）属实、hermes_api:262 静默吞错属实。
- **修正报告尺度**：S101 / S311 / B007 / F841 四项报告少报，实际生产缺陷比报告写的更多 → 后端 P1 修复清单应扩容（尤其 **S101 97 处生产 assert 在 `python -O` 下全部失效**，比报告估计的 14 严重得多）。
- 验证原始数据：`D:/AI/workspace/JoyAI-VL-Interaction-main/.workbuddy/tmp/ruff-probe-112845.txt`

```
