# 审查结论 + 全仓 Lint 扩容方案（2026-07-22，已校正）

> 角色：code-review 对话。**本文件是审查结论与执行方案（handoff），不直接改源码/CI 配置。**
> JS/eslint 部分 → 前端对话执行；Python/ruff/quality.yml 部分 → 后端（或 devops）对话执行。
> **校正说明**：初版曾误报"webinfer 门禁红"，系用陈旧树(bbf8b61)+ruff 0.15.22 所致；已用 ruff 0.6.9(=CI 钉版) 跑最新 origin/main(b6b9fd0) 复核，结论见下。

---

## Part 1 — 审查（Review）

### 1.1 合并态代码审查（回溯）
- PR #2（P0 #2/#3/#4）、PR #3（前端 stale-refs）、PR #4（Block 5）、PR #5（ci/quality-gate）均已合入 `origin/main`（HEAD `b6b9fd0`）。
- 关键修复均已源码级落地（`asyncio.Event` 双检锁 / 委派任意位置优先 / `index.html` 守卫 / 常量收敛）。
- 逐行 review 结论：**0 blocker**（详见 `review_fullstatus_20260722.md`、`pr_review_p0_20260721.md`）。

### 1.2 当前 Lint/CI 家底（本次新审查，有证据）
| 维度 | 现状 |
|------|------|
| Python 配置 | 根 `pyproject.toml` repo-wide ruff（E/F/W/I/UP/B/C4/SIM/N/RUF/D）；`.pre-commit-config.yaml` 接 ruff-pre-commit（rev `v0.6.9`，**已钉版本**） |
| Python CI 范围 | `quality.yml` 的 `ruff` job **只扫 `services/webinfer`**；`package-smoke` job 是构建/导入冒烟测试（非 lint，且不涉及 JS） |
| JS 配置 | 全仓 **0 个 `package.json`、0 个 eslint 配置**；`quality.yml` **无任何 JS lint job** |
| 全仓 JS 体量 | 手写 JS = 7 文件（均 `services/webui/.../static/`）；另 1 个 `services/.venv/.../emscripten_fetch_worker.js` 是 vendored 虚拟环境文件，**必须排除** |
| workflow 总数 | **仅 `quality.yml` 一个** —— lint/format 是仅有的 CI 门禁 |

**实测（关键，已用两种 ruff 版本交叉验证 `origin/main` = `b6b9fd0`）：**

| 检查 | ruff **0.6.9**（= CI 钉版） | ruff **0.15.22**（现代本地版） |
|------|------|------|
| `ruff check services/webinfer` | ✅ **All checks passed!** | ❌ **102 errors**（86×`UP045` + 13×`RUF059` + 2×`RUF046` + 1×`RUF022`） |
| `ruff format --check` | ✅ **31 files already formatted** | ❌ 3 文件未格式化（`io_utils.py`/`prompt_constants.py`/`tests/test_text_chat_prompt.py`） |
| 备注 | PR #5 `ci/quality-gate` 已清洗，门禁**真绿** | 86 个 `UP045` 即旧码 `UP007`（被 ignore），format 差异为版本漂移 |

🟢 **结论 1（校正）**：webinfer 门禁在钉死版本下**是绿的**（PR #5 交付）。初版"红"是误报。

🔴 **结论 2（版本漂移 landmine，真问题）**：ignore 列表钉死 **0.6.9 的规则码 `UP007`**，而 webinfer 仍残留 **87 处 `Optional[X]` 注解**。一旦 ruff 升级到 ≥0.7，`Optional[X]` 变成 **`UP045`**（不在 ignore 列表）→ **86 个 lint 错误瞬间爆炸**；format 输出在 0.6.9→0.15.22 间也漂移（3 文件）。也就是说：**当前"绿"完全依赖永不升级 ruff**。本地开发者 `pip install -U ruff` 后已看到 102 错 + 格式红，而 CI 仍绿 → **信号分裂**。这是扩容前必须先解决的隐患。

🔴 **结论 3（前端说得对）**：全仓**无 JS lint 门禁**，且连 `package.json` 都没有，本地都跑不了 `npm run lint`。这是真实缺口。

### 1.3 JS 模块人肉 Lint 审查（7 个外置文件）
| 文件 | `'use strict'` | 引号 | 备注 |
|------|:---:|:---:|------|
| `joy_ws.js` | ✅ | 单 | 唯一带 strict；最规范 |
| `render_markdown.js` | ❌ | 单 | `_match` 未用参数用 `_` 前缀（good 约定） |
| `sanitize_static_html.js` | ❌ | 单 | 干净 |
| `config_services.js` | ❌ | 单 | const/let 规范 |
| `screen_capture.js` | ❌ | 单 | `catch{} // ignore` 注释，non-empty |
| `capture_webcam.js` | ❌ | **双** | 与下面一个文件双引号 |
| `capture_rtsp.js` | ❌ | **双** | 与上面一个文件双引号 |

- **仅 1/7 有 `'use strict'`**，其余 6 个没有。
- **引号风格分裂**：`capture_webcam`/`capture_rtsp` 双引号，其余单引号 → eslint `quotes` 一开 2 文件直接红（典型"装饰性债务"）。
- `console.warn/error` 普遍（浏览器 UI 文件，**不应**开 `no-console`）。
- 整体逻辑干净：无未定义变量、无裸 `except`、无 `eval`/危险动态执行。

---

## Part 2 — 全仓 Lint 扩容方案（分阶段）

### 总原则
1. **先消版本漂移，再扩大**：当前绿是"钉死 0.6.9"的假绿；扩容前必须把 `Optional[X]`→`X | None` 收口、ignore 列表对齐现代规则码，否则一升级全仓爆炸。
2. **每层"启用真 bug 规则 + 测量装饰性债务 + `--extend-ignore` 测量值"**，与 `quality.yml` 现有策略一致。
3. **每个 Phase 独立 PR**，便于 review 与回滚。
4. **版本单一真相源**：ruff 版本同时钉在 `quality.yml` + `.pre-commit-config.yaml` + 新增 `requirements-dev.txt`，本地与 CI 一致。

### Phase 0 — 建立 JS Lint 门禁（前端对话执行）
**目标**：`services/webui/` 引入 eslint，**先只扫 7 个外置 `.js`**。

**配置草稿**

`services/webui/package.json`：
```json
{
  "name": "joyai-webui-static",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "lint": "eslint .",
    "lint:fix": "eslint . --fix"
  },
  "devDependencies": {
    "eslint": "^9.0.0",
    "@eslint/js": "^9.0.0"
  }
}
```

`services/webui/eslint.config.js`（flat config）：
```js
import js from '@eslint/js';
export default [
  js.configs.recommended,
  {
    files: ['src/joy_interaction_webui/static/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: {
        window: 'writable', document: 'readonly', console: 'readonly',
        navigator: 'readonly', WebSocket: 'readonly', RTCPeerConnection: 'readonly',
        MediaStream: 'readonly', ImageCapture: 'readonly', Node: 'readonly',
        DOMParser: 'readonly', marked: 'readonly', DOMPurify: 'readonly',
        katex: 'readonly', setTimeout: 'readonly', setInterval: 'readonly',
        clearInterval: 'readonly', fetch: 'readonly', location: 'readonly',
        alert: 'readonly', HTMLElement: 'readonly',
      },
    },
    rules: {
      'strict': ['error', 'global'],                 // 要求 'use strict'
      'quotes': ['error', 'single', { avoidEscape: true }],
      'semi': ['error', 'always'],
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-console': 'off',                            // UI 文件合理打日志
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
  { ignores: ['**/.venv/**', 'node_modules/**', 'dist/**', '**/__pycache__/**'] },
];
```

`quality.yml` 新增 `eslint` job：
```yaml
  eslint:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: services/webui
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: npm ci
      - run: npm run lint
```

**执行步骤**：① `npm install` 生成并提交 `package-lock.json`（锁版本，防漂移）；② 给 6 个缺 `'use strict'` 的文件补上；③ `npm run lint:fix` 把 2 个双引号文件归一为单引号；④ 确认 7 文件绿后开 PR（base `main`）。`index.html` 内联 ~5600 行 JS **暂不纳入**（见 Phase 3）。

### Phase 1 — 消除版本漂移 + 钉版本（后端/devops 对话，优先于扩大 Python 范围）
1. **统一版本**：选一个现代 ruff（如最新 0.6.x 或 0.7+），同时更新 `quality.yml`(install 行)、`.pre-commit-config.yaml`(rev)、新增 `requirements-dev.txt`：`ruff==<选定版本>`。
2. **燃烧 `Optional[X]` 债务**：在 webinfer（及后续每包）跑 `ruff check --fix`（把 `Optional[X]`→`X | None`，消除 86 个 `UP045`/`UP007`）+ `ruff format`。
3. **对齐 ignore 列表**：旧 `UP007` 在新版对应 `UP045`（或已无需 ignore），按选定版本的规则码重写 `--extend-ignore`。
4. **验证**：本地与 CI 均 `ruff check .`/`ruff format --check .`（先限 webinfer）全绿，再合并。
> 这一步解决结论 2 的 landmine：从此"绿"不再依赖永不升级。

### Phase 2 — Python 逐个包扩大（后端/devops 对话）
服务包共 7 个，已扫 1 个（webinfer）。剩余：`memory-store`、`voice-clone`、`webui`(FastAPI Python 代码)、`asr`、`tts`、`background-agent`。

**每包流程**（镜像现有策略 + Phase 1 的债务燃烧）：
1. `ruff check <pkg> --statistics` 测装饰性债务分布。
2. `ruff check --fix` + `ruff format` 清洗（含 `Optional[X]`→`X|None`）。
3. 把剩余装饰性规则（`D101/D102/D103`、`RUF001/RUF003`、`SIM105/SIM108` 等）加入该包 `--extend-ignore`，保留 E/F/I/B/C4/SIM(非装饰)/RUF(非装饰) 等真 bug 规则。
4. 该包合并后绿，再进下一包。
5. 顺序建议：`memory-store → voice-clone → webui → asr → tts → background-agent`。

### Phase 3 — 前端内联脚本纳入
`index.html` 内联 ~5600 行 JS 是最大难点。选项：(a) 继续抽外置模块（Block 7+，收益递减、行为等价风险升）；(b) 用工具对提取片段 lint。
**建议**：暂不纳入 lint 范围，靠外置 7 文件 + 新代码规范约束；长期若抽模块再自然纳入。

### Phase 4 — 整仓 Gate（最终）
当所有包绿 + JS 绿后，`quality.yml` 的 `ruff` job 改为整仓：
```yaml
      - name: Ruff lint (repo-wide)
        run: ruff check . --extend-ignore <各包测量值汇总>
      - name: Ruff format check (repo-wide)
        run: ruff format --check .
```
保留 `archive/`、`icefall_src/`、`.venv`、`node_modules` 排除。装饰性债务此时已燃烧或明确 ignore，gate 稳定绿。

---

## 下一步
- **Phase 0（前端，JS 门禁）** 与 **Phase 1（后端/devops，消版本漂移+钉版本）** 可立即并行启动。
- Phase 1 完成后，结论 2 的 landmine 闭环，"绿"变为可持续。
- 建议测试对话在合并后的 `main` 跑一次 `services/webinfer/tests/` 回归套件（前次合并时未跑，确认跨分支无回归）。
- 各 Phase 独立 PR，按依赖顺序合并。
