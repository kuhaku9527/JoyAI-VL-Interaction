# ADR 0001 — 声音克隆走 MiniMax Rapid Clone 同步路径

- **状态**：Accepted
- **日期**：2026-07-11
- **作者**：Codex

## 背景

用户在 2026-07-11 提出："文档好像有更好的，不走快速克隆，有异步生成啊是不是更适合我们？"
需要审视：BT 实时对话场景下，"异步 TTS 生成" 是否值得从 Rapid Clone 改到 `/v1/t2a_async_v2`。

## 决策

**继续走 MiniMax Rapid Clone（`/v1/voice_clone`）的同步路径**，**不**改用 `/v1/t2a_async_v2` 异步路径。

## 论证

| 维度 | Rapid Clone 同步 | `/v1/t2a_async_v2` 异步 |
| - | - | - |
| 端点 | `POST /v1/voice_clone` | `POST /v1/t2a_async_v2` + 轮询 |
| 用例 | **克隆声音**（创建/刷新 voice）| **长文 TTS**（单段 > 10k 字符）|
| 延迟 | < 1s | 几秒到几十秒 |
| 实时对话 TTFB | **< 300ms（SSE 流式 `/v1/t2a_v2`）** | 必须等整段完成才能下 |
| 与流式冲突 | 不冲突 | 冲突（polling + 下载 + 解码）|

核心点：
1. **根本没有"异步克隆"端点** —— MiniMax 文档里的 async 指的是 `t2a_async_v2`（长文合成），跟克隆无关
2. 对话每段 < 200 字，**整段合成时间 < 1.5s**，异步 polling + 下载 mp3 + 解码三次操作**总延迟更长**
3. 真正可用的"加速"是**预热**：start-joyai 启动时，如有 voice 缓存 + 上次调用 < 7 天，主动 ping 一次刷新，把 7 天过期窗口推前

## 后续修订

### 2026-07-11 凭证体系修正

MiniMax 的 **订阅 Key** `sk-cp-*` 与 **按量付费 API Key** `sk-api-*` 是两套独立凭据，不能互相替代其计费来源。
但本次对用户 Token Plan Key 的真实探针显示，`sk-cp-*` 可以认证 `POST /v1/get_voice` 与 `POST /v1/t2a_v2`。
早前“`sk-cp-*` 不能调 get_voice”的判断已废弃。

当前权威记录见 `doc/voice-clone.md` §15.9。

## 后果

- `voice_clone_api.cloud_clone` 维持现状（`/v1/voice_clone` 同步 + `/v1/t2a_v2` SSE 流式）
- 新增可选 start-joyai 预热逻辑（见 ADR 0004）
- 文档 `doc/voice-clone.md` §12 已经是这个结论，不需要改写
