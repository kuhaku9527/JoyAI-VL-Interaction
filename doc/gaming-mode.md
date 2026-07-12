# Jarvis 模式使用指南（游戏中 / 日常陪伴）

> 状态：**P1 核心已落地**。KWS v4 + 状态机骨架已部署，待全链路 e2e 验证。
> - **2026-07-10**：唤醒词 "bt"（自训 KWS v4），JarvisStateMachine 已集成 KWS + 流式 ASR 代码改动完成。
> 配套文档：`doc/jarvis-mode.md`（产品设计）+ `doc/asr-streaming.md`（技术实现）。

---

## 0. 一句话

> **这是钢铁侠的贾维斯**：默认静默，你说"bt"→ 它说"铁御，我在"→ 你提需求 → 它回应 → 你说"明白" → 它说"任务完成，断开神经链接"→ 回到静默。

---

## 1. 适用场景

| 场景 | 适合 | 不适合 |
| - | - | - |
| **游戏中**（一边玩一边语音） | ✅ 唤醒 + 全双工 + 短指令 | 嘈杂多人环境 |
| **日常陪伴**（电脑旁工作） | ✅ 偶尔问问题 | 需要持续录音（隐私敏感） |
| **写代码**（IDE 内） | ✅ 唤醒 + 短问 | 长篇对话 |
| **直播 / 监控** | ❌ 需 always-on | 选原版 ASR |
| **多人会议** | ❌ 唤醒会被误触发 | 选原版 ASR |

---

## 2. 启动与使用

### 2.1 启动

```powershell
cd services
.\scripts\run-windows.ps1 -Mode jarvis
```

**第一次启动会**：
1. 装 sherpa-onnx（如果未装）
2. 加载 KWS 模型 "bt"（1-3MB）
3. 加载流式 ASR 模型（100MB，懒加载）
4. 加载 BT-7274 角色 prompt
5. webui 启动到 https://127.0.0.1:8099/

### 2.2 浏览器

打开 https://127.0.0.1:8099/，接受自签证书。

**会看到**：
- 视频/音频流（可选）
- **Jarvis 状态指示器**：
  - 灰色 = 待命（KWS 监听中）
  - 蓝色 = 唤醒中（播 wake.wav）
  - 绿色 = 对话中（全双工）
  - 黄色 = 处理中（TTS 暂停 / 重启）

### 2.3 第一次对话

```text
你：bt？
BT-7274：铁御，我在
[状态指示器：绿色]

你：今天有什么新闻？
BT-7274：（流式回答...）
[状态指示器：绿色]

你：明白
BT-7274：任务完成，断开神经链接
[状态指示器：灰色]
```

### 2.4 打断

```text
你：bt？
BT-7274：铁御，我在
[绿色]

你：今天...（开始说话）
BT-7274：今天...（开始回答）
你：等等，换个话题（打断）
[BT-7274 立即停止 TTS]
你：今天有什么特价游戏？
BT-7274：（新回答）
[绿色]
```

---

## 3. 角色化（BT-7274）

### 3.1 角色 prompt

位置：`prompts/bt-7274.txt`

**用户自己填**（占位符已就绪）：
- 性格（直接、机械、毒舌、温柔）
- 背景故事
- 说话风格
- 对游戏的偏好

### 3.2 声音克隆

**预录音频位置**：`prompts/bt/events/`
- `wake.wav` - 唤醒响应（"铁御，我在"）
- `goodbye.wav` - 结束响应（"任务完成，断开神经链接"）
- `error.wav` - 错误响应（极少触发）

**声音克隆源**：`D:\AI\workspace\bt-voice\ref_audio\1.BT-7274\diag_sp_pilotLink_WD141_43_01_mcor_bt.wav`
参考文字："我们的命令是要展开特殊作业二一七"

**重新生成**（更换声线 / 升级 TTS 后端）：
```powershell
# 1. 重新上传参考音频
curl -X POST http://127.0.0.1:8985/v1/voices/upload `
  -F "audio=@D:\AI\workspace\bt-voice\ref_audio\1.BT-7274\diag_sp_pilotLink_WD141_43_01_mcor_bt.wav" `
  -F "name=bt-7274" `
  -F "ref_text=我们的命令是要展开特殊作业二一七"

# 2. 拿新 voice_id，跑生成脚本
python services/scripts/generate_event_audio.py --voice-id <新 voice_id>
```

---

## 4. 故障排查

### 4.1 KWS 不识别

**症状**：喊"bt"无反应。

**排查**：
```powershell
# 1. 检查 KWS 模型是否存在
Test-Path "D:\AI\models\sherpa-onnx\models\kws\bt-zai-ma\encoder.onnx"

# 2. 检查 sherpa-onnx 是否装好
python -c "import sherpa_onnx; print(sherpa_onnx.__version__)"

# 3. 测试 KWS 单独
python -m services.asr.jarvis.kws test_wake.wav
```

**调整**：
- 调高麦克风音量
- 训练更多数据（50 句不够就 100 句）
- 缩短唤醒词（"bt 吗"）

### 4.2 ASR 首字延迟高

**症状**：说完后 1-2s 才出文字。

**排查**：
- 检查 `rule1_min_trailing_silence` 设置（应该 2.0s）
- 检查 chunk size（应该 30ms）
- 关闭 `do_server_vad`（让客户端 VAD 决定）

### 4.3 打断不响应

**症状**：你说话时 BT-7274 还在播。

**排查**：
- 浏览器 AEC 是否开启（默认是）
- ASR partial 是否在出（看 `services/.logs/<时间戳>/jarvis-mode.log`）
- TTS pause 是否被调用

### 4.4 静默超时误触发

**症状**：对话 5s 没说话就被关闭。

**调整**：改 `prompts/bt/events/jarvis_mode.py` 的 `DIALOG_SILENCE_TIMEOUT`。

---

## 5. 性能与优化

| 指标 | 数值 | 备注 |
| - | -: | - |
| KWS 唤醒响应 | <50ms | KWS 模型 1MB |
| ASR 首字 | 200-400ms | 流式 |
| 端到端（说话→听到回答） | 0.8-1.5s | 流式 + LLM |
| 打断响应 | 200-400ms | ASR partial → TTS pause |
| 静默期 CPU | <0.5% | KWS |
| 静默期显存 | 0 | KWS 纯 CPU |
| 对话期 CPU | ~10% | 流式 ASR + KWS 持续 |
| 对话期内存 | ~300MB | sherpa-onnx 加载 |
| 对话期显存 | 0 | 纯 CPU |

---

## 6. 与其他模式的对比

| 模式 | 触发 | 适用 |
| - | - | - |
| **Jarvis 模式**（推荐） | 唤醒词 + 全双工 | 个人 / 游戏 / 陪伴 |
| **Always-on 模式** | 持续 ASR | 看护 / 直播 / 监控 |
| **Push-to-talk 模式** | 按住说话键 | 老人 / 嘈杂环境 / 会议 |

**本项目主推 Jarvis 模式**——其他模式保留原项目逻辑。

---

## 7. 关联文档

- `doc/jarvis-mode.md`（产品设计）**必读**
- `doc/asr-streaming.md`（技术实现）
- `doc/voice-clone.md`（声音克隆）
- `doc/api-optimization.md`（API 选型）

---

## 8. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-06 | v1.0 | 初版：游戏中对话指南 | Codex |
| 2026-07-08 | v2.0 | 大改：升级为 Jarvis 模式指南（唤醒 + 全双工 + EXIT_WORDS） | Codex |
