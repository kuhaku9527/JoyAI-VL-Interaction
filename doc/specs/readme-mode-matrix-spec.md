# Spec：README Quick Start 增补 -Mode 对照表
> 生命周期：草稿（2026-08-06 依 D-2026-08-06-001 派生）
> 上游决策：决策/调研-HF-speech-to-speech-姿态.md（UI/部署 学 → 含启动预设对齐）

## §1 因果链（Why）
- **Why**：`start-joyai.ps1` 有 4 模式 `default/minimal/voice/gaming`(L24 ValidateSet)，但 README Quick Start 仅写 `run.sh minimal`(L108)，新用户不知有 gaming/voice 预设。
- **被否方案**：改脚本（过度）。→ 选「README 顶部加四模式对照表 + 启动命令」。

## §2 范围与负面约束（What NOT）
- **做**：README.md + README.zh-CN.md Quick Start 顶部加 `default / minimal / voice / gaming` 对照表（含一句场景说明 + 启动命令）。
- **不做**：不改 `start-joyai.ps1` 的 -Mode 枚举（以脚本为准，文档对齐脚本）；不引入新模式。
- **负面约束**：README 模式列表必须与 `start-joyai.ps1` ValidateSet 严格一致（防再漂移）。

## §3 方案（What）
- 纯文档增补。

## §4 Harness
- 无。

## §5 验收
- 文档 review：README 对照表四模式与 `start-joyai.ps1` ValidateSet 一字不差。
