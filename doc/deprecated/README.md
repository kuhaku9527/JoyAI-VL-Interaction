# Deprecated 目录说明

本目录是历史文档快照，按下列规则处置：

| 文件                           | 状态                              | 处置                                       |
| ------------------------------ | --------------------------------- | ------------------------------------------ |
| 700809-raw-extract.md          | 早期 11 进程 + CosyVoice 全套设计 | 仅历史参考；当前现状见 `../specs/2026-07-13-current-state.md` |
| architecture.md / .zh-CN.md    | v1 设计                           | 同上                                       |
| getting_started.md / .zh-CN.md | v1 入门                           | 见仓库根 `../../README.md`                |
| rtsp_streaming.md / .zh-CN.md  | 未实现                            | `../../services/webui/src/joy_interaction_webui/rtsp_track.py` 占位，禁止据此实施 |
| troubleshooting.md / .zh-CN.md | 早期问题库                        | 问题查 `doc/subsystems/jarvis-mode.md` / `../specs/2026-07-13-current-state.md` |

**规则**：
1. 本目录不进新人入门路径。
2. 任何人翻旧实现时，必须对照 `../specs/2026-07-13-current-state.md` 验证是否仍生效。
3. 半年没引用的文件可批量删除（先 git grep + 30 天观察期）。

最近核对日期：2026-07-13