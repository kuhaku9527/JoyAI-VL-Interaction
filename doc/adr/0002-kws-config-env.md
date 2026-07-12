# ADR 0002 — KWS 配置改成 env 化

- **状态**：Accepted
- **日期**：2026-07-11
- **作者**：Codex

## 背景

用户要求：`bt` 唤醒词改成英文（已经是 BPE token `B T @bt`），并对"很干净、没有杂声"的录音调参。
但当前 `services/asr/jarvis/kws.py` 把 `keywords_score=10.0` / `keywords_threshold=0.25` / `trailing_blanks=1` / `max_active_paths=10` **硬编码**在构造器默认值里，没有 env 钩子。

用户不能在不重启 webui + 改源码的情况下做"扫参数"。

## 决策

把 KWS 4 个调参项改为**读环境变量**，保留硬编码默认值。

| Env | 默认 | 推荐范围（干净 16 kHz mono mic）|
| - | - | - |
| `JARVIS_KWS_SCORE` | 10.0 | 8–12 |
| `JARVIS_KWS_THRESHOLD` | 0.25 | 0.20–0.30 |
| `JARVIS_KWS_TRAILING_BLANKS` | 1 | 1–2 |
| `JARVIS_KWS_MAX_ACTIVE_PATHS` | 10 | 8–12 |

## 实现

- `services/webui/src/joy_interaction_webui/jarvis_mode.py::JarvisConfig.from_env()` 读 env，覆盖字段默认值
- `services/webui/src/joy_interaction_webui/server.py::on_startup` 改为调 `JarvisConfig.from_env()`，不再手写 kwargs
- `services/scripts/run-windows.env` 加 KWS env 行（含注释提示调参方向）
- 模型目录 `bt-zai-ma` → `bt-en`（仅改名，模型与 keywords.txt 不变）

## 后果

- **正面**：调参不需要重启 webui + 改源码；改 env + start-joyai -Restart webui 就生效
- **正面**：`bt-en` 命名贴合实际（keywords 早已是英文 `B T @bt`）
- **负面**：env 拼错（`JARVIS_KWS_SCORE=abc`）会启动崩溃。需要 try/except + 警告日志回退到默认
- **测试**：需写 `test_jarvis_config_env.py` 覆盖 5 个矩阵场景