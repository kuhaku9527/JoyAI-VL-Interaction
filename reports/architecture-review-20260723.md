# 架构 Review 复检备忘录 · 2026-07-23（校正版）

> 复检：昨日（2026-07-22）review 后代码树变化（services 513→1670，webui 新增 ESLint 工具链），根目录新增 `ARCHITECTURE.md`（由 G1~G6 九份交付稿提炼）。本备忘录重跑 review，并**经实地核验修正**了首稿的两处误报。
> 方法：主理人直接审代码 + 新 `ARCHITECTURE.md` + 今日跨对话记忆，与冻结边界（D4 + ADR0001~0008）比对。未重启架构团队。

## 一句话结论

**大部分昨天标的项已不成立，真正需要补的只剩 1 项硬伤 + 少量打磨。** 首稿（未核验记忆）把两项误判为"仍成立且被权威文档放大"，实地核验后撤销：
- ❌ 撤销 **B3（memory 多后端矛盾）**：`psql_backend.py`/`obsidian_backend.py` 均为占位桩（`raise NotImplementedError`），**只有 sqlite 是活后端**，ADR0005"v0.1 仅 sqlite"完全准确。
- ❌ 撤销 **A1"jarvis-mode.md 缺失"**：`doc/subsystems/jarvis-mode.md`（60KB）一直存在，是 `server.py` 注释引用了错误路径 `doc/jarvis-mode.md`（PR #10 已改为 `subsystems/`）。

## 复检结果（逐项，已核验）

| 编号 | 首稿判断 | 实地核验后 | 最终状态 |
| --- | --- | --- | --- |
| **B4** | TTS 端口三分裂 vs ADR0004/安全设计 | 代码仍 `8985`(voice-clone)/`8992`(tts-adapter ws)/`8991`(本地 TTS 上游)；`ARCHITECTURE.md` §3/§5 仍只写单端口 8985，§10 防火墙 inbound 列表未含 TTS 端口 | 🔴 **唯一硬伤，仍成立** |
| **A1/A2** | Jarvis 文档缺失 + 无状态机 | `doc/subsystems/jarvis-mode.md`(60KB) 存在且完整；`ARCHITECTURE.md` §2/§5 仅提"KWS 常驻监听"，**未交叉引用该文档、也未在顶层描述 Jarvis 状态机** | 🟡 降级为"交叉引用 + 顶层摘要"缺口（设计本身不缺） |
| **B3** | memory 多后端 vs ADR0005 | psql/obsidian 是占位桩，仅 sqlite 活；ADR0005 准确 | ✅ **误报，撤销**（仅建议加一句"多后端 Protocol 已就位，psql/obsidian 为路线图桩"） |
| **C6** | ADR0008 未引用 | `doc/adr/0008-*` 存在；`ARCHITECTURE.md` §7 仅列 ADR0001~0007 | ⚪ 仍成立（轻微） |
| **C5** | WebUI 双角色 | 仍 aiohttp（前端宿主 + 本地桥接后端）；新增 ESLint 工具链（仅 lint，非 SPA 迁移） | ⚪ 仍成立（轻微） |

## 更新后的补充清单（按优先级）

1. **🔴 B4（唯一必须修）**：以新 `ARCHITECTURE.md` 为修正面——
   - §3 端口表：把"8985 TTS + voice_clone"拆成 `8985`(voice-clone API) / `8992`(TTS adapter ws) / `8991`(本地 TTS 模型上游)；
   - §10 防火墙 inbound 规则：补 TTS 相关端口（否则语音链路端口被漏放会直接故障）；
   - 同步改 G1~G6 的部署设计 §2/§3 与安全设计 §5.2（原文档同样只列 8985）。
2. **🟡 A1/A2（交叉引用 + 顶层摘要）**：`ARCHITECTURE.md` §2/§5 增加 Jarvis 常驻语音模式的一行摘要 + 指向 `doc/subsystems/jarvis-mode.md` 的链接；系统设计可补一节引用该子系统文档（避免重复造轮子）。
3. **⚪ C6**：`ARCHITECTURE.md` §7 + 系统设计补 ADR0008（P0 适配器修复）引用。
4. **⚪ C5/B3 澄清**：`ARCHITECTURE.md` 一句说明 WebUI 双角色 + memory 多后端 Protocol 已就位（psql/obsidian 为路线图桩，线上仅 sqlite）。
5. **⚪ 顺带**：前端 ESLint 工具链（`services/webui/package.json`/`eslint.config.js`）值得在部署/CI 章节记一笔（目前 CI 已含 eslint job）。

## 工作量估计

极小：主要改 1 份 `ARCHITECTURE.md`（端口表 + 防火墙 + Jarvis 链接 + ADR0008 + 两句澄清），部署/安全两份详文档同步修端口表。核心冻结边界（决策 token、单入口网关、端口基线）一律不动。

## 给主理人的判断

首轮 review（2026-07-22）的 4 项里，**真正经得起复检的只有 B4（TTS 端口）**；B3 与 A1 是"看代码 grep 到的结构"但未经深究导致的误报（多后端是桩、Jarvis 文档在 subsystems/）。这提醒：架构 review 不能只 grep 结构，要确认桩/活后端、文档真身路径。

新 `ARCHITECTURE.md` 整体质量好、应作为贡献者首要入口；唯一会误导人的是 TTS 端口那一行——优先级最高。

---
*本备忘录为 2026-07-23 校正版结论（首稿两处误报已撤销）。是否据此开补充 PR（修正 ARCHITECTURE.md 端口表/防火墙 + Jarvis 交叉引用 + ADR0008），请主理人裁决。*
