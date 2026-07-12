---
title: WebUI 视觉与交互规约
status: active
last_updated: 2026-07-12
related:
  - architecture-local.md
  - api-optimization.md
  - specs/webui-kws-listening-chain.md
  - specs/webui-asr-input-state.md
---

# Voice UI 规约

本文档记录 JoyAI-VL-Interaction WebUI 中与 BT-7274 语音链路相关的视觉与交互约定。
所有 WebUI 调整改完 CSS / HTML / JS 后，必须同步本文档对应小节，否则视为不一致。

## 1. HUD 右上角状态条（header-right）

### 1.1 元素清单
从左到右依次为：

| 序号 | 元素 | 类型 | 说明 |
| --- | --- | --- | --- |
| 1 | jarvisStatus | `.status-badge.disconnected` / `.connected` | WebSocket 连接状态，文本 `Disconnected` / `Connected` |
| 2 | llmBadge | `.status-badge.llm-unknown` / `.llm-ok` / `.llm-err` | LLM 健康状态，文本 `LLM ?` / `LLM OK` / `LLM ERR` |
| 3 | ttsBadge | `.status-badge.llm-unknown` / `.llm-ok` / `.llm-err` | TTS 健康状态，文本 `TTS ?` / `TTS OK` / `TTS ERR` |
| 4 | kwsBadge | `.status-badge.llm-unknown` / `.llm-ok` / `.llm-err` | KWS 健康状态，文本 `KWS ?` / `KWS OK` / `KWS ERR` |
| 5 | jarvisExtra | `.status-badge.jarvis-disconnected` / `.jarvis-connected` | Jarvis 后端额外状态，文本 `Jarvis ?` / `Jarvis OK` |
| 6 | settingsBtn | `button.settings-btn` | 打开 Settings Modal，仅图标 |
| 7 | themeToggle | `button.theme-toggle` | 浅色 / 深色主题切换，文本 `Dark` / `Light` |

### 1.2 视觉分组约束
1. 元素 1-5 是「状态徽章区」，视觉上必须连续。
2. 元素 6-7 是「控制区」，与状态徽章区之间必须有视觉分隔。
3. 实现方式：`.header-right` 设置 `gap: 10px`，并在 `.settings-btn` 上：
   - `margin-left: 4px`
   - `padding-left: 14px`（在 `.theme-toggle` 同款 padding 基础上多加 4px 形成左侧呼吸空间）
   - `box-shadow: inset 1px 0 0 rgba(255, 255, 255, 0.28)`（画一根 1px 半透明白色分割线）
4. 调整任何徽章或按钮的 padding / margin 后，必须重新走 `getBoundingClientRect()` 验证：
   - 状态徽章彼此 `gap_left` 应稳定在 10px
   - 第 5 个徽章 -> settingsBtn 的 `gap_left` 应 >= 14px
   - settingsBtn -> themeToggle 的 `gap_left` 应稳定在 10px
   - `.header-right` 总宽控制在 `min(680px, 100%)` 以内，避免溢出

### 1.3 已知修复记录

#### 1.3.1 2026-07-12 HUD 重叠（518px 拥挤）

**症状**：5 个状态徽章 + 2 个控制按钮挤在 499px 内，无视觉分组，从左至右密集排列，眼睛难以区分。

**修复方案**：
- `.header-right` `gap: 8px -> 10px`
- `.settings-btn` 改为 `padding: 8px 12px 8px 14px`，新增 `box-shadow: inset 1px 0 0 rgba(255, 255, 255, 0.28)` 与 `margin-left: 4px`

**修复前后实测布局**：

| 区域 | 修复前 gap_left | 修复后 gap_left |
| --- | --- | --- |
| jarvisStatus -> llmBadge | 8px | 10px |
| llmBadge -> ttsBadge | 8px | 10px |
| ttsBadge -> kwsBadge | 8px | 10px |
| kwsBadge -> jarvisExtra | 8px | 10px |
| jarvisExtra -> settingsBtn | 8px（无分隔） | 14px（含 4px margin + 视觉分隔） |
| settingsBtn -> themeToggle | 8px | 10px |
| `.header-right` 总宽 | 499px | 518px |

**改动文件**：`services/webui/src/joy_interaction_webui/static/index.html`
- `.header-right` 块（约 line 154）
- `.settings-btn` 块（约 line 187-197）

**截图**：
- `.pids/after_overlap_fix_step2.png`
- `.pids/after_overlap_fix_step2.jpeg`
- `.pids/after_overlap_fix_step3.jpeg`

## 2. 主题与色板

- 深色主题为默认（`.theme-toggle` 文本 `Dark`，点击切换到浅色并显示 `Light`）。
- 状态徽章色板由 `.status-badge` 系列定义：
  - `.connected` / `.llm-ok` / `.jarvis-connected` -> 健康色
  - `.disconnected` / `.jarvis-disconnected` -> 未连接色
  - `.llm-unknown` -> 未知 / 轮询中
  - `.llm-err` -> 错误
- 不允许使用单一色调家族作为整个 HUD 主色（如全紫 / 全蓝）。

## 3. 待补章节

- 聊天面板布局（消息气泡、用户/助手区分、延迟时间戳）
- KWS 监听模式下的音频波形 / RMS 指示器
- ASR 输入框状态机（idle / recording / final / error）
- 设置 Modal 内字段
