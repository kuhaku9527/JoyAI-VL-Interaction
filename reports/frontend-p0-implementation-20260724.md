# JoyAI-VL-Interaction — 前端 P0 实施报告（前端对话）

> 角色：前端对话（joyai-frontend-webui）｜日期：2026-07-24
> 靶子：`reports/code-health-audit-20260723.md` §1 + `reports/frontend-review-20260723.md`
> 范围：P0 最小集（前端测试底座 + CSS 设计令牌外置 + WCAG a11y 第一轮）
> 路线：专项报告明确**不推荐 React/Vue 整体重写** → "现代化 vanilla" 路线，只补质量基线，不改 DOM 命令式逻辑。

---

## 1. 前端现状（实测校正）

| 维度 | 实测 | 说明 |
|---|---|---|
| 主文件 | `index.html` **9,438 → 5,739 行** | 抽出整块 `<style>`（line 31–3731，~3,700 行 CSS） |
| CSS | 原报"3 个 `<style>` 块" → 实为 **1 个巨型块**；`style=` 内联 **53**；6 位 hex **73** | 已外置 + 令牌化 |
| 框架/构建 | 0 框架 / 0 `type=module` / 0 构建 / 0 TS | 维持 vanilla（P1 再上 Vite） |
| 可访问性 | `aria-/role=` 仅 **14**；`#sidebarToggle` 已有 aria 且 `aria-expanded` 已同步 | a11y 第一轮已补齐按钮 + 焦点陷阱 |
| 测试 | **0 → 24 用例**（Vitest+jsdom，全绿） | 最大质量缺口已补 |

---

## 2. 已完成的改动

### 2.1 前端测试底座（最大质量缺口）
- 引入 **Vitest 4.1.10 + jsdom 29.1.1**（选 Vitest 而非 Playwright：零浏览器二进制、CI 快、直接覆盖外置模块纯逻辑；报告允许 Vitest+Testing Library）。
- 4 个测试文件覆盖外置模块的纯逻辑：
  - `tests/joy_ws.test.js`（6）：**WS 连接 happy-path**（mock `WebSocket`→`onopen`→`updateStatus('Connected','connected')`）、`applyApiSettings` 发 `update_model`、`cleanupServerSession` POST。
  - `tests/render_markdown.test.js`（7）：`escapeHtml`、XSS 兜底、链接 `target=_blank`。
  - `tests/sanitize_static_html.test.js`（6）：`isSafeStaticUrl` / `sanitizeStaticCss` / DOM fallback 丢 `<script>`+`on*`。
  - `tests/config_services.test.js`（5）：`readForm`/`writeForm`/`setBadge`/`save` PUT。
- `package.json` 加 `"test": "vitest run"`；`.github/workflows/quality.yml` 加 **`frontend-test` job**（node20 + `npm ci` + `npm test`）。
- **结果：24/24 通过，CI 门禁现守护 9.4k 行 UI 的外置逻辑。**

### 2.2 CSS 设计令牌外置
- 抽整块 `<style>` → `static/styles.css`（112KB，独立缓存）；`index.html` 换 `<link rel="stylesheet" href="styles.css">`。
- CSP `style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net` 兼容外部表（`'self'` 放行）。
- `:root` 补 **20 个高频 hex 基元令牌**（`--joy-ffffff` 等），全文件 top-20 hex 替换为 `var()`（行内 `style=` 同步替换；**JS 字符串绝不碰**，避免 canvas `fillStyle` 等被破坏）。
- **顺手修复潜在 bug**：原内联 `:root` 的语义令牌（`--joy-red`/`--bg-primary`…）引用 `--joy-c81e2a`/`--joy-080707` 这批基元，但**原文件从未定义**——是悬空引用，之前这些颜色其实无效；现在才真正按预期生效（属修正，非回归）。
- 遗留（非 P0、待清理）：原 style 块历史就有括号差 1（line ~1581 多余 `}`），浏览器可容错。

### 2.3 a11y 第一轮（WCAG 2.1 AA 起步）
- **抽屉焦点陷阱**：文件末尾独立 IIFE（5712–5787）扩展 `setOpen`——打开时焦点移入 `.sidebar-panels` 并 Trap `Tab`、关闭时归还焦点给 `#sidebarToggle`；开时设 `role="dialog"`+`aria-modal`。抽屉开关按钮原有 `aria-label/controls/expanded` 且 `aria-expanded` 已由 `setOpen` 同步（确认无缺口）。
- **按钮访问名**：脚本给 **22 个有 `title` 无 `aria-label` 的按钮**补 `aria-label`（与 tooltip 一致，含中文）；再给 **4 个 `prompt-preset-option`**（靠 `data-label`）补；`themeToggle`/`settingsClose` 单独补。现 27 个按钮全有可访问名。

---

## 3. 验证

- `npm test` → **24 passed**（Vitest 4 / jsdom 29）。
- `styles.css` 括号配平检查；`var(--joy-…)` 替换完整无悬空；`#sidebar`/`#main-content` 等选择器原样保留（抽屉布局未动）。
- CSP 兼容：`'self'` 放行外部样式表、`'unsafe-inline'` 放行内联 `style=`（行为不变）。
- eslint job 不受影响（仅 lint `static/*.js`，本次未改那些文件）。

---

## 4. 状态与下一步

- **未提交 / 未推送**：改动均本地未提交。注意 `quality.yml` 是 **workflow 文件**，推送须 **fine-grained PAT（workflow scope）** 或 `workflow_dispatch` 兜底（踩过坑，不要走 `gh` 的 `gho_` token）。待确认是否开 PR。
- **P1（未做，用户未要求）**：Vite + 真·ESM 替代 `window.Xxx`；增量 TypeScript；集中式状态 store。
- **P2（可选）**：组件库 / 设计系统、Core Web Vitals、统一错误/加载 UX、PWA。

**前端 Developer**：像素匠（前端对话）
**Implementation Date**：2026-07-24
**结论**：P0 质量基线（测试 + CSS 令牌 + a11y）已补齐；维持 vanilla，不重写框架。
