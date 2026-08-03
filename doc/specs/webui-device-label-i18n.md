# WebUI Device-Label i18n Spec（feat-webui-i18n-tests）

> 接管旧活儿 ⑦。本 spec 用于框定接手范围（接手纪律：无 spec 不得直接写码）。
> 参考：存档分支 `save/wt-webui-i18n-tests-571bcda`（tip `571bcda`）、标签 `archive/feat/webui-i18n-tests`（tip `78f477e`），两处 i18n 文件逐字节相同。

## Problem Statement

`main` 当前在 UI 里直接渲染**原始英文设备名**，没有任何设备标签本地化：

- `services/webui/src/joy_interaction_webui/static/index.html:1028` 摄像头下拉用原始 `device.label || \`Camera ${index + 1}\``；
- `index.html:4093` 蓝牙麦克风 chip 用原始 `deviceText || '--'`。

历史上 PR #56（`b5781c8` "localize runtime device labels to Chinese"）做过内联 `localizeDeviceLabel()`，但**从未合入 main**（只活在 `feat-q2-emit` 与存档分支上）。因此本任务标题写的"抽出 i18n 做测试"与现状**错配**——main 上根本没有可抽出的东西。正确解读是 **新增 + 接线 + 测试**（见 Solution 与 Scope）。

## Solution

新增一个独立的前端本地化模块，并把 main 上两处设备名渲染点接到它：

- 新增 `services/webui/src/joy_interaction_webui/static/i18n_device_label.js`：IIFE 挂 `window.JoyI18n = { localizeDeviceLabel, DEVICE_LABEL_MAP }`。
  - `DEVICE_LABEL_MAP`：有序数组，元素为 `[RegExp, zh]`（most-specific 在前）。覆盖常见相机/音频/蓝牙设备名（约 18 条，如 `OBS Virtual Camera→OBS 虚拟摄像头`、`Integrated Webcam→内置摄像头`、`Bluetooth→蓝牙`、`Headphones→耳机`）。
  - `localizeDeviceLabel(label)`：falsy 输入原样返回；否则按 `DEVICE_LABEL_MAP` 顺序用 `String.replace` 逐条替换；未知标签（含已是中文的）**原样透传**（保守设计，绝不乱翻）。
- 新增 `services/webui/tests/i18n_device_label.test.js`：vitest + jsdom，8 个 `it` 用例覆盖（见 Testing Decisions）。
- 改 `index.html`：在 `<head>` 既有模块脚本之后加 `<script src="./i18n_device_label.js"></script>`；把 `:1028` 与 `:4093` 两处渲染改用 `window.JoyI18n.localizeDeviceLabel(...)`。

## User Stories

1. As a Pilot, I want camera / mic device dropdowns to show Chinese names, so that I can pick the right device without guessing English labels.
2. As a developer, I want the label map + localization logic covered by a unit test, so that the most-specific-wins ordering and passthrough behavior cannot regress silently.

## Implementation Decisions

- **手动移植，禁止 cherry-pick** `571bcda`：存档分支带了大量无关 drift（drift-gate、memory-store、`tail_logs.ps1`、PR #49–#56 等），且 `index.html` 的 hunk 在 main 上对不上（内联函数本就不存在、调用点字符串不同）。只取 3 个 i18n 文件内容，**逐文件手写**进 `feat/webui-i18n-tests`（从 `main` 起）。
- 沿用既有 `window.JoyX` IIFE 约定（`JoySanitize` / `JoyRender` / `config_services` / `joy_ws` 同款），不另起框架。
- **zh-only by design**：本模块只是设备标签中文化，不是通用 i18n 框架；不做 locale 切换、不做其他语言。
- 零配置改动：`services/webui/vitest.config.js`（`environment: 'jsdom'`、`globals: true`、`include: ['tests/**/*.test.js']`）与 `package.json`（`"type": "module"`、`vitest@^4.1.10`、`jsdom@^29.1.1`、`eslint@^9`）已就位，直接放文件即可跑。
- 行尾：新文件与 `index.html` 改动均**对齐仓库 CRLF 约定**（无 `.gitattributes` 强制，但保持与相邻 `static/*.js` / `index.html` 一致）。

## Testing Decisions

- 新增 `tests/i18n_device_label.test.js`（side-effect import + `window.JoyI18n` 断言，与现有 `tests/*.test.js` 同款）：
  1. `DEVICE_LABEL_MAP` 为非空 array；
  2. 相机名 → 中文（≥10 例）；
  3. 音频名 → 中文（≥8 例）；
  4. **most-specific-wins**（≥3 例：`Integrated Webcam→内置摄像头`，不被 "Integrated 摄像头" 误伤）；
  5. 未知标签透传（`Logitech BRIO` 不变）；
  6. 已中文不二次翻译；
  7. 空 / `null` / `undefined` 原样返回；
  8. 多关键词组合（`Bluetooth Headset→蓝牙 耳机`）。
- 本地验证：`cd services/webui && npm test`（vitest run）+ `npm run lint` / `npx eslint i18n_device_label.js`（依赖齐则跑；不齐则交由 CI 的 `frontend-test` / `eslint` job 验证）。
- 可选回归用例（非强制）：`Webcam Camera→摄像头 摄像头`（顺序 replace 的已知无害边角）。

## Out of Scope

- 通用 i18n / locale 切换 / 除设备标签外的其他语言。
- 存档分支的所有无关 drift（drift-gate、memory-store、`tail_logs.ps1`、PR #49–#56 等）。
- 后端改动；VLM / ASR / TTS 链路改动。

## 约法三章合规（接手前置校验）

- **不静默**：未知/已中文透传是**有意设计**（非吞错），调用点仍保留 `|| 兜底名` 兜底；✅。
- **不盲 except**：模块无 try/except，无可吞异常；✅。
- **必 log**：纯 map 工具无需 log；可选对未识别标签打 debug-log 以便扩充 map（nice-to-have，非必需）；✅（无违反）。
- **增新删旧**：存档提交删掉了内联函数（无双源）；main 上本无内联函数可删，移植后无残留；✅。

## Further Notes

- 接手分支：`feat/webui-i18n-tests`（从 `main` 起，存档 `archive/feat/webui-i18n-tests` 仅作内容兜底，不 cherry-pick）。
- 验证通过后走 reviewer 约法三章门禁 → squash-merge 合 `main` → 删分支。
- 真·内容已交付后，`save/wt-webui-i18n-tests-571bcda` 与 `archive/feat/webui-i18n-tests` 可随分支大扫除清理（留标签兜底即可）。
