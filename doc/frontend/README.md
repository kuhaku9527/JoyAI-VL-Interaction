# JoyAI VL Interaction — 前端模块说明

> 本文档面向需要维护、排障或二次开发前端的工程师。
> 配套架构评分报告见 `reports/frontend-architecture-report.md`。

## 1. 总览

JoyAI VL Interaction 的前端是一个**单文件原生 JS SPA**（无框架、无打包器、无 `package.json`），
由 aiohttp 网关 `services/webui/src/joy_interaction_webui/server.py` 托管并提供 API 代理。
整页逻辑集中在 `static/index.html` 的两个内联 `<script>` 块中（约 6000 行），这是当前最大的技术债来源。

前端只负责：UI 渲染、采集（摄像头/RTSP/屏幕）、与后端建立 WebSocket 与 WebRTC 通道、把模型文本做 Markdown 渲染。

## 2. 文件地图

| 文件 | 作用 |
| --- | --- |
| `static/index.html` | 整个前端单体：HTML 结构 + 两个内联脚本（业务逻辑 + 渲染/通信） |
| `static/capture_webcam.js` | 摄像头采集（IIFE 模块，挂 `window.startWebcamCapture` 等） |
| `static/capture_rtsp.js` | RTSP 流采集（IIFE 模块） |
| `static/screen_capture.js` | 屏幕共享采集（IIFE 模块） |
| `server.py` | aiohttp webui 网关：托管静态页 + 反向代理 + WebSocket/WebRTC 信令入口 |
| `../webinfer/` | LLM 编排网关（:8070），前端通过它下发推理请求 |

三个 `capture_*.js` 已是结构良好的 IIFE 模块，**不要**把它们再塞回 `index.html`；
它们是后续模块化拆分时优先保留的外部模块范本。

## 3. 启动方式

前端本身没有独立的 dev server，随 webui 网关一起启动：

```powershell
# 仓库根目录
.\start-joyai.ps1          # 启动 webui(:8099) + webinfer(:8070) 等
```

访问 `http://127.0.0.1:8099/`。如需禁用 HTTPS 便于本地调试：`server.py --no-ssl`。
测试模式：`$env:JOYAI_TEST_MODE=1` 可跳过 `on_startup`/`on_shutdown` 钩子。

## 4. 通信契约

| 通道 | 路径 / 协议 | 说明 |
| --- | --- | --- |
| 页面入口 | `GET /` | 返回 `index.html`（含 CSP 响应头） |
| 实时消息 | `WebSocket /ws` | 上行用户指令/采集帧信令，下行模型流式文本与状态 |
| 媒体协商 | `POST /offer` | WebRTC SDP offer，转发到 webinfer 做推理侧媒体建立 |
| 推理代理 | `POST /api/llm/message`、`POST /api/tts/synthesize` 等 | 网关转发到 webinfer(:8070)/TTS(:8985)/ASR(:8993) 等微服务 |
| 服务配置 | `GET/PUT /api/services/config` | 前端服务端点（LLM/Summary/TTS/ASR）配置 |

> 前端在"服务配置"面板里填的 API Base 默认都是 `127.0.0.1:PORT`，因此 CSP 的
> `connect-src` 仅放行 `127.0.0.1:*`。若要把后端指向其他主机，需同步放宽 `server.py`
> 中 `security_headers_middleware` 的 `connect-src`。

## 5. 安全模型（已加固）

### 5.1 CDN 子资源完整性（SRI）
`index.html` 头部的 4 个 CDN `<script>` + katex CSS 均已钉版本并带 `integrity="sha384-..."` +
`crossorigin="anonymous"`，防止 CDN 被篡改或投毒时加载恶意脚本。

刷新某次 CDN 版本后，用以下命令重算哈希：

```bash
curl -sSL <cdn-url> -o /tmp/cdn.js
echo "sha384-$(openssl dgst -sha384 -binary /tmp/cdn.js | openssl base64 -A)"
```

把输出填回对应标签的 `integrity` 属性。**不要**把脚本改回 `@latest` 这类浮动版本——它
会让 SRI 随时因内容变化而失效。

### 5.2 内容安全策略（CSP）
`server.py` 的 `security_headers_middleware` 对每个响应注入：

```
default-src 'self';
script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com;
style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;
img-src 'self' data: blob:;
font-src 'self' data: https://cdn.jsdelivr.net;
media-src 'self' blob: data:;
connect-src 'self' ws: wss: http://127.0.0.1:* https://127.0.0.1:*;
object-src 'none';
base-uri 'self';
frame-ancestors 'none'
```

外加 `X-Content-Type-Options: nosniff` 与 `Referrer-Policy: no-referrer`。

已知权衡：
- `script-src` 含 `'unsafe-inline'`，因为 `index.html` 有两大段内联脚本。
  后续若做模块化拆分，应改为 `nonce` 注入以消除该弱化项。
- `connect-src` 限制到 `127.0.0.1:*`，是面向本地/内网工具的有意收紧。

### 5.3 不可信内容的 DOM 消毒（无需改动，已具备）
所有"模型/网络产出"进入 DOM 的路径都已有消毒，审计确认无裸 `innerHTML` 漏网：

| 内容来源 | 落地函数 | 消毒方式 |
| --- | --- | --- |
| 模型 Markdown 文本 | `renderMarkdown()` → `renderTextIntoElement()` | `DOMPurify.sanitize`（ALLOWED_TAGS/ATTR 白名单），链接加 `rel="noopener noreferrer"` |
| 模型产出的 HTML 工件 | `renderBackgroundHtmlView()` | `sandbox=""` 隔离 iframe + `sanitizeStaticHtml()` 二次消毒 |
| ASR 转写文本 | `sanitizeAsrTranscriptText()` | 转义 + 标签剥离 |

> ⚠️ 不要把上面这些 `innerHTML` 调用"顺便"也包一层 `sanitizeStaticHtml`——页面里大量
> `innerHTML = '<i data-lucide="...">'` 是注入图标用的，`sanitizeStaticHtml` 的白名单会
> 把 `data-lucide` 属性洗掉，导致图标失效。开发者写死的静态 HTML 是安全的，无需消毒。

## 6. 响应式布局与交互架构

> 本节记录 2026-07-20 布局重构后的最终结构，含一个已修复的预存布局缺陷。

### 6.1 DOM 结构（重构后）

```
<body>
  <header>                    ← 固定顶栏（~75px），含汉堡菜单按钮 #sidebarToggle
    ...
  </header>

  <div class="container">     ← display:flex; height:calc(100vh - 75px)
    <div id="sidebar" class="sidebar">  ← flex:1; display:flex; flex-direction:row（**默认展开 350px**；点击面板头可收起为 64px docked）
      <div id="sidebarPanels" class="sidebar-panels">  ← 设置面板容器
        .panel { ... }         ← 视频源 / 服务配置 / ... 各设置卡片
        .panel { ... }
        ...
      </div><!-- /sidebar-panels -->

      <div class="main-content">   ← flex:1; 主内容区（视频 + VLM + 聊天）
        .video-card             ← 视频播放器
        .result-card            ← 结果展示
        .chat-prompt-shell      ← 对话输入
        ...
      </div><!-- /main-content -->
    </div><!-- /sidebar -->

    <div id="sidebarScrim" class="sidebar-scrim"></div>  ← 抽屉遮罩层
  </div><!-- /container -->
</body>
```

关键点：
- `.main-content` 是 `.sidebar` 的**直接子元素**（flex 兄弟），不是 `.sidebar-panels` 的后代。
- `.sidebar-panels` 包裹所有设置面板；它是唯一参与 off-canvas 动画的元素。

### 6.2 已修复的预存布局缺陷

原始代码中 `.sidebar` 缺少 `display:flex`（默认为 `block`），导致其子元素 `.main-content`
的 `flex: 1` 从未生效——桌面端主内容被压进 ~47px 宽的停靠侧栏内，几乎不可见。
本次重构将 `.sidebar` 改为 `display:flex; flex-direction:row`，使布局恢复为设计意图：
**左侧面板列（350px 展开或 64px 收起）+ 右侧主内容区（flex:1 填充剩余宽度）**。

### 6.3 断点层级与行为矩阵

| 视口范围 | 断点名 | `.sidebar` | `.sidebar-panels` | `.main-content` | 汉堡按钮 | 布局模式 |
|---|---|---|---|---|---|---|
| ≥1600 | 大桌面 | flex-row | 350px（**默认展开**；点面板头可收起 64px） | 双栏 grid | 隐藏 | 双栏 + 侧栏 |
| ≥1280 | 标准桌面 | flex-row | 350px（默认）/64px（收起） | 单栏 → 双栏 grid | 隐藏 | 单/双栏 + 侧栏 |
| 1024–1279 | 小笔记本 | flex-row | 350px | 单栏 | 隐藏 | 单栏 + 窄侧栏 |
| ≤1023 | 平板/手机 | flex-row | **off-canvas drawer**<br>`position:fixed; z-index:9991` | 全宽 `width:100%` | 显示 | **抽屉覆盖** |
| ≤768 | 手机竖屏 | flex-row | 同上（重申 drawer） | 全宽 + 紧凑间距 | 显示 | 同上 |
| ≤420 | 小屏手机 | flex-row | 同上 | 更紧凑字号/间距 | 显示 | 同上 |

### 6.4 移动端 Off-canvas 抽屉

≤1023 时，`.sidebar-panels` 切换为 `position:fixed` + `transform:translateX(-100%)`，
从屏幕左侧滑入/滑出。选择器**刻意省略 `.docked`**，使其不论桌面端默认为展开（350px）
还是收起（64px docked）都能正确触发抽屉。

- **打开**：点击 `#sidebarToggle`（汉堡按钮）→ `body.sidebar-open` → `translateX(0)`。
- **关闭**：三种方式均有效：
  1. 点击遮罩层 `.sidebar-scrim`（z-index:9990，位于面板 9991 之下）的**暴露区域**
     （即面板右侧未覆盖区域）；
  2. 按 `Escape` 键；
  3. 窗口 resize 至 ≥1024px 时自动关闭。

z-index 层级（移动端）：
```
  10000  设置弹窗（settings modal）
  9991   设置面板抽屉 (.sidebar-panels, position:fixed)
  9990   半透明遮罩 (.sidebar-scrim)
   ...   主内容区 (.main-content) 与视频等正常流元素
```

> ⚠️ Playwright 回归测试中点击 scrim 应使用**暴露区域坐标**（如 `x = vw - 15`），
> 而非 scrim 元素的几何中心（中心点落在抽屉上方，会被抽屉拦截）。

### 6.5 交互层

以下能力在 CSS 末尾以"additive layer"形式注入，不修改原有业务样式：

| 特性 | 实现方式 |
|---|---|
| 键盘焦点环 | `:focus-visible { outline:2px solid var(--accent-color); outline-offset:2px }` |
| 按钮 hover 微动效 | `transition:.2s`; hover `translateY(-1px)`; active `scale(0.97)` |
| 处理中脉冲动画 | `.status-badge.processing { animation:statusPulse 1.4s infinite }` |
| 减弱动画偏好 | `@media(prefers-reduced-motion:reduce)` 全局将 transition/duration 归零 |
| ARIA 状态播报 | 连接状态 `<span role="status" aria-live="polite">`；按钮带 `aria-label`/`aria-controls`/`aria-expanded` |

## 7. 后续演进路线（建议）

1. **短期（已完成）**：CDN SRI + CSP + 消毒审计 + 响应式重构。零回归风险。
2. **中期**：把 `index.html` 的两个内联脚本按 `capture_*.js` 的模式拆成 ES Modules
   （chat / video / config / ws / state），并引入轻量 `createStore` 集中状态。
   拆分时**必须**配无头浏览器冒烟测试，避免上次出现的函数复制/截断问题。
3. **长期**：引入 Vite + TypeScript，把内联脚本彻底模块工程化。
