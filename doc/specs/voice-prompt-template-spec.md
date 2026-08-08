# Spec：语音专用 Prompt 模板（voice_prompt 拼接）
> 生命周期：草稿（2026-08-06 由审查组依 D-2026-08-06-001 派生）
> 上游决策：决策/调研-HF-speech-to-speech-姿态.md（Prompt 模板 = 学）

## §1 因果链（Why）
- **Why**：当前 `[response]` 之后送 TTS 的文本可能含 `**粗体**` / `*斜体*` / 列表 / `(laughs)` 等，TTS 会念出「星号粗体」或表情蛋；且角色 prompt 走 bt-7274 配置，无语音输出专用裁剪（`grep` 全目录无 `no markdown`/`laughs` 约束）。
- **被否方案**：① 只在 TTS 端 strip（治标，LLM 仍可吐 markdown 影响语义）；② 全局改 system prompt（会污染非语音模式）。→ 选「LLM 端 voice_prompt tail 强约束」+ TTS 端轻量 strip 双保险（见 §10.4 预处理）。
- **不影响决策 token**：决策 token 由 VLM 自训练输出，不走 prompt 注入；本改动只影响 `[response]` 之后的 TTS 文本。

## §2 范围与负面约束（What NOT）
- **做**：在 `services/webinfer/system_prompts.py` 增 `compose_voice_prompt(session_prompt, tool_section)`，tail 放最强约束（「通常一句话；不要 markdown；不要 *laughs*；先说话再调用工具」）。
- **不做**：不改动 bt-7274 角色配置主结构；不动 decision token 解析；不引入新 LLM 调用。
- **负面约束**：禁止为语音模式单独起一份完整 system prompt 副本（维护双份会漂移）——必须复用 `compose_system_prompt_with_memory` 后追加 voice tail。

## §3 方案（What）
- 落点 `system_prompts.py:compose_system_prompt_with_memory`(L297) 之后增 `compose_voice_prompt`。
- tail 约束结构参照 s2s `voice_prompt.py` 三段：lead → session → tail，最强约束在 tail（LLM 注意力衰减规律的反向利用）。

## §4 Harness
- 无（一次性 feature，无跨任务复用固定流程）。验收 = 单测 `compose_voice_prompt` 输出含 tail 约束且不含 markdown 诱导。

## §5 验收
- `tests/test_system_prompt_memory.py` 增用例：voice prompt 输出末尾含「不要 markdown」类约束。
- 手验：Jarvis 模式 `[response]` 后 TTS 不再念出星号/表情蛋（对照 §10.4）。

## §10.4 预处理（TTS 端轻量 strip 双保险）
§1 选定「LLM 端 voice_prompt tail 强约束 + TTS 端轻量 strip 双保险」，本节约为后者落点（由 issue #109 实现）。

- **落点**：`services/tts/tts_adapter.py` 的纯函数 `strip_markdown(text: str)`（仅依赖 `re`，无嵌套同定界符量词、无灾难性回溯）。在 `run_tts_session` 送上游前的最后一关以
  `text = strip_markdown(normalize_text("".join(buffered_text)))` 接线，**vLLM 与 voice-clone 两路都拿到剥离后文本**（接线位于 voice-clone 分支之前）。
- **剥离项**：行首标题 `#+`、引用 `> `、无序/有序列表 `- / * / + / 1. / 1)`、行内代码 `` `x` ``、链接 `[label](url)`→label、粗体 `**x**`/`__x__`、斜体 `*x*`/`_x_`、围栏代码块标记（保留内部文本）、分隔线 `---`/`***`/`___`（整行删除）；末尾 `" ".join(body.split())` 折叠多余空白。
- **边界保护**：斜体/下划线用 ASCII-only 边界 `(?<![A-Za-z0-9*])` / `(?<![A-Za-z0-9_])`，避免误剥 `my_var` / `2*3` 类标识符；中文嵌入的强调（如 `说*强调*吧` → `说强调吧`）正常剥离。
- **单测**：`services/tts/tests/test_tts_markdown_strip.py`（23 例，覆盖中文嵌入斜体/下划线、ASCII 标识符保留、缩进标题/列表、链接/代码块/分隔线、组合与幂等）。
- **门禁**：`quality.yml` 的 pytest 矩阵已含 `tts`（CI 实际 collects 上述测试）；ruff 对 `services/tts` 走 `--extend-ignore D103,SIM105,D102,D101,RUF001`。
