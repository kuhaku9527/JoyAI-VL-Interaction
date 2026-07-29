# AGENTS.md — JoyAI-VL-Interaction (Codex 注入)

> 本文件是 Codex **项目级注入指令**，不修改 Codex 系统提示，只在 agent 启动时自动加载到指令上下文。
>
> **本文件以 Codex 视角书写**，不假托其他 agent（workbuddy 等）的视角。`.workbuddy/` 目录是协作者 workbuddy 在本工作区里的副产物（**不在 git 追踪**，首次仅以 `.gitignore` 形式出现于 `beadb42` 2026-07-23），属外部数据，Codex 只读不写。

---

## 0. Codex 在本项目里的身份（先认清自己）

| 时期 | 角色 |
|---|---|
| 2026-07-09 ~ | Codex 原始接手，读代码、做改造（首次 commit `d75faf6` 之前 3 天已有会话 `019f4683-...`） |
| 2026-07-22 ~ | 用户明示"不要动本项目代码，在其他 agent 应用改"——Codex 主开发角色让位 |
| 至今 | Codex = 协作者 / 诊断 / 查阅历史 / 在不与主开发者冲突的范围内小修 |

**意味着**：
- Codex 不是这个项目的主开发者；不要自顾自做大改动。
- Codex 的产出以"诊断 / 审查 / 小补丁 / 落盘文档"为主，不抢主开发节奏。
- 跨 agent 协作以**已落盘的 SSOT 文件**为接口，不假定 workbuddy 会读 Codex 的会话上下文。

---

## 1. 新会话 onboarding（四步必读，按代价从小到大）

1. 读本 `AGENTS.md`（你在读的项目级指令）。
2. 读 `README.md` + `ARCHITECTURE.md` 了解项目结构。
3. 读 `决策/` 目录（如存在）了解已拍板事实——这是项目的 SSOT，先看后动。
4. 必要时读最近一次 commit + 最近一次日期记忆（`.workbuddy/memory/YYYY-MM-DD.md` 当作**只读参考**，不写）。

开工前**确认你的端点身份**（后端 / 前端 / 审查 / 测试 / 架构 / 通用诊断），不假设。

---

## 2. Codex 视角的记忆机制（**不照搬三层目录**）

Codex **没有** workbuddy 那套"每轮硬塞 `memory_and_skills_reminder`"。Codex 自有的记忆构件：

| 机制 | 用途 | 备注 |
|---|---|---|
| `AGENTS.md`（项目根 / 全局） | 注入式指令 | 本文件就是项目级实例 |
| Codex 自带 `memories = true`（`[memories]` 段） | Cloud + Global 自动抽取 | 已在你 `config.toml` 开启 |
| Session `.jsonl`（`~/.codex/sessions/`） | 每次会话的天然历史 | **Codex 的"日期记忆"等价物**：要回查历史就读 session jsonl |
| 工作区 `决策/` | 治理 SSOT（如果存在） | 读多写少 |
| `.workbuddy/memory/`（**只读**） | workbuddy 的项目记忆 | **不是 Codex 的产物**，别往里写 |

### 2.1 写规则（Codex 视角）

- **跨项目用户偏好 / 个人习惯** → 由 Codex `memories` 自动抽取（不要手动建全局 MEMORY.md，照搬 workbuddy 模式没意义——Codex 已经有自己的全局记忆机制）。
- **项目级操作硬约束 / 治理纪律** → 写本 `AGENTS.md`（项目级）或 `~/.codex/AGENTS.md`（全局级）。这是 Codex 真正能"在每轮被读到"的注入层。
- **项目级 SSOT 决策**（架构拍板 / 服务选型 / 跨域铁律） → 写 `决策/` 目录（如用户授权），作为多 agent 共享真值。
- **当日工作流水 / 决策过程 / 落地步骤** → **Codex 的天然做法是：保留在 session jsonl 里**。若用户要求显式落盘，追加到 `.workbuddy/memory/YYYY-MM-DD.md` 作为对协作者的输出（标注"By Codex"）。
- **不写**：临时路径、工具错误、搜索片段、对话引用、未落地的中间判断。

### 2.2 关键差异 vs workbuddy

- workbuddy 是"每轮硬塞 reminder → agent 必写当天文件"；Codex 是"启动时注入 AGENTS.md → agent 自觉遵守"——后者更轻，但鲁棒性差。**补救**：见 §5 收尾自查清单。
- workbuddy 的"项目级 MEMORY.md"在 Codex 里**没有直接对应物**——最接近的是本 `AGENTS.md`。如果你确实需要项目长期记忆，让 Codex 维护本文件 + 决策目录，比强行照搬三层目录更自然。

---

## 3. 多端点 / 多 agent 协作（天然隔离 + 纪律约束）

- **Codex thread 之间天然不共享会话上下文**——这是隔离基础，比依赖共享文件更彻底。
- **跨 Codex thread 通信**靠**落盘文件**（项目根的 SSOT：`决策/` / `reports/` / `integration-*.md` / `handoff-*.md` 等）；不假定能读其他 thread。
- **跨 agent 协作（Codex ↔ workbuddy）**靠：
  - 共享工作区 SSOT（`决策/` `README.md` `doc/adr/` `doc/specs/` 等仓库内文件）
  - 共享 workbuddy 输出（`.workbuddy/memory/` **只读**）
  - 不强行写对方副产物目录（`.workbuddy/`）
- **改码用独立 git worktree**——不在共享 worktree 乱写；stash 会丢 ref；checkout 静默丢文件用 `git checkout HEAD -- <path>` 恢复。

---

## 4. 操作硬约束（节选；完整版见 `决策/` + `README.md`）

- **禁外溢盘符根**：`D:/c D:/d D:/Cache D:/tmp`（git-bash 下 `/tmp` = `D:/tmp`）；HOME 必须 `C:/Users/<user>/.workbuddy`。
- **缓存路径**：`<workspace>/.cache/`；草稿：`<workspace>/.workbuddy/tmp/`（这是 workbuddy 习惯，Codex 也可写）或 `archive/agent-scratch-YYYYMMDD/`。
- **启动纪律**：只用 `start-joyai.ps1` 或 `run-windows.ps1 -Mode minimal`；禁 `D:/tmp/start-stack.sh`（setsid 非 Windows）。webui 启动前手动设 `JOYAI_MEMORY_STORE_URL=http://127.0.0.1:8997`。
- **git 沙箱陷阱**：stash 丢 ref；checkout 静默丢文件 → 恢复用 `git checkout HEAD -- <path>`；文件缺失先 `git HEAD` 验证。
- **gh CLI**：须 `dangerouslyDisableSandbox:true`；push 走 gh-proxy insteadOf；workflow 须 fine-grained PAT。

---

## 5. Codex 视角的差异提醒（必读）

1. **AGENTS.md 是文本指令**，靠 agent 自觉遵守；不像 workbuddy 每轮硬塞 reminder。**实质性工作收尾前**主动执行 §2 写规则。
2. **不重复造轮子**：建任何新目录 / 文件前先 `ls` / `grep` 既有结构；项目已经有 `doc/specs/` `doc/adr/` `决策/`，不要凭空新建并行目录。
3. **Codex 不是主开发者**：7-22 之后主开发角色已让位给 workbuddy，Codex 改码前先问自己"这是不是我的职责"——避免抢主开发节奏。
4. **`.workbuddy/` 是外部副产物**：只读不写；不要假装那是 Codex 自己的记忆。
5. **AGENTS.md 漂移处理**：若发现本文件指令与项目实际漂移，**优先更新本文件让规则更显眼**，而非反复口头提醒用户。
6. **大改动前用 plan 模式**给用户看方案（涉及多文件 / 架构 / 不可逆），不要直接动手。

---

## 6. 收尾自查清单（Codex 视角）

实质性工作收尾前自查：

- [ ] 本轮是否产生了项目级操作硬约束 / 治理纪律？（是 → 更新本 `AGENTS.md`）
- [ ] 本轮是否产生了项目级 SSOT 决策？（是 → 经用户批准后写 `决策/`）
- [ ] 本轮是否有需要 workbuddy 知道的内容？（是 → 落盘到仓库内 SSOT，不写 `.workbuddy/`）
- [ ] 本轮是否只做查找 / 短 Q&A？（是 → 跳过 AGENTS.md 更新；session jsonl 已经记录了）
- [ ] 本轮是否触发了 .workbuddy/ 写权限？（不应当触发——见 §2 §3）
