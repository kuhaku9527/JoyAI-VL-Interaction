# 架构 Review 备忘录 · 2026-07-22

> 范围：以 G1~G6 已交付架构文档（资料摘要 / 调研 / 高层 / 系统设计 / UserStory / 部署 / 安全 / G6 汇总）为基准，对**当前已落地的前后端实现**做一致性 review，判断文档是否需要补充。
> 方法：主理人直接审代码（端口、服务结构、前端外置模块、后端拆分、新增能力），与冻结边界（D4 + ADR0001~0008 + 高层 D1~D5 + 系统设计）逐条比对。未重启架构团队（本回合是 review + 判断，非重新设计）。

## 结论（TL;DR）

**需要补充，但属于"实现跑在文档前面"的回填，不是推翻重写。**

- ✅ **核心运行时拓扑仍然成立**：决策 token（`silence`/`response`/`delegate`）在 `index.html` 仍在使用；端口 8070/7060/8996/8079/8642 与 ADR0004 对齐；webinfer 后端拆分（adapter_core 协调器 + 子模块）符合 ADR0007；前端 Blocks 1-6 外置模块（`render_markdown/sanitize_static_html/config_services/joy_ws/capture_*`）全部就位于 `services/webui/.../static/`。
- ❌ **文档在 4 个具体点上落后/矛盾**，需增补（详见下）。其中 1 项（TTS 端口三分裂）若不修正，会直接导致安全设计的防火墙规则漏放端口、语音不可用。

## 审查证据

| 检查项 | 代码事实 | 架构文档现状 | 判定 |
| --- | --- | --- | --- |
| 决策 token | `index.html` 仍用 silence/response/delegate | 高层/系统设计已定义 | ✅ 一致 |
| 服务端口 | 8070/7060/8996/8079/8642 对齐；TTS 实际 8985(voice-clone)/8992(tts-adapter ws)/8991(本地TTS上游) | ADR0004 冻结"TTS adapter 8985"单端口 | ❌ 矛盾（见 B4） |
| webinfer 拆分 | `adapter_core.py` + 9 子模块 + facade | ADR0007 | ✅ 一致 |
| 前端外置模块 | 7 个 `window.Joy*` JS 在 static/ | Blocks 1-6 已记录 | ✅ 一致 |
| memory-store 后端 | `get_backend()` 支持 sqlite/**psql**/**obsidian**（`MEMORY_BACKEND` env） | ADR0005 冻结"v0.1 仅 sqlite" | ❌ 矛盾（见 B3） |
| Jarvis 模式 | `jarvis_mode/jarvis_session/jarvis_routes` + KWS 唤醒 + hybrid-wake 恢复 | G1~G6 完全未覆盖；`doc/jarvis-mode.md` 不存在（server.py 注释引用 v3.22 却无文件） | ❌ 缺失（见 A1/A2） |
| WebUI 角色 | aiohttp 服务：WebRTC + 静态宿主 + ASR/TTS/VLM 客户端桥接 + Jarvis 编排 | 文档视为"纯静态 monolith" | ⚠️ 需澄清（见 C5） |
| ADR0008 | P0 适配器修复已完成（`doc/adr/0008-*`） | G4 系统设计未引用 | ⚠️ 需补引用（见 C6） |

## 必须补充的条目

### A. 新增能力（文档完全缺失）

- **A1 · Jarvis 常驻语音模式架构**：webui 内含完整状态机（`JarvisState` + `JarvisSessionManager` + jarvis 路由），含唤醒词触发、hybrid-wake 恢复、session 生命周期。这是一套新产品能力，需在系统设计补一节：状态机、唤醒触发边（KWS→Jarvis）、与决策 token 循环（silence/response/delegate）的协作关系、降级路径（唤醒失败/ASR 超时回退）。
  - 配套动作：新建 `doc/jarvis-mode.md`（server.py 已引用却缺失），否则代码注释悬空。
- **A2 · KWS 唤醒集成边界**：sherpa-onnx KWS（`services/asr/jarvis/kws.py`）作为 Jarvis 唤醒源接入 webui。ADR0002 只规定"KWS 参数→环境变量"，未说明它作为唤醒触发器驱动新交互。需在接口/数据流章节补 KWS→Jarvis 触发边与失败回退。

### B. 与冻结边界矛盾（必须修正）

- **B3 · memory-store 多后端 vs ADR0005**：实现已支持 psql/obsidian 插件式后端（`MEMORY_BACKEND` 切换），但 `__version__` 仍写 `0.1.0` 且 ADR0005 冻结"v0.1 仅 sqlite"。建议补 **ADR0005 修订（v0.1.1 允许插件式后端，默认 sqlite）** 或新增 ADR0009，否则交付文档与代码直接矛盾。
- **B4 · TTS 端口三分裂 vs ADR0004 / 安全设计**：实际为 8985=voice-clone API、8992=TTS adapter(ws)、8991=本地 TTS 模型上游。安全设计 §5.2 防火墙规则仅放通 `8099/8070/8985/ops`，**漏放 8991/8992 会直接致语音不可用**。部署设计 §2/§3 与 ADR0004 端口表须更新为三端口，防火墙规则同步补齐。

### C. 表述需对齐现实（澄清类）

- **C5 · WebUI 双角色**：系统设计 §3 / 部署设计 §3 应把 webui 重新定义为"前端宿主 + 本地桥接后端"——它既 serve `index.html`，又持有 ASR/TTS/VLM 客户端路由与 WebRTC。并厘清 webui↔`services/asr`、`services/tts`、`services/voice-clone` 的边界（webui 持 WS/路由，外部服务持推理）。
- **C6 · ADR0008 引用**：P0 适配器修复（决策解析统一 / 常量收敛 / 并发竞态）已完成，G4 系统设计未引用，补充引用即可。

## 不需改动（保持冻结）

- 决策 token 协议、webinfer 8070 单入口网关（ADR0006）、MiniMax Rapid Clone 同步路径（ADR0001）、live_adapter 拆分（ADR0007）、高层 D1~D5（本地优先/单机/MVP 边界）。

## 补充优先级建议

1. **B4**（漏放端口→语音故障，最高）— 改 ADR0004 + 部署 §2/§3 + 安全 §5.2。
2. **A1/A2**（Jarvis 无文档，产品核心新能力）— 新增系统设计章节 + `doc/jarvis-mode.md`。
3. **B3**（ADR0005 矛盾）— ADR 修订。
4. **C5/C6**（表述对齐）— 文档澄清。

## 工作量估计

约 1 个中等架构补丁：1 份修订 ADR（或新建 ADR0009）+ 系统设计补 1 节（Jarvis）+ 部署/安全各改端口表与防火墙规则 + 新建 jarvis-mode.md。不触及已冻结核心边界。

---
*本备忘录为 review 结论，非重新设计。是否据此开补充 PR / 由前端或后端对话落地代码侧修正，请主理人裁决。*
