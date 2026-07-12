# Glossary — BT 语音交互栈术语

| 术语 | 全称 | 含义 |
| - | - | - |
| BT | BT-7274 | 《Titanfall 2》主角之一，先锋级泰坦，致敬发音"哔踢"。本项目用它做语音克隆人设 |
| KWS | Keyword Spotting | 唤醒词检测（"bt"），区别于 ASR 的全句识别 |
| ASR | Automatic Speech Recognition | 流式全句语音识别（sherpa-onnx streaming-paraformer-bilingual-zh-en）|
| TTS | Text-To-Speech | 文本合成语音，本项目走 MiniMax 云端 (`speech-2.8-hd`) |
| LLM | Large Language Model | 大模型对话（llama.cpp 的 joyai-vl-interaction-preview-iq4_nl-imat.gguf）|
| TTFB | Time To First Byte | 流式 LLM 的首字延迟 |
| FAR | False Acceptance Rate | KWS 的误唤醒率（不希望唤醒时唤醒了）|
| Recall | 召回率 | KWS 该唤醒时唤醒了（FAR vs Recall 是平衡关系）|
| sherpa-onnx | k2-fsa 出品的 ONNX 推理引擎 | KWS / ASR 后端 |
| MiniMax | MiniMax AI | 云端 TTS + 声音克隆服务（Rapid Clone）|
| Rapid Clone | MiniMax 的 `/v1/voice_clone` 端点 | 同步声音克隆，**不是**异步 |
| t2a_async_v2 | MiniMax 的 `/v1/t2a_async_v2` 端点 | 异步**长文合成**，与克隆无关 |
| chunk-8 | sherpa-onnx 编码器 chunk size | 流式接口，每 8 帧一输出 |
| max_active_paths | sherpa-onnx KWS beam search 宽度 | 默认 4 不够，自训模型需要 10 |
| trailing_blanks | sherpa-onnx KWS 触发后的"静音帧"要求 | 防止尾音重复触发 |
| voice_id | MiniMax 声音档案 ID | 形如 `vc_<timestamp>_<hex>`，每次 clone 后会变 |
| minimax_voice_id | 云端固定 voice 标识 | 我们传 `bt-7274`，跨次刷新复用 |
| 7d 过期 | MiniMax 声音档案 7 天不调就删 | start-joyai 预热逻辑保持它活着 |
| EXIT_WORDS | 退出关键词集合（jarvis 模式）| "行 / 明白 / ok / 好的 ..." 共 8 个 |
| JarvisState | 6 个状态枚举 | KWS_LISTENING / WAKE_DETECTED / DIALOG_ACTIVE / TTS_PAUSED / EXIT_DETECTED / ERROR |
| SpeakerAudioTrack | aiohttp-WebRTC 音频输出轨道 | jarvis 模式推 TTS 给浏览器 |
| MicAudioTrack | 浏览器 → jarvis 模式麦克风轨道 | 100ms chunk PCM16 |