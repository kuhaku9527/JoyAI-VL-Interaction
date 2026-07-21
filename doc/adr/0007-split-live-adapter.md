# ADR 0007 — 拆分 live_adapter.py 巨文件为模块化结构

- **状态**：Accepted
- **日期**：2026-07-20
- **作者**：WorkBuddy

## 背景

`services/webinfer/live_adapter.py` 在拆分前是一个 **3531 行** 的单体文件，承载了实时视频-语言交互适配器（`StreamingInferAdapter`）的全部职责：配置、会话状态、请求解析、提示词构建、回复格式化、I/O 工具、时间区间工具、aiohttp 应用工厂与 CLI 入口。

问题：

1. **可维护性差**：单次修改动辄需要通读数千行；新增/修改变更的回归面过大。
2. **审查困难**：PR 差异巨大，reviewer 难以聚焦；`git blame` 信息被单体污染。
3. **测试脆弱**：外部（如 `services/webui`、`test_jarvis_webinfer_e2e.py`）直接引用 `AdapterConfig` / `StreamingInferAdapter` 及 `la._xxx` 私有属性，单体结构下尚可，单体一旦改名/重组极易断裂。
4. **职责混杂**：一个文件里同时有数据类、HTTP 路由、内存摘要路由、文件系统工具，违反单一职责。

团队技术提升诉求（见根目录清理与 `doc/standards/`）要求把"巨文件"作为重点治理对象，先做**机械安全拆分**并保留外部契约，再逐步做**深度重构**。

## 决策

**将 `live_adapter.py` 拆分为聚焦职责的子模块，同时保留 `live_adapter.py` 作为门面（facade）做全量 re-export，外部契约完全不变。**

拆分采用 **AST 生成器机械切分**（按函数名 → 目标子模块映射表生成子模块与门面），而非手工拷贝，以避免漏拷/错拷。

## 目标布局（里程碑 1 落地后）

| 模块 | 行数 | 职责 |
| - | - | - |
| `live_adapter.py` | 53 | 门面：re-export 全部公共/私有符号，`main()` 入口 |
| `adapter_types.py` | 195 | 数据类 `AdapterConfig`、`SessionState` |
| `config.py` | 113 | 配置加载与环境变量解析（`_env_bool/_env_int/_env_float/_split_paths/reset_chunk_state`） |
| `prompt_building.py` | 238 | 系统提示词与消息体构建、上下文裁剪 |
| `time_ranges.py` | 228 | 时间区间解析与归一化 |
| `response_format.py` | 296 | 模型输出归一化与回复载荷格式化 |
| `io_utils.py` | 239 | 文件系统/输出路径工具、URL→路径解析 |
| `request_parsing.py` | 237 | 入站请求解析（文本/图像/时间区间） |
| `adapter_core.py` | 1992 | 核心 `StreamingInferAdapter`（实时交互主循环） |
| `app.py` | 608 | aiohttp 应用工厂 `create_app`、参数解析 `parse_args`、CLI 入口 `main` |

> 注：`memory_summarizer.py`、`memory_store_client.py`、`system_prompts.py` 为既有模块，不在本次拆分范围。

## 外部契约约束（不可破坏）

- **console script**：`pyproject.toml` 中 `joyvl-webinfer-adapter = "live_adapter:main"`。
- **直接运行**：`python live_adapter.py`（走到 `if __name__ == "__main__": main()`）。
- **库导入**：`from live_adapter import AdapterConfig, StreamingInferAdapter, ...`。
- **脆弱测试引用**：测试通过 `StreamingInferAdapter.__init__.__globals__["AdapterConfig"]` 与 `la._xxx` 属性访问内部符号；门面 `__all__` 已显式 re-export 这些私有助手（`_compute_prompt_guard_max_chars`、`_estimate_messages_chars`、`_trim_messages_to_ctx`、`_env_bool/_env_int/_env_float/_split_paths`、`_chat_completion_response`、`_openai_error_response`、`_short` 等）以维持兼容。

## 里程碑 1（已完成）：代码优化 + 模块化

- 用 AST 生成器按映射表切分，生成 9 个子模块 + 门面，规避手工拷贝错误。
- 验证手段：`cd services/webinfer && python -m pytest tests/ -q` → **66 passed**。
- 拆分过程中发现并修复的真实缺陷：
  1. `@dataclass` 装饰器在 `AdapterConfig` / `SessionState` 上丢失 → `SessionState() takes no arguments`，已补回装饰器。
  2. 模块名 `types.py` 遮蔽标准库 `types` → 重命名为 `adapter_types.py`。
  3. `SessionState` 的 `default_factory=reset_chunk_state` 在类体求值时 `reset_chunk_state` 未导入 → `adapter_types.py` 顶部 `from config import reset_chunk_state`。
  4. 跨模块助手未 import 导致 `F821`：`request_parsing.py` 缺 `_file_url_to_path`(io_utils)/`_normalize_time_range_text`(time_ranges)；`response_format.py` 缺 `_parse_start_second`(time_ranges)；`app.py` 缺 `sanitize_output_name` 等(io_utils)。已补齐且**确认无循环导入**（`config` 不反向 import `adapter_types`；子模块均不反向 import `adapter_core`/`live_adapter`）。
  5. 生成器把整段 import 块拷进每个子模块 → 大量 `F401`，已 `ruff --fix` 清除 237 处。
  6. 机械拆分把跨模块 import 放在模块级常量**之后** → `E402`×12，已将 import 整体前移；并补 `D100` 模块 docstring。

## 里程碑 2（待办）：`StreamingInferAdapter` 内部职责进一步解耦

`adapter_core.py` 仍有 **1992 行 / 约 66 个方法 / 5 个职责簇**（会话生命周期、主推理循环、内存摘要路由、记忆读写、提示词装配）。建议下一轮按职责簇拆为 `session.py` / `infer_loop.py` / `summarizer_routing.py` / `memory_io.py` / `prompt_assembly.py`，同样经 `adapter_core.py` 门面 re-export。

## 里程碑 3（待办）：类型与文档现代化

当前残留的 `UP007`（`X | Y`）、`RUF001`（全角标点，中文文案不可避免）、`D102`/`D103`（方法/函数缺 docstring）绝大多数是**单体时代就存在的风格债**，拆分后随代码迁移到新模块，已计入项目 lint 基线（`doc/standards/lint-baseline.md`）。建议作为独立一轮清理，不在本次拆分范围内追平。

## 风险与缓解

- **循环导入**：已静态确认无子模块反向 import `adapter_core`/`live_adapter`；`config` 不 import `adapter_types`，故顶部 import 安全。门面与子模块均通过 `from __future__ import annotations` 隔离注解期依赖。
- **环境依赖**：`memory_summarizer.py` 在 `SummarizerModel.__init__` 内懒导入 `transformers`。部署环境（requires-python 3.12）需安装该包；本 lint/测试 venv 未装不影响拆分验证（66 测试不触发该路径）。
- **测试脆弱性**：已通过门面 `__all__` 全量 re-export 私有符号，兼容现有 `la._xxx` 与 `__init__.__globals__` 测试引用。

## 验收标准

- [x] `pytest services/webinfer/tests/` 全绿（66 passed）。
- [x] 新模块无 `F401`/`F811`/`F821`；`E402`/`I001`/`D100` 已修复。
- [x] 门面契约可用：`python -c "import live_adapter; live_adapter.parse_args(); live_adapter.create_app(...)"` 解析正常；console script 与 `from live_adapter import X` 路径保留。
- [x] 临时拆分脚本（`_split_gen.py`、`_live_adapter_orig.py`）不入库，已删除。

## 后续修订

（本 ADR 落地后如有新决策，记录于此。）
