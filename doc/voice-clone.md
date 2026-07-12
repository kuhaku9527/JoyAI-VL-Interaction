# 声音克隆工作流（云端 MiniMax Rapid Clone + 2.8-hd 模型）

> **本项目声音克隆统一走云端 MiniMax Rapid Clone**，不再保留本地 CosyVoice3 实现（已于 2026-07-12 从代码库删除）。
> 配套：`services/voice-clone/README.md`（API 细节）、`doc/tech-local.md` §3.3（旧本地实现，已弃用）。
>
> **2026-07-11 升级**：模型升级到 `speech-2.8-hd`（支持笑声 / 叹息 / 呼吸等语气标签），
> 并启用可选的 `clone_prompt.prompt_audio` 二次提音方案；详情见 §13 / §14。

---

## 1. 一句话总结

`voice_clone_api`（端口 8985）= 声音档案管理 + 流式合成。后端是 **MiniMax Rapid Clone**（云端 API），10 秒参考音频 + 可选 <8s `prompt_audio` 二次提音，无需本地模型。默认合成模型 `speech-2.8-hd`（支持 `(laughs)` 等语气标签）。

## 2. 为什么只用云端

| 维度 | 本地 CosyVoice3（已于 2026-07-12 删除） | **MiniMax Rapid Clone** |
| - | - | - |
| 参考音频 | 3-10 秒 | **10 秒（主）+ 可选 <8s prompt** |
| 相似度 | 主观 3-4/5 | **99%**（开 prompt 后更高） |
| 显存 | 1.1GB | 0 |
| 冷启动 | 5-8s | <300ms |
| 月成本 | 0 | **¥9.9/voice**（Token Plan 套餐内免费）|
| 隐私 | ✅ 全本地 | ⚠️ 参考音频上云 |
| 断网 | ✅ | ❌ |

**结论**：声音相似度 + 0 显存 + 冷启动 0 延迟是硬需求，**云端 MiniMax 全胜**。
本地 CosyVoice3 路径**已于 2026-07-12 从代码库删除**（`voice_clone_api/cosyvoice_client.py` 不复存在；`main.py` 中的 `TTS_PROVIDER=stub` 默认值已移除，缺少凭证会直接 `RuntimeError` 而不是 fallback 到任何本地实现）。

## 3. 工作流（4 步）

### 第 1 步：准备参考音频

**MiniMax 要求**：
- 时长 **10 秒**（±2s 可接受；<5s 相似度骤降，>30s 拒绝；主音源上限 5 分钟）
- 单声道（mono）
- WAV / MP3 / M4A 格式
- ≤ 20MB
- 清晰无背景音乐、无电流声、无回声
- **单人中文字**（不支持多人 / 方言 / 笑声 / 咳嗽）

**录制小贴士**：
- 用 Audacity 录，导出 16kHz mono WAV
- 念一段完整的中文句子（如 BT-7274 风格台词 10 秒）
- 麦克风距离嘴 10-15cm
- 关掉风扇 / 空调
- **避免**笑声、咳嗽、气口明显的片段

**参考音频文案推荐（BT-7274 风格）**：

> 我们的命令是要展开特殊作业二一七。保持通讯畅通，铁御，等我回来。

#### 可选 1.5：上传 prompt audio 二次提音（<8s）

> 这条是**可选**的，仅在追求更高相似度时启用。MiniMax 官方 `clone_prompt.prompt_audio` 字段，
> 与主参考音频（`file_id`）分离；音频必须 < 8 秒，且 `prompt_text` 必须逐字对齐。

```bash
# 1) 上传 prompt 音频（专用 purpose=prompt_audio，端点 /v1/files/upload）
curl -X POST "https://api.minimax.io/v1/files/upload?GroupId=${MINIMAX_GROUP_ID}" \
  -H "Authorization: Bearer ${MINIMAX_API_KEY}" \
  -F "purpose=prompt_audio" \
  -F "file=@D:\AI\workspace\bt-voice\ref_audio\bt_prompt_8s.wav;type=audio/wav"
# 返回 {"file":{"file_id": 987654321}}，记作 PROMPT_FILE_ID
```

效果：开启 prompt 后，BT-7274 这类**机器人 / 角色腔**的尾音、共振峰匹配度更稳。
日常对话可不开（多一次上传 + token 消耗），正式直播 / 演示场景建议开。

### 第 2 步：上传并创建档案（自动调用 MiniMax）

```powershell
curl -X POST http://127.0.0.1:8985/v1/voices `
  -F "name=bt-7274" `
  -F "language=zh" `
  -F "audio=@D:\reference\bt7274_sample.wav;type=audio/wav"
```

`voice_clone_api` 内部自动：
1. 调 MiniMax `/v1/files/upload` 上传参考音频 → 拿 `file_id`
2. （可选 1.5）再调 `/v1/files/upload` 上传 prompt audio → 拿 `prompt_file_id`
3. 调 MiniMax `/v1/voice_clone`，body 含 `file_id` + `voice_id` + `model=speech-2.8-hd` + `language_boost="Chinese"` +（若有）`clone_prompt: {prompt_audio, prompt_text}`
4. **首次合成 1 次免费试听** → 扣 ¥9.9（若不在套餐内）
5. 缓存到 `services/voice-clone/voices/bt7274/` 本地

返回：

```json
{
  "voice_id": "vc_<new-timestamp>_<newhash>",
  "name": "bt-7274",
  "duration_sec": 10.2,
  "sample_rate": 24000,
  "language": "zh",
  "model": "speech-2.8-hd",
  "prompt_audio_used": true,
  "language_boost": "Chinese",
  "created_at": "<ISO8601>",
  "minimax_voice_id": "bt-7274",
  "minimax_expires_at": "<ISO8601+7d>"
}
```

> **2026-07-11 升级提示**：旧的 `vc_20260709_abc123`（或 `vc_1783631940_8f222d56` 这类历史 ID）
> 在重新克隆后会变成**新的** `vc_<new-timestamp>_<newhash>`，因为新流程会同时写新的本地缓存
> + 新调一次 `/v1/voice_clone`。`run-windows.env` 的 `TTS_DEFAULT_VOICE_ID` 必须同步更新。

**关键字段**：
- `voice_id` 是本系统 ID（`vc_<日期>_<hash>`），每次重克隆会刷新
- `minimax_voice_id` 是 MiniMax 云端 ID（我们传 `bt-7274` 固定字符串，便于跨次刷新复用）
- `minimax_expires_at` 是 7 天过期时间（详见 §6）

### 第 3 步：设置默认 voice_id

编辑 `services/scripts/run-windows.env`：

```powershell
# 替换成你刚拿到的 voice_id（新克隆后是新值，见上文提示）
$env:TTS_DEFAULT_VOICE_ID = "vc_<new-timestamp>_<newhash>"
$env:TTS_CLONE_API_URL = "http://127.0.0.1:8985"

# MiniMax API key（必填）
$env:MINIMAX_API_KEY = "eyJhbGciOiJSUzI1NiIs..."
$env:MINIMAX_GROUP_ID = "your-group-id"
```

重启 tts_adapter：

```powershell
.\scripts\run-windows.ps1 -Restart tts-adapter
```

之后所有 TTS 都用这个声线（走 MiniMax 云端合成，`model=speech-2.8-hd`）。

### 第 4 步：测试

在 WebUI 里问一句"你好"，听耳机里出来的声音是不是角色声线。
如果不像：
1. 先看 §5 的 `language_boost=Chinese` / 启用 `prompt_audio`
2. 再看 §9 的故障排查表

## 4. API 端点

| 端点 | 方法 | 用途 | 后端 |
| - | - | - | - |
| `/health` | GET | 探活 + 列 MiniMax 状态 | 检查 `MINIMAX_API_KEY` 是否有效 |
| `/v1/voices` | GET | 列出所有声音档案 | 扫 `voices/` 目录 |
| `/v1/voices` | POST | 上传参考音频 → MiniMax 创建档案 | MiniMax Rapid Clone（`speech-2.8-hd`）|
| `/v1/voices/{voice_id}` | GET | 查档案详情 | 本地 + 调 MiniMax 验证 |
| `/v1/voices/{voice_id}` | DELETE | 删除档案 | 本地 + MiniMax |
| `/v1/voices/{voice_id}/refresh` | POST | 7 天过期后重新克隆 | MiniMax（用缓存参考音频，可复用同一 `voice_id="bt-7274"`）|
| `/v1/synthesize` | POST | 合成（流式或非流式） | MiniMax T2A v2 |
| `/v1/synthesize/ws` | WebSocket | 流式合成（tts_adapter 走这里） | MiniMax T2A v2 WebSocket |

## 5. 质量调优

| 想 | 改 |
| - | - |
| 合成更像 | 参考音频换 10 秒标准朗读（清静环境） |
| 合成更稳定 | 重录参考音频，避免气口 / 停顿 |
| 合成更自然 | MiniMax 端 `temperature` 调小（默认 0.7 → 0.5）|
| **中文发音更准（防串台到英文）** | 合成请求加 `language_boost="Chinese"`（`voice_clone_api` 已默认开）|
| **进一步提升相似度（BT-7274 之类机器人腔强烈推荐）** | 上传 <8s prompt audio，开 `use_prompt_audio=true`（见可选 1.5）|
| **合成支持 `(laughs)` `(sighs)` `(breath)` 等语气标签** | `model=speech-2.8-hd`（`speech-2.6-hd` 不支持）|
| 合成支持情感 | MiniMax Speech 2.8 支持 `emotion` 参数（需 voice_clone_api 透传）|
| 合成速度 | MiniMax 端 `speed_ratio` 调大（默认 1.0 → 1.1）|
| 声音更响 | 后处理 +5dB（在 webui 端做）|

## 6. 7 天保活问题

**MiniMax 限制**：voice_id **7 天不调用自动删除**。

**本项目日常对话频繁，7 天限制基本无影响**。

**冷门角色**（"备而不用"）的保活策略：

| 策略 | 实施 |
| - | - |
| **月度自动保活** | `voice_clone_api` 跑月度 cron（每月 1 日 03:00）→ 自动合成 1 次任意文本触发 |
| **按需重新克隆** | 合成时若 MiniMax 返回 400 "voice not found" → 自动用缓存参考音频重新克隆 |
| **手动保活** | `POST /v1/voices/{voice_id}/refresh` 立即重新克隆 |

参考音频已缓存在 `services/voice-clone/voices/<name>/ref.wav`，重新克隆**不扣费**（首次扣费已在创建时）。
若开启 §1.5 的 prompt audio，保活时也会一并复用，无需重新截取。

## 7. 隐私 / 安全

- **参考音频是个人生物特征**，要妥善保管
- 参考音频 + 可选 prompt audio **会上传 MiniMax 云端**（不可避免，因 MiniMax 需在云端训练 / 检索）
- 本地仅缓存 `services/voice-clone/voices/<name>/ref.wav`（不删除）
- 默认 `voices/` 目录是普通文件夹，建议加 `.gitignore` 规则
- 删除档案用 `DELETE /v1/voices/{voice_id}` → 同时清本地 + 调 MiniMax 删云端

## 8. 多声音切换

```powershell
# 全局切换：编辑 run-windows.env 改 TTS_DEFAULT_VOICE_ID
$env:TTS_DEFAULT_VOICE_ID = "vc_<new-ts>_aaaa"   # 切到角色 A
$env:TTS_DEFAULT_VOICE_ID = "vc_<new-ts>_bbbb"   # 切到角色 B

# 每请求切换：编辑 webui/src/joy_interaction_webui/tts.py 的 build_tts_config
# 加 voice_id 字段（参考 voice-clone worker 报告的"B. 每请求切换"示例）
```

**注意**：切换时 `tts_adapter` 不会自动重置 MiniMax 连接（连接复用），延迟 0。
**注意**：每次重新克隆（哪怕模型或参数变了）都会刷新本系统 `voice_id`，所以升级时记得回头改这条 env。

## 9. 故障排查速查

| 症状 | 检查 |
| - | - |
| `/health` 返回 `status: degraded` | `MINIMAX_API_KEY` 没设 / 过期 / 余额不足 |
| 上传返回 401 | API key 错；检查 `~/.joyai/minimax_creds.json` 或 `run-windows.env` |
| 上传返回 400 "audio too short" | 参考音频 < 5 秒，重录 |
| 上传返回 400 "audio too long" | 参考音频 > 30 秒（主音源）；截断或换 < 5 分钟的更短版 |
| 合成返回 400 "voice not found" | 7 天过期了，调用 `/v1/voices/{voice_id}/refresh` |
| 合成返回 429 | MiniMax QPS 限流，加退避重试（`voice_clone_api` 已实现）|
| 合成不像参考声 | 参考音频有底噪 / 多人 / 方言；重录 10s 干净单人 |
| **合成里出现不该有的 `(laughs)` / `(sighs)` 笑声** | 升级 `model=speech-2.8-hd`；旧 `speech-2.6-hd` 不识别这些 tag（导致字面朗读 "laughs"）|
| **中文发音偏英文 / 串台到英语咬字** | 合成请求加 `language_boost="Chinese"`（`voice_clone_api` 默认已加）|
| **prompt audio 没生效，相似度没提升** | ① prompt 音频 ≥ 8s（MiniMax 拒收）② `prompt_text` 与 prompt 音频逐字对不上 ③ `clone_prompt.prompt_audio` 没塞进 body（看响应 JSON `prompt_audio_used` 字段）|
| **重新克隆后 `voice_id` 变了** | 这是预期的：`vc_<new-timestamp>_<newhash>`；同步改 `TTS_DEFAULT_VOICE_ID` 即可 |
| 合成慢（> 2s） | 网络抖动；`voice_clone_api` 启动时 ping MiniMax 探活 |

## 10. 关键数字

- **样本**：10 秒（主音源），mp3/m4a/wav，≤ 20MB（上限 5 分钟）
- **价格**：**¥9.9 / 被接受的 voice**（首次合成时扣费；试听不扣）
- **套餐**：Token Plan Max ¥119 套餐赠额内**免费**（1:1 折算积分）
- **限制**：7 天不调用就**自动删除**（频繁对话场景无影响）
- **模型版本**：`speech-2.8-hd`（v2.6 仍支持但**新项目用 2.8**，2.8 才支持语气标签）
- **prompt audio**：<8s 可选，进一步提升相似度（同 voice 复用、不再扣费）
- **`language_boost`**：`"Chinese"` 显式标注（防 auto-detect 漂移）

## 11. 弃用 / Legacy 说明

**2026-07-12 更新**：本地 CosyVoice3 实现已**删除**，不再是"保留但不再调用"的 dead-code 状态。

- ~~**本地 CosyVoice3 路径已弃用**（2026-07-09 决策）~~ → **已删除**（2026-07-12）
- `voice_clone_api/cosyvoice_client.py` 文件已删除；`voice_clone_api/main.py` 中所有 cosyvoice provider 分支、`_stub_synthesize` 烟雾路径、`_stream_synthesize` SSE helper 全部清除；`create_app` 不再接收 `cosyvoice` 形参
- 缺失 `MINIMAX_API_KEY` / `MINIMAX_GROUP_ID` 会触发 `RuntimeError`（过去会 silent fall back 到 stub）
- **`TTS_PROVIDER`** 现在只接受 `minimax`；传 `cosyvoice` 或 `stub` 会 `ValueError`
- 不再有"本地 fallback"。断网场景请走 `tts-adapter` + MiniMax 代理或直接失败
- **`speech-2.6-hd` 已标 legacy**（2026-07-11 升级 2.8 后）：仅在确实不支持 2.8 的旧账户回退时短暂使用，正式项目统一 `speech-2.8-hd`
- 旧文档中的"双轨方案 / hybrid"不再适用
- 重新克隆（哪怕参数只变了 `model` 或 `language_boost`）会刷出新的 `voice_id`，
  这是 MiniMax 本地缓存协议的设计；不是 bug

---

## 12. Sync vs Async 决策（2026-07-11 更新）

**核心结论**：**MiniMax Rapid Clone（`/v1/voice_clone`）= 同步、单次 HTTP 返回 voice_id**。
**不存在"异步克隆"端点**。MiniMax 文档里出现的 "async" 是另一个端点 `/v1/t2a_async_v2`，
跟克隆**无关**，仅供超长文本（≤ 1M 字符）T2A 合成走轮询。

| 维度 | Rapid Clone（同步，本项目用）| `/v1/t2a_async_v2`（异步，长文 TTS 用） |
| - | - | - |
| 端点 | `POST /v1/voice_clone` | `POST /v1/t2a_async_v2` → 轮询 `task_id` |
| 用途 | **克隆声音**，返回 `voice_id` | **长文 TTS 合成**，返回 mp3 URL |
| 延迟 | < 1s（一次性返回）| 几秒 ~ 几十秒（要轮询 + 下载）|
| 适合场景 | 创建 / 刷新 voice 档案 | 单段 > 10000 字符的长文（小说章节 / 长报告）|
| 本项目是否用 | ✅ **是**（每个 voice 创建时一次）| ❌ 否（我们实时对话每段 < 200 字，走 `/v1/t2a_v2` SSE 流式）|
| 计费 | ¥9.9 / voice（一次性）| 按字符（与 T2A 同价）|

**为什么不用 async t2a 做"变相异步克隆"**：

1. **不能换得更低延迟**：async t2a 仍要先 clone 完才能用；
   clone 本身 < 1s 是同步的瓶颈下限，不是异步的。
2. **实时对话要的是首字延迟（TTFB）< 300ms**，不是总耗时；
   async t2a 必须等整段合成完才能下，跟"流式 SSE"冲突。
3. **polling 增加复杂度** + **额外接口费用** + **下载 mp3 浪费一次解码**，
   收益近乎为零。

**真正能"提早启动合成"的方案**：长任务开始之前**预热** voice（同步克隆一次），
存在缓存里；后续每次对话直接走已激活的 voice_id，没有任何异步可言。

## 13. 参考音频 v2（2026-07-11 升级）

我们把 BT-7274 的参考音频从早期 7.76s 的 `bt7274_ref_8s_mono.wav`
升级到 **`bt_reference.wav`（23.24s，16kHz mono）**。

**新文件信息**：

| 项 | 值 |
| - | - |
| 路径 | `D:\AI\workspace\bt-voice\ref_audio\bt_reference.wav` |
| 大小 | 743 724 字节（约 726 KB）|
| 时长 | 23.24 秒 |
| 采样率 | 16 kHz mono |
| 内容 | 完整 BT-7274 自报家门："我是 BT-7274，先锋级泰坦，属于反抗军 SRS，掠奪者军团…" |
| 转写文稿 | `D:\AI\workspace\bt-voice\ref_audio\bt_reference.wav.txt` |

**为什么不只挑 10 秒，而用 23 秒整段**：

1. **MiniMax 主音源上限 5 分钟**，23 秒完全在容忍区间；
   之前 7.76s 已经偏短（MiniMax 推荐 ≥ 10s），相似度吃亏。
2. **23 秒里包含 BT-7274 的标志性停顿和咬字习惯**，比裁短到 10 秒信息密度更高。
3. 长样本让 MiniMax 的韵律建模更稳，**不会出现"声音像但节奏不像"的怪感**。

**跟 §1.5 prompt audio 的边界**：
- 主参考音频（`file_id`）：23.24 秒 → 训练整体音色 + 韵律
- prompt audio（`prompt_audio`）：另选 < 8s 的某段"标志性台词" → 二次提音（**v2 默认暂不开**，等遇到相似度真不够的合成样本时再启用）

## 14. 升级路径（2026-07-11，把 `speech-2.6-hd` 干到 `speech-2.8-hd`）

**目标**：在不中断服务的前提下，把 `services/voice-clone` 后端模型换成 `speech-2.8-hd`
+ 中文锁定 + 用上 23.24s 长样本。

#### Step A：复制长样本参考音频到 voice 缓存目录

```powershell
# 把 bt-voice/ref_audio/bt_reference.wav 覆盖到本项目 voice 缓存
Copy-Item `
  -LiteralPath "D:\AI\workspace\bt-voice\ref_audio\bt_reference.wav" `
  -Destination "D:\AI\workspace\JoyAI-VL-Interaction-main\services\voice-clone\voices\bt7274\ref.wav" `
  -Force
# 同时把转写文本也搬过去（可选，但 voice_clone_api 自检会用到）
Copy-Item `
  -LiteralPath "D:\AI\workspace\bt-voice\ref_audio\bt_reference.wav.txt" `
  -Destination "D:\AI\workspace\JoyAI-VL-Interaction-main\services\voice-clone\voices\bt7274\transcript.txt" `
  -Force
```

#### Step B：调 `POST /v1/voices` 用新样本重新克隆一次

```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://127.0.0.1:8985/v1/voices" `
  -Form @{
    name     = "bt-7274"
    language = "zh"
    audio    = Get-Item "D:\AI\workspace\bt-voice\ref_audio\bt_reference.wav"
  } | Tee-Object -FilePath "D:\voice-clone-new.json"
```

**记下返回的 `voice_id`（形如 `vc_<new-timestamp>_<newhash>`）**，下一步要写进 env。

#### Step C：设 MiniMax key + 更新 voice_clone_api 配置

```powershell
# 1) MiniMax key（找你的组长 / 自己账户管理面板拿）
[Environment]::SetEnvironmentVariable('MINIMAX_API_KEY', '<your-bearer-token>', 'User')
[Environment]::SetEnvironmentVariable('MINIMAX_GROUP_ID', '<your-group-id>', 'User')

# 2) 改 voice_clone_api 默认模型为 2.8 + 锁中文
#    services/voice-clone/voice_clone_api/cloud_clone.py 第 35 行附近：
#    DEFAULT_MODEL = "speech-2.6-hd"  →  DEFAULT_MODEL = "speech-2.8-hd"
#    并在 zero_shot_synthesize() 的 payload 里加：
#    "language_boost": "Chinese",

# 3) 把新的 voice_id 写进 tts_adapter 的 env
$env:TTS_DEFAULT_VOICE_ID = '<paste-new-voice_id-here>'
Add-Content -Path "D:\AI\workspace\JoyAI-VL-Interaction-main\services\scripts\run-windows.env" `
  "`$env:TTS_DEFAULT_VOICE_ID = '<paste-new-voice_id-here>'"
```

#### Step D：重启 voice-clone 服务 + tts_adapter

```powershell
# 重启 voice-clone（让新的 DEFAULT_MODEL / language_boost 生效）
.\services\voice-clone\scripts\run-windows.ps1 -Restart

# 重启 tts_adapter（让它加载新的 TTS_DEFAULT_VOICE_ID）
.\scripts\run-windows.ps1 -Restart tts-adapter

# 探活
curl http://127.0.0.1:8985/health
# 期望看到："model": "speech-2.8-hd" / "language_boost": "Chinese"
```

#### Step E（可选，但强烈推荐）：跑一个烟雾测试

```powershell
curl -X POST http://127.0.0.1:8985/v1/synthesize `
  -H "Content-Type: application/json" `
  -d '{
    "text": "铁御，BT-7274 就绪，准备展开作业二一七。",
    "voice_id": "<paste-new-voice_id-here>",
    "streaming": false
  }' | Out-File -Encoding utf8 bt_smoke.json
# 听一下 bt_smoke.json["pcm16_base64"] 反 base64 出来的 PCM，听听是不是 BT 那种机器人腔
```

**回滚方案**：把 cloud_clone.py 的 `DEFAULT_MODEL` 改回 `speech-2.6-hd`，
然后跑一次 `POST /v1/voices/{voice_id}/refresh` 即可（旧的 7.76s 样本仍在
`services/voice-clone/voices/bt7274/ref.wav` 备份位置 —— 当然 Step A 用
`-Force` 覆盖过，所以严格起见升级前先 `Copy-Item ... -Destination ...ref.wav.v26.bak`）。

## 15. 升级执行记录（2026-07-11）

执行人：Codex。2026-07-11 早些时候只动本地文件；后续在用户确认 Token Plan Key 与
`GROUP_ID=2073018417979330937` 后，已完成真实 MiniMax 探针，见 §15.9。

### 15.1 已完成

| 步骤 | 文件 | 状态 |
| - | - | - |
| 复制参考音频 | `services/voice-clone/voices/bt7274/ref.wav` | ✅ 23.24 s, 16 kHz mono, 743 724 bytes |
| 同步转写文本 | `services/voice-clone/voices/bt7274/transcript.txt` | ✅ 单行 335 bytes（已清理 Praat 时间戳）|
| 创建 env 文件 | `services/scripts/run-windows.env` | ✅ 含 `MINIMAX_*` 与 `TTS_DEFAULT_VOICE_ID=vc_replace_me_after_first_clone` 占位 |
| 模型升级 cloud_clone.py | `DEFAULT_MODEL` 默认 `speech-2.8-hd`（已就位） | ✅ |

### 15.2 旧操作记录（已由 §15.9 当前配置取代）

```powershell
# 0. 写 key
Add-Content -Path "$env:USERPROFILE\.joyai\minimax_creds.json" -Value (@{
    api_key  = "eyJ-replace-me"
    group_id = "replace-me"
} | ConvertTo-Json)

# 1. 重启 voice-clone 加载新 ref.wav + 默认 speech-2.8-hd
$env:MINIMAX_API_KEY  = "<paste-here>"
$env:MINIMAX_GROUP_ID = "<paste-here>"
.\servicesoice-clone\scripts
un-windows.ps1   # 没 -Restart 时手动 stop + start

# 2. 重新克隆（自动取新 voice_id）
Invoke-RestMethod -Method POST `
  -Uri "http://127.0.0.1:8985/v1/voices" `
  -Form @{
    name     = "bt-7274"
    language = "zh"
    audio    = Get-Item "D:\AI\workspacet-voice
ef_audiot_reference.wav"
  } | Tee-Object -FilePath "D:oice-clone-new.json"

# 3. 把返回的 voice_id 写进 env（替换占位符）
$newVoiceId = (Get-Content D:oice-clone-new.json | ConvertFrom-Json).voice_id
notepad services\scripts
un-windows.env   # 改两处：TTS_DEFAULT_VOICE_ID 与 JARVIS_TTS_VOICE_ID

# 4. 重启 voice-clone + webui
.\stop-joyai.ps1
.\start-joyai.ps1
```

### 15.3 7 天过期 + start-joyai 预热（规划中，ADR 0001）

`voice_clone_api` 缓存的 voice 7 天不调就被 MiniMax 删除。后续 v2.1 准备在 `start-joyai.ps1` 启动 voice-clone 之后
**主动 ping 一次 `/v1/voices/{voice_id}/refresh`**，把过期窗口推前。

### 15.4 旧结论：订阅 Key vs 按量付费 API Key（已由 §15.9 修正）

从用户仪表盘上看到的事实真相：**订阅 Key（`sk-cp-`）和按量付费 API Key（`sk-api-...`）是两套独立体系**：

| 凭证 | 范围 | 能调的端点 | 不能调的端点 |
| - | - | - | - |
| 订阅 Key（`sk-cp-...`）| Token Plan 套餐内 | `/v1/chat`, `/v1/t2a_v2`, `/v1/t2a_async_v2`, `/v1/voice_clone`, `/v1/files/upload` | **`/v1/get_voice`, `/v1/files/list`, `/v1/delete_voice`**（管理类） |
| 按量付费 API Key（`sk-api-...`）| API 余额按调用计费 | 上面所有 + 管理类 | 无 |

文档原话："订阅 Key 与按量计费 API Key **不互通**" — https://platform.minimaxi.com/docs/token-plan/quickstart.md

实际测试（用订阅 Key 试管理类 endpoint 全都 1004）：
- `POST /v1/get_voice` body=`{"voice_type":"all"}` → HTTP 200 但 body `status_code:1004 login fail`
- `POST /v1/files/upload?purpose=voice_clone` → HTTP 200 但 body `status_code:1004 login fail`
- `GET /v1/files/list?purpose=voice_clone&GroupId=...` → HTTP 200 但 body `status_code:1004 login fail`
- `GET /v1/models` → HTTP 401 login fail

**1004 = MiniMax 后端完全不认识这把 key**，与 base URL / endpoint / body / GroupId 全都无关，纯凭证问题。

**找回 voice_id 的正确路径**：必须用按量付费 API Key 调 `/v1/get_voice`，订阅 Key 不行。

```powershell
$apiKey = "sk-api-...完整..."
$body   = @{ voice_type = "all" } | ConvertTo-Json
$r = Invoke-RestMethod -Method Post -Uri "https://api.minimaxi.com/v1/get_voice" `
       -Headers @{ Authorization = "Bearer $apiKey"; "Content-Type" = "application/json" } `
       -Body $body
$r.voice_cloning   # 你创过的所有 voice_cloning 列表
```

### 15.5 端点正解（2026-07-11 勘误）

| 我代码默认（cloud_clone.py::list_voices）| 实际官方 |
| - | - |
| `GET /v1/voice/list?GroupId=...` | ❌ 404 page not found（端点不存在） |
| ✅ 用 `POST /v1/get_voice` body `{"voice_type":"all|voice_cloning|system|voice_generation"}` | 文档：https://platform.minimaxi.com/docs/api-reference/voice-management-get |

返回值结构：
```json
{
  "system_voice": [...],
  "voice_cloning": [
    { "voice_id": "bt-7274-XX-XX", "description": [], "created_time": "2026-07-10" }
  ],
  "voice_generation": [...],
  "base_resp": { "status_code": 0, "status_msg": "success" }
}
```

### 15.6 GroupId vs 账号 UID 误区

| 名称 | 例子 | 用途 |
| - | - | - |
| **账号 UID**（纯数字）| `2073018417979330937`（用户一开始填错的）| 个人账号标识，**不是 GroupId** |
| **GroupId**（字符串）| `g-XXXXXX...`（约 27 位，g 前缀）| `/v1/files/upload` 等需要指定"哪个团队/工作空间"的接口 |

填错 GroupId 返回的错误是 `2013 输入格式信息不正常`，不是 1004；1004 = 凭证被 MiniMax 鉴权拒绝。

### 15.7 "voice 未激活不可查"

> 「快速复刻得到的音色为未激活状态，**需正式调用一次**才可在本接口查询到」 — 文档原话

也就是说即使用 API Key 调 `/v1/get_voice`，只创过但**还没在 `/v1/t2a_v2` 中真正合成过一次**的 voice 不会出现在 `voice_cloning` 数组里。需要在创完后立刻调一次 `t2a_v2`（哪怕纯文本占位）"激活"它。

### 15.8 key 完整 vs 残缺（2026-07-11 重复犯的错误）

MiniMax 的 1004 `login fail` 错误**永远是 token 字符串层面**问题。粘贴时一字之差 = 1004，与 token 是否有效完全无关。

**自检流程**：
1. 数 dashboard 上显示的 key 总长度（一般是 125-130 字符）
2. 数你粘贴到 env 文件的 key 长度 — 必须一模一样
3. 与用户中心"前 4 + ... + 后 6"显示对齐，例如末尾必须是 `EGaXX0` 而不是 `nEGaXX0`（差一个字符就 1004）
4. **实战技巧**：复制后立刻用 Select-String 检查 "Total: X chars"，给 env 之前先 echo `$key | Measure-Object Length`

**`sk-api-...` vs `sk-cp-...`**：
- 用户使用 Token Plan（订阅套餐）应该用 `sk-cp-...`
- 这个 key 在 MiniMax 用户中心带绿勾表示该 key 当前有效
- 如果 dashboard 里也带红字或不可见，说明该 key 已撤销或过期

### 15.9 当前权威记录（2026-07-11 实测通过）

用户确认：`GROUP_ID=2073018417979330937`，云端 voice_id 为 `minimax_man_33333`。

本机配置已更新：

| 项 | 当前值 |
| - | - |
| `TTS_PROVIDER` | `minimax` |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.com` |
| `MINIMAX_DEFAULT_MODEL` | `speech-2.8-hd` |
| `MINIMAX_LANGUAGE_BOOST` | `Chinese` |
| `MINIMAX_GROUP_ID` | `2073018417979330937` |
| `TTS_DEFAULT_VOICE_ID` | `minimax_man_33333` |
| `JARVIS_TTS_VOICE_ID` | `minimax_man_33333` |

`MINIMAX_API_KEY` 不写入 `services/scripts/run-windows.env`；它由 User/Process 环境变量提供，避免把密钥落盘到项目目录。

真实 API 探针结果：

| 探针 | 结果 |
| - | - |
| Token Plan 用量接口 | HTTP 200, `base_resp.status_code=0` |
| `POST /v1/get_voice` | HTTP 200, `base_resp.status_code=0`，可见 305 个音色 |
| `POST /v1/t2a_v2` + `minimax_man_33333` | HTTP 200, `base_resp.status_code=0`，返回合法 WAV |
| `api.minimaxi.com` / `api-bj.minimaxi.com` | 两个域名同步 T2A 均成功；默认继续用官方主域名 `api.minimaxi.com` |

关键修正：MiniMax 同步 T2A 的 `data.audio` 是 **hex 编码**，不是 base64；WAV 音频的前缀会显示为 `52494646...`，hex 解码后才是 `RIFF...WAVE`。这不是 UID，也不是 GROUP_ID。

Token Plan 结论修正：`sk-cp-*` 订阅 Key 与 `sk-api-*` 按量 Key 是两套独立凭据，不能互相替代其计费来源；但本次实测中，用户的 `sk-cp-*` Token Plan Key 可以认证 `get_voice` 与 T2A 端点。若再次出现 `1004 login fail`，优先检查当前进程是否还残留旧 `MINIMAX_API_KEY` 或旧 `MINIMAX_GROUP_ID`。

服务合成链路修正：`voice_clone_api` 在 `TTS_PROVIDER=minimax` 时允许直接使用云端 voice_id（如 `minimax_man_33333`），不再要求本地存在 `voices/minimax_man_33333/meta.json`。

验证命令：

```powershell
$env:MINIMAX_GROUP_ID = '2073018417979330937'
D:\AI\envs\joyai-main\python.exe -m pytest services\voice-clone\tests -q
D:\AI\envs\joyai-main\python.exe -m pytest services\webui\tests -q
```

