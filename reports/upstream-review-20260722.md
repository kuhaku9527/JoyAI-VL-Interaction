# 上游 `jd-opensource/JoyAI-VL-Interaction` 调研 — 2026-07-22

> 范围:仅参考仓库 `https://github.com/jd-opensource/JoyAI-VL-Interaction`(public, 1399 ⭐, Python 主语, 9324 KB)。**不动本项目代码、不改 fork**,仅作调研与可行性评估。  
> 数据来源:GitHub REST API 直查 + `raw.githubusercontent.com` 文件内容抓取(未认证,公开 API 视角)。  
> 本地参考:`.workbuddy/memory/MEMORY.md` + `2026-07-22.md` + `reports/architecture-review-20260722.md`(本仓库 7/22 架构 review)。

---

## 1. 调研目的

fork `kuhaku9527/JoyAI-VL-Interaction` 是基于上游 `jd-opensource/JoyAI-VL-Interaction` 的私有 fork,本仓库当前主战场是 **CI 门禁 + 前端模块化 + ruff 烧债**(见 `MEMORY.md` 长期记忆);memory 截止 7/22 20:19,后端对话 Phase 1+2 推不出去(fine-grained PAT 不可用、gh OAuth token 无 workflow scope)。

本次调研目的:在不动 fork 源码的前提下,摸清**上游这 2–3 周的更新内容**,识别哪些是**可借鉴的真优化**,哪些是**表面热闹但不该抄**的(LiveKit、整 Docker 化)。

---

## 2. 上游 2–3 周变更时间线

| 日期 (UTC) | SHA | 作者 | 类别 | 摘要 |
|---|---|---|---|---|
| 7/22 09:01 | `452e147` | cyuQ1n | 文档 | docs: correct benchmark count in Chinese README |
| 7/22 07:11 | `07d1f38` | Qingyi Si (PhoebusSi) | 文档 | Update README.md |
| 7/22 07:06 | `14ad99f` | Qingyi Si | 文档 | Update README.md |
| 7/22 05:38 | `89fd543` | cyuQ1n | **模型** | release: update model path and add Qwen3-VL benchmarks |
| 7/22 05:37 | `f4f2a61` | ydyhello | 文档 | docs: update unified model defaults |
| 7/21 18:21 | `002d3f8` | frankjoey2048 | **部署** | docs: document LiveKit deployment option |
| 7/21 17:29 | `12db533` | frankjoey2048 | 文档 | docs: add bilingual navigation and deployment tuning |
| 7/21 17:09 | `332ac2e` | frankjoey2048 | 文档 | docs: mark optimized inference configs complete |
| 7/21 17:08 | `745c2a6` | frankjoey2048 | 文档 | docs: remove RTX optimization announcement |
| 7/21 17:05 | `60b117d` | frankjoey2048 | 文档 | docs: highlight optimized RTX 3090 and 5090 profiles |
| 7/21 17:04 | `bcfab44` | frankjoey2048 | **部署** | feat: release Docker deployment for RTX 3090 and 5090 |
| 7/21 07:54 | `fb0312e` | ydyhello | **运行时** | Add service startup and smoke warmup helpers |

**Open PR(5 个,社区贡献,跟本 fork 工作无关):**

- #25 wilhelm-tiger — **Fix unbounded context growth in long streaming sessions (`qa_history` + `long_term_memory`)**(base `main`,head `fix-long-session-window-issue`,**真 bug 修复,值得同步**)
- #28 MayVerse4 — 同样 context 溢出问题的另一种实现
- #29 MayVerse4 — feat: add LLaMA-Factory weighted SFT loss integration
- #30 MayVerse4 — 提建议建交流群
- #31 structDream — Feat/for webide

**分支现状:**

- `main`(48 commit,生产)— 含 `container/`、`services/`、双语文档
- `livekit` — **落后 main 7 commit**,ahead 2 commit。本质是 "main 减去 `container/` 再加 LiveKit 相关脚本改" 的混合体
  - `services/webui/scripts/start_server.sh`:**+159 / −15**(可能含 LiveKit WebRTC 集成)
  - `services/webui/src/.../server.py`:**+269 / −150**
  - `services/webui/src/.../video_processor.py`:**+266 / −278**
  - `services/webinfer/live_adapter.py`:**+3 / −40**(净删多)
  - `install/install.sh`:**+72 / −23**
  - 无任何 LiveKit 专用文件(后端依赖直接走 `livekit` pip 包)
  - README 自带警告: **"this branch may not be maintained long term"**

---

## 3. 上游架构/端口表(以 `doc/architecture.md` 为准)

```
                          ┌──────────────────┐
                          │   webinfer       │
                          │  (Core VLM API)  │
                          │   :8070          │
                          └────────▲─────────┘
                                   │
┌────────────┐   ┌────────────┐    │    ┌────────────────────┐
│  asr       │   │  tts       │    │    │ background-agent   │
│  :8994     │   │  :8992     │    │    │ :8079              │
└─────▲──────┘   └─────▲──────┘    │    └──────────▲─────────┘
      │                 │           │               │
      └─────────────────┴───────────┼───────────────┘
                                    │
                          ┌─────────┴────────┐
                          │     webui        │
                          │  (Browser + WS)  │
                          │   :8099          │
                          └──────────────────┘
```

**官方端口表:**

| Port | Service | Protocol |
|---:|---|---|
| 7060 | webinfer (main VLM vLLM) | HTTP (internal) |
| 8065 | webinfer (summary VLM vLLM) | HTTP (internal) |
| 8070 | webinfer (adapter) | HTTP |
| 8079 | background-agent | HTTP |
| 8099 | webui | HTTPS + WebSocket |
| 8991 | tts (vLLM-Omni) | HTTP + WebSocket (internal) |
| 8992 | tts (adapter) | HTTP + WebSocket |
| 8993 | asr (vLLM ASR) | HTTP (internal) |
| 8994 | asr (adapter) | HTTP + WebSocket |

**GPU 分配(default):**

| GPU | Service | util |
|---:|---|---:|
| 0 | main streaming model (vLLM, 7060) | 0.9 |
| 1 | summary model (vLLM, 8065) | 0.9 |
| 2 | ASR model (vLLM, 8993) | 0.3 |
| 2 | TTS model (vLLM-Omni, 8991) | 0.6 total deploy budget |

ASR + TTS 共用 GPU 2,总预算 0.9。

---

## 4. PR #25 长会话上下文溢出修复(真 bug,可借鉴)

**作者:** wilhelm-tiger(已签名 GPG 验证)  
**Base:** `main`  
**Files changed:** `services/webinfer/live_adapter.py` (+70 / −4), `.gitignore` (+2)  
**Repo link:** https://github.com/jd-opensource/JoyAI-VL-Interaction/pull/25

### 4.1 根因 1:`qa_history` 无界增长

`archive_chunk_response_records()` 把每对 query/response 都 append 到 `memory_state["qa_history"]`,整 session 不淘汰;`build_dynamic_system_content()` 每次主模型 prompt 都把 `qa_history` 全文塞进去。

实测:turn 119 时涨到 5889 input tokens,撑爆 6144 token context。

对照:`long_term_history` 已经通过 `long_term_memory_window` 限了窗口,**`qa_history` 没享受同等待遇**。

**修复:** `archive_chunk_response_records()` 新增 `window: int = 0` 参数,超过则 trim 到最近 N 条。

```python
# live_adapter.py:449
def archive_chunk_response_records(
    ...,
    chunk_index: int = 0,
    before_time_sec: float = float("inf"),
    window: int = 0,
) -> None:
    ...
    # Unlike long_term_history, qa_history previously had no eviction at all:
    # every query/response pair ever seen in the session was kept and resent
    # in full on every subsequent turn, so a long enough session always
    # eventually overflows the main model's context window regardless of
    # max_model_len. Bound it the same way long_term_history is bounded.
    qa_history = memory_state["qa_history"]
    if window > 0 and len(qa_history) > window:
        del qa_history[: len(qa_history) - window]
```

### 4.2 根因 2:`long_term_memory` 只 append,不 re-compress

`batch_compress_to_longterm()` 的 docstring 自己写着:

> "Only the new mid-term summaries are compressed (existing long-term is NOT re-compressed), then appended to the existing block."

每个 long-term 压缩 batch 仅 append 到 `long_term_memory`,**永不重压缩降阶**。`long_term_memory_window` 只限 batch **数**,不限 batch 累计 **token 数**;`long_term_max_tokens` 是单次生成上限,不是累计上限。

实测:5 batch 涨到 ~11k tokens,远超大模型 context window。

**修复:** `_compress_mid_terms()` 新增 token budget 强约束,drop 最旧 batch 直到重建后的 `long_term_memory` 文本塞得下预算。

```python
# live_adapter.py:1743
window = int(self.config.long_term_memory_window or 0)
token_budget = int(self.config.long_term_memory_max_tokens or 0)

def _rebuild_long_term_memory() -> str:
    return "\n\n".join(
        entry["compressed_text"].rstrip()
        for entry in state.long_term_history
        if entry.get("compressed_text")
    )

trimmed = False
if window > 0 and len(state.long_term_history) > window:
    dropped_count = len(state.long_term_history) - window
    del state.long_term_history[:dropped_count]
    trimmed = True

if token_budget > 0:
    while (
        len(state.long_term_history) > 1
        and self.summarizer.estimate_tokens(_rebuild_long_term_memory())
        > token_budget
    ):
        del state.long_term_history[0]
        trimmed = True

if trimmed:
    state.memory_state["long_term_memory"] = _rebuild_long_term_memory()
    token_count = self.summarizer.estimate_tokens(
        state.memory_state["long_term_memory"]
    )
```

### 4.3 新增 `AdapterConfig` 字段

```python
qa_history_window: int = 40
long_term_memory_max_tokens: int = 4000
```

CLI 接入:

- `--qa-history-window` / env `QA_HISTORY_WINDOW`(默认 40,`0` 禁用 = 旧行为)
- `--long-term-memory-max-tokens` / env `LONG_TERM_MEMORY_MAX_TOKENS`(默认 4000,`0` 禁用)

### 4.4 调用点改动(下游接线)

三处需要传 `window=self.config.qa_history_window`:

1. `_flush_session_outputs(self, state)`(line 962)
2. `_handle_chat_payload(...)` 中的 archive 调用(line 1146)
3. `_execute_pending_qa_archive(self, state)`(line 1479)

### 4.5 上游实测数据(L40S / AWS g6e.2xlarge)

| 配置 | 表现 |
|---|---|
| 仅 fix 1 | turn 300+(原 turn 119 失败) |
| fix 1 + fix 2 | `long-term compression batch=1 tokens=4013, batch=2 tokens=4014` 稳定 plateau;原 965→11316 单调增长;turn 200+ 零 context-length 错 |

**注意:** plateau 停在 ~4000 而非 3000(单 batch 已接近 4000,trimming 永不降到 0 batch)。进一步压低需要调 `--long-term-max-tokens`(单次生成上限,跟本 PR 独立)。

### 4.6 对本 fork 的可移植性

本 fork 在 `2dacfa5` 拆完 `live_adapter.py` 后(见 MEMORY 长期记忆,9 子模块 + 53 行门面),PR #25 的修复**逻辑可直接移植**,但需要先定位:

- `archive_chunk_response_records` 落到哪个子模块?(大概率在 `live_adapter_core.py` 或 `coordinator` mixin)
- `_compress_mid_terms` / `_flush_session_outputs` 落在 `memory_summarizer.py` 改写后的哪个文件?
- `AdapterConfig` dataclass 在 `adapter_config.py`?
- `parse_args` 在 `cli.py`?

**本调研不动代码**,仅指出可同步点。后续若用户授权,可以做一次纯只读的 grep 定位(不修不改)。

---

## 5. smoke warmup 借鉴(`services/webinfer/smoke.py`,108 行)

### 5.1 解的什么坑

vLLM 第一次推理会触发 CUDA kernel JIT 编译,常见 20–30s 延迟。肉眼看像"服务起了但首请求卡死"。

本 fork `start-joyai.ps1` 缺这步;上游的解法是启 vllm 后、起 webui 前,先发一个 dummy `/v1/chat/completions` 请求,触发 JIT 预热。

### 5.2 实现要点

- **依赖最小化**:用标准库 `urllib.request`,**不引入 `requests` / `httpx`**(轻,跟 vllm 部署解耦)
- **占位图最小化**:1×1 白底 PNG,inline `data:image/png;base64,...`(35 字符,见 `WHITE_PNG_DATA_URL`)
- **`argparse` subparsers** 区分 `main-vlm` / `summary` 两种 kind
- **重试参数化**:`--attempts 60 --interval 2.0 --timeout 60`
- **走 OpenAI 协议**:`POST {api_base}/v1/chat/completions`,`Authorization: Bearer {api_key}`(vllm 默认 `EMPTY`)
- **可观测输出**:`main-vlm smoke: completed in 2341.7ms (model=joyai-vl-interaction, response='OK')`

### 5.3 与 start 脚本接线

`fb0312e` 改动的 19 个文件里,核心是 `start_model.sh / start_summary_model.sh / start_adapter.sh / start_all_models.sh / start_server.sh` 这 5 个 start 脚本都在 vllm 起来后调一次 `python3 smoke.py main-vlm --api-base ... --model ...`(类似形式),等返回 0 再启下一个。

### 5.4 本 fork 落地建议

写一个等价 `scripts/smoke.py`(urllib,不要 requests 依赖),preload main-vlm + summary 两个 endpoint。`start-joyai.ps1` 改为:起 vllm → `python smoke.py main-vlm` → `python smoke.py summary` → 起 webui(每步成功才往下走)。文件粒度保持跟上游一致(单文件、argparse),方便后续做 PR 同步。

---

## 6. 端口表差异(本 fork vs upstream)

| 服务 | upstream (`container/README.md`) | 本 fork (memory) | 差 |
|---|---|---|---|
| main vLLM | 7060 | 7060 | ✓ |
| summary vLLM | **8065** | 未标 | 新端口 |
| webinfer adapter | 8070 | 8070 | ✓ |
| webui | 8099 | 8099 | ✓ |
| ASR model | **8993** | 未标 | 新端口 |
| ASR adapter | **8994** | 未标 | 新端口 |
| TTS model | **8991** | 未标 | 新端口 |
| TTS adapter | **8992** | 8985 | **差 6** |
| background-agent | **8079** | 未标 | 新端口 |
| memory-store | (未在 main) | 8996 | fork 自有 |
| voice-clone / TTS | (未在 main) | 8985 | fork 自有 |

**风险:** 本 fork 文档(`doc/adr/0004-*.md`、`reports/architecture-review-20260722.md` 提的"B4 TTS 端口三分裂")跟 upstream 端口表对不齐,外人照 upstream 文档跑会踩坑。

**建议:** 短期不改,只在本 fork `doc/adr/0004-*.md` 加一段 "fork 偏移表" 说明;长期等 fork 走完 CI 门禁后再做端口归一。

---

## 7. vLLM 启动 flag 跟齐

upstream `container/docker-compose.yml` 给主模型 + summary 都开了:

```yaml
--enable-prefix-caching
--enable-chunked-prefill
```

- **prefix-caching**: 重复 system prompt 不重复 prefill,长 system + 重复 query 友好
- **chunked-prefill**: 长输入切片,降低首 token 延迟

vllm 0.22.0(vllm/vllm-openai:v0.22.0 image)默认行为跟 0.6.9 不一样。本 fork vllm 怎么起的(脚本位置待查),需要确认这两个 flag 是否启用。MEMORY 长期记忆里 `fix/adapter-p0-correctness` 重点是决策路径,未提及 vllm 起服务参数——**风险点**。

---

## 8. 部署抽象借鉴(`container/manage.sh` 模式)

upstream `manage.sh` 模式:

```bash
./container/manage.sh 16GB up|down|restart|status|logs|test
```

设计要点:
- **profile 互斥**: 启一个 stop 另外两个(`stop_others()`)
- **`images.lock` 锁全部 image tag**: 比 pip 锁更狠
- **healthcheck 配 vllm 内部 `/v1/models`**: 比外部脚本探测稳
- **`.env` per profile**: GPU / 路径 / 端口全 env 化
- **3 个 profile**(regular / 24GB / 16GB):对应不同硬件预算

本 fork `start-joyai.ps1` 现状: ps1 散落 + 手动 check + 端口散在脚本里。

**借鉴价值(轻量):** 把 profile 概念引进来——本 fork 场景里 profile 可以是 (本地调试 / 单卡 3090 / 4 卡 5090),用 `.env` 切。**不建议**:整 Docker 化(改造成本太高,见 §10)。

---

## 9. 优化建议优先级

| Pri | 项 | 实施成本 | 影响 | 状态 |
|---|---|---|---|---|
| **P0** | 同步 PR #25 长会话上下文修复(2 处) | 中(需要先在 `2dacfa5` 拆分子模块里定位函数) | 高(避免 turn 100+ 必崩) | 待评估 |
| **P1** | 抄 `smoke.py` 给 `start-joyai.ps1` 加首请求预热 | 低(单文件 urllib,改 start 脚本) | 中(消 7060 首请求 20–30s 延迟) | 待评估 |
| **P2** | 端口表 fork 偏移表写入 ADR0004 | 低(纯文档) | 低(防止外人踩坑) | 待评估 |
| **P2** | vLLM 启动 flag 审计(prefix-caching / chunked-prefill 是否启用) | 低(看 start 脚本) | 中(长 prompt 性能) | 待评估 |
| **P3** | 部署 profile 抽象(.env 化) | 中(改 start-joyai.ps1 加载 .env) | 低(切环境更顺) | 待评估 |
| **P3** | `images.lock` 类比(写个 `models.lock` 锁 vllm/ASR/TTS image tag) | 低(单文件) | 低(防漂移) | 待评估 |

---

## 10. 不建议同步的

### 10.1 `livekit` 分支(整支)

- README 自带警告: "this branch may not be maintained long term"
- 落后 main 7 commit
- 表面"feat: add LiveKit streaming support"实际无 LiveKit 专用文件,LiveKit 集成藏在 `start_server.sh +159`、`server.py +269/−150`、`video_processor.py +266/−278` 这些巨大改动的内部
- merge 冲突大、行为风险高、未文档化
- 本 fork 用 WebRTC 直连而非 LiveKit 信令,需求不对位
- **结论: 不动,等真要做 WebRTC 化再单独评估**

### 10.2 整 Docker 化(`container/`)

- 改造成本高(7 个 Dockerfile + 6 个 requirements + 645 行 compose + manage.sh + 3 个 profile)
- vllm 0.22.0 image 替换本 fork 现网 vllm(版本漂移风险,memory 已记录 ruff 0.6.9→0.15.22 教训)
- ASR/TTS/background 三个 adapter 要全 containerize,本地 venv 调试断点没了
- 本 fork 主力用户在 Win 本地(消费级 8B 实时),Docker Desktop for Windows + NVIDIA Container Runtime 链路脆弱
- **结论: 仅抄 smoke warmup + 端口表 + vLLM flag 这三个轻量改进,不抄 Docker 化**

---

## 11. 下一步候选(等用户授权)

1. **PR #25 修复定位**: 纯只读 grep,定位 `archive_chunk_response_records` / `_compress_mid_terms` / `AdapterConfig` / `parse_args` 在 `2dacfa5` 拆分后落在哪个子模块。**不动代码、不改文件**。约 10 分钟工作量。
2. **vLLM flag 审计**: 看 `start_*.sh` / `start_model.sh` 是否启用 `enable-prefix-caching` / `enable-chunked-prefill`,如果没开就列出来。约 5 分钟。
3. **smoke.py 草稿**: 写一个 `scripts/smoke.py` 草稿(urllib + argparse + 1×1 PNG dataURL,跟 upstream 同构),不接 start-joyai.ps1,只做产物。约 15 分钟。
4. **ADR0004 端口偏移表**: 在 `doc/adr/0004-*.md` 追加"fork 偏移表"章节。约 5 分钟。

以上都**不动现有 tracked 代码**;只产新文件(若选 3 / 4)或纯只读调研(若选 1 / 2)。

---

## 12. 参考链接

- 上游仓库: https://github.com/jd-opensource/JoyAI-VL-Interaction
- `main` HEAD (调研时): `452e14723eab95df4fe314f942fa78ca8799d24d` (2026-07-22T09:01:41Z)
- `livekit` HEAD: `e364f2fccd` (fix: align livekit branch with local source tree) — 落后 main 7
- PR #25: https://github.com/jd-opensource/JoyAI-VL-Interaction/pull/25
- `container/README.md` 原文: https://raw.githubusercontent.com/jd-opensource/JoyAI-VL-Interaction/main/container/README.md
- `doc/architecture.md` 原文: https://raw.githubusercontent.com/jd-opensource/JoyAI-VL-Interaction/main/doc/architecture.md
- `services/webinfer/smoke.py` 原文: https://raw.githubusercontent.com/jd-opensource/JoyAI-VL-Interaction/main/services/webinfer/smoke.py
- 本 fork `MEMORY.md`: `.workbuddy/memory/MEMORY.md`
- 本 fork 7/22 架构 review: `reports/architecture-review-20260722.md`

---

**作者**: 主理人  
**日期**: 2026-07-22  
**作用**: 调研产物,不动 fork 代码;下一步等用户挑 11 节的候选动作授权。
