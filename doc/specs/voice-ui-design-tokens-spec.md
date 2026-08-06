# Spec：voice-ui.md 增补 Design Tokens（§9）
> 生命周期：草稿（2026-08-06 依 D-2026-08-06-001 派生）
> 上游决策：决策/调研-HF-speech-to-speech-姿态.md（UI 纪律 = 学 Design Tokens）

## §1 因果链（Why）
- **Why**：`doc/subsystems/voice-ui.md` 只记 HUD 徽章，无色板/字体/动效 token 体系（grep 无 Design Tokens 章节）；新增 WebUI 状态徽章时易拍脑袋（曾发生 GAP 8px→10px 事故）。
- **被否方案**：① 每加徽章临时定规则（漂移）；② 照搬 s2s `demo/DESIGN.md` 全量（含我们不需要的）。→ 选「增 §9 Design Tokens，搬 s2s 的色板/字体/8px 网格规则并本地化」。

## §2 范围与负面约束（What NOT）
- **做**：voice-ui.md 增 §9 「Design Tokens」——orb 颜色随状态、mono 仅机器文本、body 走 Inter、gap/8px 网格。
- **不做**：不改现有徽章逻辑；不引入 CSS 框架。
- **负面约束**：新增 token 必须入 §9，禁止散落叙述。

## §3 方案（What）
- 纯文档增补，零代码。

## §4 Harness
- 无。

## §5 验收
- 文档 review：§9 含色板/字体/网格三节；后续新增徽章 PR 须引用 §9。
