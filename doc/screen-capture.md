# 屏幕捕获方案（getDisplayMedia）

> 状态：**P1 规划**。webui 端浏览器 API，0 后端改动。
> 配套文档：`doc/jarvis-mode.md`（产品）+ `doc/tech-local.md §3.7`（实现）。

---

## 0. 选型结论

> **采用浏览器原生 `navigator.mediaDevices.getDisplayMedia()`**
>
> 理由：webui 端已经是浏览器 + WebRTC 架构，**0 后端改动**；与云游戏标杆（GeForce NOW / Stadia）同架构；延迟 <100ms；用户主动授权隐私友好。

---

## 1. 方案对比

| 维度 | **getDisplayMedia** | OBS Studio | ffmpeg + gdigrab |
| - | - | - | - |
| 实现层 | 浏览器 API | 独立应用 | CLI 后台进程 |
| 用户交互 | **必须**（user gesture + picker） | 否（配置后） | 否 |
| 窗口选择 | 浏览器弹选择器 | OBS 配置 | 命令行按窗口名 |
| 音频 | 标签音频 / 系统音频 | OBS 混音 | 系统音频（需 virtual device） |
| 延迟 | **<100ms** | 200-800ms | 取决于后续链 |
| GPU 加速 | 浏览器自动 | NVENC / QuickSync | NVENC / QSV / AMF |
| 自动化 | ❌ 需用户点 | ⚠️ 需 OBS 实例 | ✅ 完全自动 |
| 集成度 | ✅ webui 已有 | ❌ 需独立 OBS | ⚠️ 需额外进程 |
| 社区成熟度 | ⭐⭐⭐⭐⭐ MDN 标准 | ⭐⭐⭐⭐⭐ 流媒体标配 | ⭐⭐⭐⭐ CLI 老牌 |
| 云游戏标杆 | GeForce NOW / Stadia 类似 | NVIDIA GeForce Experience | 自托管服务器 |

---

## 2. 与本项目集成

**webui 现状**（已用浏览器 video API）：
- `services/webui/.../vlm_service.py` — 视频帧送给 VLM
- `services/webui/.../video_processor.py` — 视频处理
- `services/webui/.../server.py` — WebRTC 信令

**getDisplayMedia 集成点**：在 `vlm_service.py` 或 web 前端 `static/js/`，加一个"开始游戏捕获"按钮。

**0 后端改动**——纯前端 + 现有 WebRTC 链路。

---

## 3. 实施代码

### 3.1 webui 端 JavaScript

```javascript
// services/webui/src/joy_interaction_webui/static/js/screen_capture.js
/**
 * Start capturing a game window via getDisplayMedia.
 * Captures at 1 fps and sends frames to VLM via existing pipeline.
 */
let gameStream = null;
let captureInterval = null;

async function startGameCapture() {
  try {
    // Step 1: 弹浏览器选择器，让用户选游戏窗口
    gameStream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        displaySurface: "window",  // 只让用户选窗口，不要整屏
        width: { ideal: 1920 },
        height: { ideal: 1080 },
        frameRate: { ideal: 1 }    // 1 fps（与 VLM 1 fps 视频流一致）
      },
      audio: false                  // 不要系统音频（避免 TTS 反馈到 mic）
    });

    // Step 2: 渲染到隐藏 video 元素
    const videoEl = document.createElement("video");
    videoEl.srcObject = gameStream;
    videoEl.muted = true;
    videoEl.play();

    // Step 3: 每秒抓一帧送给 VLM
    captureInterval = setInterval(async () => {
      if (videoEl.readyState < 2) return;
      const canvas = document.createElement("canvas");
      canvas.width = videoEl.videoWidth;
      canvas.height = videoEl.videoHeight;
      canvas.getContext("2d").drawImage(videoEl, 0, 0);
      // JPEG 压缩到 70%，减带宽
      const frame = canvas.toDataURL("image/jpeg", 0.7);
      await sendFrameToVLM(frame);
    }, 1000);

    // Step 4: 监听用户停止共享
    gameStream.getVideoTracks()[0].onended = () => {
      stopGameCapture();
    };

    console.log("游戏窗口捕获已启动");
  } catch (err) {
    console.error("getDisplayMedia failed:", err);
    if (err.name === "NotAllowedError") {
      alert("请允许浏览器捕获游戏窗口");
    } else if (err.name === "NotFoundError") {
      alert("未找到可捕获的窗口");
    }
  }
}

function stopGameCapture() {
  if (captureInterval) {
    clearInterval(captureInterval);
    captureInterval = null;
  }
  if (gameStream) {
    gameStream.getTracks().forEach(track => track.stop());
    gameStream = null;
  }
  console.log("游戏窗口捕获已停止");
}

async function sendFrameToVLM(frameDataUrl) {
  // 通过现有 webui pipeline 发送
  const ws = getWebUIWebSocket();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "video_frame",
      source: "screen_capture",  // 标识来源
      data: frameDataUrl,
      timestamp: Date.now()
    }));
  }
}
```

### 3.2 webui HTML 端

```html
<!-- services/webui/src/joy_interaction_webui/templates/index.html -->
<div class="game-capture-controls">
  <button id="start-capture" onclick="startGameCapture()">
    🎮 开始游戏捕获
  </button>
  <button id="stop-capture" onclick="stopGameCapture()" disabled>
    ⏹ 停止捕获
  </button>
  <span id="capture-status" class="status-idle">未捕获</span>
</div>
```

### 3.3 Python 端（webui server.py 接收 video_frame）

```python
# services/webui/src/joy_interaction_webui/server.py
async def handle_video_frame(ws, data):
    """处理来自屏幕捕获的视频帧。"""
    if data.get("source") != "screen_capture":
        return
    frame_data_url = data.get("data")
    timestamp = data.get("timestamp")
    # 复用现有 vlm_service 的帧队列
    await vlm_service.enqueue_frame(
        frame_b64=frame_data_url.split(",", 1)[1],
        source="screen",
        timestamp=timestamp,
    )
```

---

## 4. 关键设计

### 4.1 隐私保护

| 设置 | 值 | 理由 |
| - | - | - |
| `displaySurface` | `"window"` | **只让用户选窗口**，不要整屏（避免敏感信息） |
| `audio` | `false` | 不要系统音频（避免 TTS 反馈到 mic） |
| `frameRate` | `1` | 1 fps（不必要的高帧率浪费带宽 + 算力） |
| 用户主动授权 | ✅ 必选 | 每次启动都弹选择器，**不能持久化** |

### 4.2 与 VLM 1 fps 视频流对齐

webinfer 端原本就是 1 fps 视频流（见原项目），getDisplayMedia 也用 1 fps，**无缝对齐**。

### 4.3 与 Jarvis 模式协同

```text
[用户] "bt" → 唤醒
[BT-7274] "铁御，我在"
[用户] "我在玩赛博朋克 2077，把这个怪说一下打法"
[用户] 点击"开始游戏捕获" → 选赛博朋克窗口
[系统] 1 fps 视频帧 → VLM 识别
[BT-7274] "这个螳螂帮，先用赛博精神病秒掉..."
```

### 4.4 错误处理

| 错误码 | 含义 | 用户提示 |
| - | - | - |
| `NotAllowedError` | 用户拒绝授权 | "请允许浏览器捕获游戏窗口" |
| `NotFoundError` | 未选窗口 | "未找到可捕获的窗口" |
| `NotReadableError` | 窗口被其他应用独占 | "游戏窗口被占用，请关闭其他录屏软件" |
| `OverconstrainedError` | 不满足约束 | "请尝试其他窗口" |

---

## 5. 浏览器兼容性

| 浏览器 | 支持 | 备注 |
| - | :-: | - |
| Chrome / Edge (Win) | ✅ | Chromium 系原生支持 |
| Firefox | ✅ | 较新版本 |
| Safari | ⚠️ | 部分支持，需 macOS 13+ |

**推荐**：Chrome 或 Edge。

---

## 6. 性能

| 指标 | 数值 |
| - | - |
| 用户感知延迟 | <100ms（捕获 + 编码） |
| CPU 占用（编码） | 5-10%（浏览器自动） |
| 帧大小（1080p JPEG 70%） | 100-300 KB |
| 带宽 | ~200 KB/s（1 fps） |
| VLM 推理（每帧） | 0.5-2s（取决于模型） |

---

## 7. 备选方案（未来）

### 7.1 OBS 虚拟摄像头 + ffmpeg 桥接

**场景**：用户已经在用 OBS 直播/录屏，希望复用。

**架构**：
```
游戏 → OBS 捕获 → OBS 虚拟摄像头 → ffmpeg AVFoundation/dshow → 我们的 webui
```

**优势**：用户已熟悉 OBS，可配置多场景
**劣势**：增加中间环节，延迟 +300-800ms

**实施**：在 webui 端加"使用 OBS 虚拟摄像头"开关，识别新设备。

### 7.2 ffmpeg + gdigrab（Windows）

**场景**：完全自动化（无用户交互）。

**架构**：
```
ffmpeg -f gdigrab -i title="Game Window" -r 1 -f image2pipe -vcodec mjpeg
  → 推 RTSP / WebSocket → 我们的 webui
```

**优势**：完全后台，自动化
**劣势**：配置复杂；用户不能选择窗口（要预设窗口名）

**实施**：用户预先在 `run-windows.env` 配 `GAME_WINDOW_TITLE=赛博朋克 2077`，webui 后台 ffmpeg 进程。

---

## 8. 实施步骤

1. 写 `services/webui/src/.../static/js/screen_capture.js`（~50 行）
2. 改 `services/webui/src/.../templates/index.html`（加按钮）
3. 改 `services/webui/src/.../server.py` 接收 `video_frame`（~20 行）
4. 端到端测试：选窗口 → 1 fps 帧 → VLM 识别
5. 端到端测试：与 Jarvis 模式协同

**总工作量**：~2 小时。

---

## 9. 风险

| 风险 | 概率 | 影响 | 缓解 |
| - | - | - | - |
| 浏览器拒绝授权 | 中 | 中 | 明确错误提示 + 文档说明 |
| 帧率不稳（游戏卡顿） | 中 | 低 | 1 fps 容忍度高 |
| 窗口最小化后无画面 | 高 | 中 | 检测 `videoEl.videoWidth === 0` → 跳过 |
| OBS 同时录屏冲突 | 低 | 中 | 提示用户关 OBS 录屏 |
| 隐私泄露（误选整屏） | 低 | 高 | **强制 `displaySurface: "window"`** |

---

## 10. 关联文档

- `doc/jarvis-mode.md`（产品形态）
- `doc/tech-local.md §3.7`（实现细节）
- `doc/pm-local.md §9`（路线图）

---

## 11. 变更记录

| 日期 | 版本 | 变更 | 作者 |
| - | - | - | - |
| 2026-07-09 | v1.0 | 初版：getDisplayMedia 屏幕捕获方案 | Codex |