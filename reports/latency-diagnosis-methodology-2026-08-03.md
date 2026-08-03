# 视频采集端到端延迟诊断方法论（issue #43 · 诊断阶段）

> 状态：诊断阶段（已落地分段计时埋点，PR #75 合入 `main@8685742`）。本阶段只做量化，不做方案选型；选定方案后另写 spec+adr 实现可切换配置。

## 1. 目的
在 **采集 → 编码 → 传输 → 推理 → 渲染** 五段落地纯增量计时埋点，定义如何运行系统、采集计时数据、定位瓶颈段。根因未知、方案待选，故先量化再决策（避免"没想清楚就框死方案"）。

## 2. 五段计时点（已落地）

| 段 | 代码位置 | 计时标记 | 日志 / 样本字段 |
|----|----------|----------|-----------------|
| 采集 capture | `screen_capture.js` `grabFrame()` 后 | `t0 → tGrab` | `[latency][screen]` `grab_ms` |
| 编码 encode | `canvas.toDataURL('image/jpeg',0.75)` 后 | `tGrab → tEncode` | `[latency][screen]` `encode_ms`（嫌疑瓶颈） |
| 传输 send | `liveWs.send(...)` 后 | `tEncode → tSend` | `[latency][screen]` `send_ms` |
| 传输-end + 推理 | `server.py` frame handler 内联 decode+process | `t_arrive → t_decoded → t_processed` | `latency[transport+infer-screen]` `decode_ms` / `arrive->processed_ms` |
| 推理 infer | `infer_loop.py` `_call_main_model` 前后 | `t_infer_start → t_inference_end` | `latency[infer]` `model_call_ms` |
| 渲染 render | `index.html` `renderVlmHistory` DOM 插入 | `tRenderStart → log` | `[latency][render]` `ms` / `skipped` |

**帧关联**：`frame_seq`（前端自增，写入 frame JSON payload）→ 后端 `data.get("frame_seq")`，可把前端「采集/编码/发送」与后端「到达/解码/推理」按 seq 对齐。

**环形缓冲**：前端 `window.__screenLatency`（最近 120 样本），含 `interval_ms`（帧间隔漂移，衡量 1fps 节拍稳定性，可发现 setInterval 被主线程抢占）。

## 3. 如何采集数据
1. 启动全栈（`start-joyai.ps1` 或 `run-windows.ps1 -Mode minimal`）；webui 启动前设 `JOYAI_MEMORY_STORE_URL=http://127.0.0.1:8997`。
2. 浏览器开 webui，开启屏幕采集（1fps）。
3. 前端：`DevTools Console` 过滤 `[latency]`；后端：`tail webui.log / webinfer.log` 过滤 `latency[`。
4. 跑 1–2 分钟，记录稳态样本（丢弃前 10 帧预热）。

## 4. 瓶颈定位方法
- **`encode_ms` 高（>50ms）** → 嫌疑在同步 `toDataURL`（主线程阻塞）。候选：OffscreenCanvas / WebCodecs / 降质量或分辨率。
- **`arrive->processed_ms` 高 且 `model_call_ms` 高** → 瓶颈在 VLM 推理。候选：量化 / 批处理 / 更强 GPU。
- **`interval_ms` 漂移大** → 采集节拍不稳定（setInterval 被主线程抢占）。
- **`send_ms` 相对高** → WS 序列化/网络（本地回环通常可忽略）。

## 5. 方法论注意事项（reviewer 已确认）
- **真实「传输 / 网络」段未被隔离**：server 端 `t_arrive` 取在 `base64.b64decode` 之前，测的是 server 端 **decode + infer 的处理时间**，不是浏览器 `tSend` → 后端收到字节之间的真·网络往返。要隔离真·wire 延迟需前后端时钟对齐（NTP/PTP）或 WS ping/pong RTT——本阶段未做，列为后续增强项。
- **webcam / OBS 路径走 WebRTC**，编码在浏览器/OS 主线程外，JS 侧不可测；故该路径未埋点，仅留注释。对比 Screen Capture vs OBS VC 时，OBS 的编码开销不计入本埋点，需在报告里显式说明。
- `frame_seq` 缺失时后端记 `None`，不影响运行。

## 6. 待办（下一步）
- [ ] 实跑采集 → 出 `reports/latency-diagnosis-data-*.md`（真实数字 + 瓶颈结论）
- [ ] 确认瓶颈段 + 选方案（Screen Capture / OBS VC / RTSP）
- [ ] 写 spec（`doc/specs/`）+ adr（`doc/adr/`）落地可切换配置
- [ ] （可选增强）前后端时钟对齐以隔离真·wire 延迟
