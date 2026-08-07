# VLM 架构与模型组成（权威单源真值）

> **范围**：生产环境 `:7060` VLM 推理服务的完整模型架构、各组件职责、精度、路径。
> **为什么需要本文档**：2026-08-04 发生多次架构认知漂移（agent 把纯 LLM 当成有视觉能力的 VLM、混淆 IQ4_NL 与视觉精度），导致诊断和优化方向偏差。本文档钉死架构真相，防止再漂移。
> **修改走 §0 治理协议（AI 提议 → 用户同意 → 落盘）。**
> **日期**：2026-08-04（基于当日完整对话回溯 + 代码/配置/文件系统三方核对）

---

## 一、生产架构总览：分离式双模型（llama.cpp 组合）

### 核心事实（一句话）

**生产 VLM 不是单一模型，而是两个独立文件由 llama.cpp 在运行时组合：一个纯文本 LLM（IQ4_NL 4-bit GGUF）+ 一个独立视觉投影器（F16 GGUF）。**

```
┌─────────────────────────────────────────────────────────┐
│                  llama-server.exe (:7060)                │
│                                                         │
│  ┌──────────────────────┐   ┌────────────────────┐     │
│  │ LLM 主模型 (IQ4_NL)  │ + │ 视觉投影器 (mmproj) │     │
│  │                      │   │                    │     │
│  │ 格式: GGUF           │   │ 格式: GGUF          │     │
│  │ 量化: IQ4_NL (4-bit) │   │ 精度: F16 (半精度)  │     │
│  │ 能力: 纯文本生成      │   │ 能力: 图像→embedding│     │
│  │ 大小: ~4.46 GiB      │   │ 大小: ~1.08 GiB     │     │
│  └──────────────────────┘   └────────────────────┘     │
│            ↓                        ↓                   │
│         文本 token              图像特征向量             │
│            └──────────┬───────────┘                     │
│                       ↓                                 │
│              Qwen2.5-VL 风格的多模态推理                  │
│              (OpenAI 兼容 /v1/chat/completions)          │
└─────────────────────────────────────────────────────────┘
```

### 组件明细表

| 字段 | LLM 主模型 | 视觉投影器 (mmproj) |
|---|---|---|
| **文件名** | `joyai-vl-interaction-preview-iq4_nl-imat.gguf` | `mmproj-joyai-vl-interaction-preview-f16.gguf` |
| **路径** | `D:\AI\models\main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\` | `D:\AI\models\main\mmproj\` |
| **大小** | 4,793,619,520 B (~4.46 GiB) | 1,159,029,728 B (~1.08 GiB) |
| **合计** | **~5.54 GiB**（两者加起来） | |
| **格式** | GGUF（llama.cpp 原生） | GGUF |
| **量化/精度** | **IQ4_NL**（4-bit 非线性量化，~4.5 bpw） | **F16**（FP16 半精度，无量化） |
| **能力** | 纯文本 LLM：接收 text + image embeddings → 生成文本 | 视觉编码器/投影器：图像像素 → 投影到 LLM embedding 空间 |
| **参数量** | ~8B（n_embd=4096） | 取决于 vision encoder 架构（SigLIP 或类似） |
| **是否独立运行** | 可以（纯文本模式，去掉 --mmproj） | 不可以（必须配合 LLM 使用） |
| **启动参数** | `-m <路径>` | `--mmproj <路径>` |

### 启动命令（来自 `run-windows.ps1:366-376`，精确抄录）

```powershell
# Start-LlamaMain 函数（run-windows.ps1:359-388）
$args = @(
    "-m", $MainGguf,          # LLM 主模型 IQ4_NL GGUF
    "--mmproj", $MainMmproj,   # ← 关键！视觉投影器 F16 GGUF
    "--host", "127.0.0.1",
    "--port", "7060",
    "-c", "16384",             # 上下文窗口（见 D-027 / D-L1-006）
    "-ngl", "999",             # 全层 GPU offload
    "--parallel", "1",         # 并行槽位
    "-fit", "off",             # flash attention off
    "--jinja"                  # Jinja 模板
)
```

**关键点**：`--mmproj` 参数是 llama.cpp 组合双模型的唯一纽带。没有它，LLM 就是纯文本模式，无法处理图像。

---

## 二、架构对比：生产 vs NVFP4 测试

| 维度 | 生产 (:7060) | NVFP4 测试 (:7061) |
|---|---|---|
| **架构类型** | 分离式双模型（LLM + mmproj） | 一体化单模型（Qwen3VLForConditionalGeneration） |
| **文件数** | 2 个 GGUF | 1 个 safetensors (+ config.json) |
| **LLM 部分** | IQ4_NL 4-bit (~4.46 GiB) | NVFP4 4-bit + FP8 scales (~7.03 GiB 含视觉塔) |
| **视觉部分** | 独立 mmproj F16 (~1.08 GiB) | BF16 视觉塔烘焙进同一文件（无需 mmproj） |
| **运行时** | llama.cpp b10155 (Win 原生) | vLLM 0.26.0 (WSL2) |
| **总显存占用** | ~10 GB（生产实测） | ~13.7 GB（util 0.7, ctx 16384） |
| **视觉精度** | **F16（无损失）** | BF16（无损失） |
| **LLM 文本精度** | IQ4_NL（有损量化） | NVFP4（有损量化，质量介于 Q4_K_M~Q5_K_M） |
| **生产状态** | ✅ 生产（D-020/D-021 锁定） | ❌ 仅测试（用户明确不替换） |

### 为什么 NVFP4 不需要 mmproj

NVFP4 的 `recipe.yaml` 配置了 `ignore: [model.visual.*, lm_head]`——即视觉塔（`model.visual.*`）和输出头被排除在 4-bit 量化之外，保持 BF16 原始精度，**直接烘焙在同一个 safetensors 文件里**。所以 NVFP4 是"一体化"的，不需要外挂 mmproj。

而生产的 GGUF 路径受限于 GGUF 格式设计：社区量化时通常把 LLM 和视觉分开打包（LLM 用各种量化级别可选，mmproj 保持 F16 固定），所以是两个文件。

---

## 三、已发生的漂移记录（防止复发）

以下漂移发生在 2026-08-04 的对话过程中，**全部已纠正**。记录在此是为了防止以后再犯。

### 漂移 #1：把"主模型"当成有视觉能力的 VLM

- **错误表述**："主模型 IQ4_NL 的识别率低"、"主模型视觉能力"
- **真相**：IQ4_NL 是**纯文本 LLM**，没有任何视觉能力。视觉能力 100% 来自独立的 mmproj F16 文件。
- **影响**：导致诊断时把"IQ4_NL 量化天花板"列为视觉识别原因之一（实际只影响文本生成质量，不影响视觉特征提取）。
- **纠正时间**：2026-08-04 凌晨用户明确纠正（`2026-08-04.md:43`）。
- **防复发规则**：提到"主模型"时必须说明是"LLM 主模型（纯文本）"；提到"视觉能力"时必须指向 mmproj。

### 漂移 #2：混淆 IQ4_NL 量化影响范围

- **错误表述**："IQ4_NL 4-bit 量化导致视觉细节丢失"、"模型本身量化天花板限制识别率"
- **真相**：IQ4_NL 只量化 LLM 的权重矩阵（attention/ffn 层），**不涉及任何视觉处理**。视觉特征提取由 mmproj F16 完成，精度无损。IQ4_NL 影响的是：模型"看到"视觉特征后**生成什么文字描述**（文本质量/流畅度/准确性），而不是"看到什么"（视觉特征质量）。
- **影响**：把优化方向错误地引向"换更高精度的 LLM 量化"，而真正的瓶颈在输入链路（max_pixels 太小、JPEG 有损）。
- **纠正时间**：2026-08-04 诊断修正（`2026-08-04.md:45`）。
- **防复发规则**：讨论"识别率低/幻觉"时，区分两层：(a) 视觉层（mmproj F16 + 输入分辨率/编码质量）= "模型看到什么"；(b) 文本生成层（IQ4_NL LLM + prompt）= "模型怎么描述看到的"。

### 漂移 #3：NVFP4 文档表述不精确

- **错误表述**："不替代生产 IQ4_NL"、"IQ4_NL 锁定"
- **真相**：生产不是"IQ4_NL"，而是"IQ4_NL + mmproj F16 组合"。应该说"不替代生产 IQ4_NL+mmproj F16 双模型组合"。
- **影响**：读者可能误以为 NVFP4 和生产是同类可直接对比的单模型，忽略 mmproj 的存在。
- **纠正时间**：2026-08-04 19:55 用户指出截图证据后。
- **防复发规则**：提及生产模型时必须用完整表述"IQ4_NL GGUF + mmproj F16 GGUF"或"分离式双模型"。

### 漂移 #4：诊断 #4 根因分析未分层

- **错误表述**：根因列表中"#4 模型本身 IQ4_NL 量化天花板（硬约束，不可消除）"
- **真相**：未区分这影响的是文本层而非视觉层。且"不可消除"过于绝对——换量化级别（如 Q5_K_M/Q6_K）或换模型（如 NVFP4 一体化）都可以改变，只是当前决策锁定不动。
- **影响**：给用户造成"识别率低无法根本解决"的错误印象。
- **纠正时间**：本次文档撰写时系统性纠正。
- **防复发规则**：根因分析必须标注影响层级（视觉层 / 文本层 / 链路层 / 决策约束层）。

### 漂移 #5：决策源头 D-020/D-021 缺失 mmproj 描述（系统性根因）
- **问题**：`决策/服务-VLM.md` 的 D-020（":7060 = llama-server.exe"）与 D-021（"LLM = IQ4_NL GGUF"）**通篇未提及 mmproj / 视觉投影器**。D-021 只锁了 LLM GGUF 路径，没锁 mmproj 路径；标题甚至写作"主 VLM 推理服务（llama-server.exe + IQ4_NL 8B 量化）"，把 LLM 直接等同 VLM。
- **为何是系统性根因**：agent 读 D-021 时，自然把"IQ4_NL GGUF"当成"那个 VLM"，进而产生漂移 #1/#2（以为 IQ4_NL 自带视觉、以为量化影响视觉）。**源头文档没把"视觉能力来自独立的 mmproj F16"写成显式事实**，是本次一切认知漂移的温床。
- **代码层面健康**：`run-windows.ps1:66-67` 定义 `$MainMmproj`，`:362-363` 同时检查 GGUF+mmproj 存在性，`:367-368` 启动参数 `-m $MainGguf --mmproj $MainMmproj`。**代码正确组合双模型，漂移不在代码，在文档未如实反映代码。**
- **纠正动作**：本文档第四节已钉死真相；D-021 应补充 mmproj 路径锁定（治理待办，见 §八）。

### 漂移 #6：D-012 声称"vLLM 是默认生产路径"与 D-020 矛盾
- **错误表述**：`决策/模型与权重.md` D-012 写"vLLM 是主 VLM + 总结模型的**默认生产路径**（见 `服务-VLM.md` D-020）；llama.cpp b10155 是经替换验证的稳定引擎候选，非默认生产必需。"
- **矛盾**：D-020 实际锁定的是"`llama-server.exe`（llama.cpp）"，不是 vLLM。D-012 把"vLLM"说成 D-020 的结论，与 D-020 原文打架。
- **现实**：生产 VLM(:7060) 跑的是 llama.cpp b10155 + IQ4_NL GGUF + mmproj F16（NVFP4/vLLM 仅 :7061 测试，用户明确不替换）。D-012 这句会反复误导人以为生产走 vLLM。
- **纠正动作**：需按 §0 治理流程修正 D-012（见 §八）。

### 漂移 #7：NVFP4 运维文档省略"生产 = IQ4_NL + mmproj 组合"
- **错误表述**：两份 NVFP4 运维手册（模型目录版 / agent 草稿版）§6/§12 写"生产 IQ4_NL 主模型""生产链路仍锁 :7060=llama-server.exe + IQ4_NL GGUF"，未提 mmproj。
- **影响**：读者可能误以为 NVFP4（一体化单模型）和生产是同类单模型直接对比，忽略生产视觉来自独立 mmproj。
- **纠正动作**：已在本文档钉死生产架构；NVFP4 文档相应处补"（即 IQ4_NL GGUF + mmproj F16 双模型组合）"一句（agent 已修订两份手册）。

### VLM 端到端延迟实测结论（#43 调研，2026-08-07）

- **来源**：issue #43（视频采集端到端延迟高，定位根因并评估替代方案，**已 CLOSED**）+ DRIFT-6 实测 + `logs/vlm-runtime-props.json`（2026-08-04 采，IQ4_NL GGUF，:7060 health ok）。
- **结论 1 — VLM 推理段非瓶颈**：DRIFT-6 实测首条 2078ms、第 3 条起 <320ms 稳态；首条拖尾来自 memory-store 5s timeout，非 VLM 本身。稳态推理段 <320ms 属健康水位。
- **结论 2 — 瓶颈在输入链路（采集/编码）**：`max_pixels` 太小（PR #79 前 512px 等效）、主路径 JPEG 有损（PR #81→92）、WebRTC VP8/VP9 有损压缩、采集分辨率协商降级。OBS 已落地作为采集替代方案（#43 评估项）。
- **结论 3 — 指标边界（防混淆）**：本结论的"稳态推理段 <320ms"≠"VLM 启动耗时/首字节"（见 `服务-VLM.md:140` TODO，专指冷启动）；二者必须区分，不得互相替代。
- **#43 编号边界**：#43 仅覆盖"视频采集端到端延迟"调研与 OBS 替代评估；端口 8997 env 修复（PR #83/#84）、VLM watchdog 均非 #43 范畴，决策/ 各处"待 #43"标注为误标，已按 §0.1 于 2026-08-07 修正。
- modified: 2026-08-07｜by AI｜approved: 用户

---

## 四、"图片识别率低"Bug 的正确因果链（纠正后）

基于上述架构认知，重新梳理因果链：

### 第 1 层：视觉层（"模型看到什么"）—— 由 mmproj F16 + 输入链路决定

| 环节 | 问题 | 影响 | 状态 |
|---|---|---|---|
| 服务端 max_pixels | PR #79 前=262144(512px等效)，视觉token极少 | 🔴 **主因：模型看不清** | ✅ 已修(PR #79→1048576) |
| 主路径 JPEG 质量 | PIL 默认 q75 有损重编码 | 🟠 细节二次损失 | ✅ 已修(PR #81→92) |
| Background resize | long_edge=768px（后台代理路径） | 🟡 后台代理质量差 | ✅ 已修(PR #79→env 1536) |
| 采集分辨率 | getUserMedia ideal 720p，协商可能降级 | 🟡 上限受限 | 🟡 部分缓解(PR #79→1080p) |
| WebRTC 传输 | VP8/VP9 有损压缩 | 🟢 固有损失，可接受 | — |
| **mmproj F16 精度** | **无问题（F16 无损）** | ✅ 非瓶颈 | — |

### 第 2 层：文本生成层（"模型怎么描述看到的"）—— 由 IQ4_NL LLM + prompt 决定

| 环节 | 问题 | 影响 | 状态 |
|---|---|---|---|
| IQ4_NL 4-bit 量化 | 文本生成质量有上限 | 🟡 可能导致描述不够精准/编造措辞 | ⚪ 决策锁定(D-021)，不改 |
| System prompt | 是否约束"看清就答、看不清就说不知道"？ | 🟡 若无此约束，模型倾向用常识补全→幻觉源 | 🔵 待查 |
| 多帧聚合 | 是否送了模糊/运动帧？多帧 token 稀释？ | 🟡 可能降低单帧有效 token | 🔵 待查 |

### 第 3 层：决策约束层（"我们能改什么"）

| 约束 | 内容 | 来源 |
|---|---|---|
| D-020 | :7060 = llama-server.exe（锁运行时） | 决策/服务-VLM.md |
| D-021 | LLM 模型路径 = IQ4_NL GGUF（锁模型） | 决策/服务-VLM.md |
| 用户决策 | NVFP4 不替换生产，仅测试 | 2026-08-04 19:27 |

---

## 五、文件系统验证命令（任何人可跑）

```powershell
# 验证生产模型文件存在
Test-Path "D:\AI\models\main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\joyai-vl-interaction-preview-iq4_nl-imat.gguf"
Test-Path "D:\AI\models\main\mmproj\mmproj-joyai-vl-interaction-preview-f16.gguf"

# 验证文件大小（应分别约 4.46 GiB 和 1.08 GiB）
(Get-Item "D:\AI\models\main\JoyAI-VL-Interaction-Preview-IQ4_NL-GGUF\joyai-vl-interaction-preview-iq4_nl-imat.gguf").Length / 1GB
(Get-Item "D:\AI\models\main\mmproj\mmproj-joyai-vl-interaction-preview-f16.gguf").Length / 1GB

# 验证启动脚本引用（应命中两处路径）
Select-String -Path "services\scripts\run-windows.ps1" -Pattern "MainGguf|MainMmproj"

# 验证启动参数含 --mmproj
Select-String -Path "services\scripts\run-windows.ps1" -Pattern "--mmproj"

# 运行中验证（服务启动后）
curl -s http://127.0.0.1:7060/v1/models
```

---

## 六、关联决策索引

| 决策条目 | 内容 | 本文档关系 |
|---|---|---|
| D-020（服务-VLM.md） | :7060 = llama-server.exe | 锁定运行时，不含模型架构细节 |
| D-021（服务-VLM.md） | LLM = IQ4_NL GGUF 具体路径 | 锁定 LLM 路径，但**未提及 mmproj**（遗漏，待补充） |
| D-022（服务-VLM.md） | n_ctx = 16384 | 上下文窗口 |
| D-L1-006（启动链路.md） | MAIN_CONTEXT = 16384 | 同上 env 写法 |
| D-L1-001（启动链路.md） | 最小栈启动 checklist | 含 GGUF 检查但**未显式检查 mmproj**（待补充） |
| Issue #80 | [Bug] 主 VLM 识别率低 / 幻觉 | 本 bug 的跟踪 issue |

### 待补充（建议后续补齐）

1. **D-021 应补充 mmproj 路径锁定**：当前 D-021 只锁了 LLM GGUF 路径，没锁 mmproj 路径。建议新增 D-021b 或修改 D-021 加入 mmproj 路径。
2. **D-L1-001 checklist 文档描述遗漏 mmproj 检查（代码已有）**：代码 `run-windows.ps1:363` 已有 `if (-not (Test-Path $MainMmproj)) { throw "main mmproj missing" }`，启动参数 `--mmproj` 在 L368。**决策/启动链路.md D-L1-001 第 4 项 checklist 文字只写了"GGUF：Test-Path ...iq4_nl-imat.gguf"，未把 mmproj 检查写入文档描述**——属文档描述不全，非代码缺失。建议补文档 checklist 文字（不改代码）。
3. **`决策/服务-VLM.md` 待补充段（L139）**：原文写"D-XXX：VLM 启动参数（-ngl / -c / --mmproj 等）— 待确认"，现本文档已确认 `--mmproj` 参数，可回填。
4. **`决策/模型与权重.md` D-012 矛盾待治理**：D-012 称"vLLM 是默认生产路径（见 D-020）"，与 D-020（锁定 llama-server.exe = llama.cpp）直接打架；且用户已明确 NVFP4 不替换生产。详见 §八，需按 §0 治理流程由用户拍板修正。

---

## 七、变更记录

| 日期 | 变更内容 | 操作者 |
|---|---|---|
| 2026-08-04 | 初版：基于当日完整对话回溯建立，纠正 4 项已发生漂移，钉死分离式双模型架构真相 | 审查组（本对话端） |
| 2026-08-04 | 补充：穷尽核查决策文档层，新增漂移 #5/#6/#7（D-021 缺 mmproj 描述 / D-012 vLLM 默认路径矛盾 / NVFP4 文档省略）；修正 #2 为"代码已有 mmproj 检查、文档 checklist 文字遗漏"；新增 §八治理待办 | 审查组（本对话端） |

---

## 八、文档层根因与治理待办（需用户按 §0 流程拍板）

> 本节所列改动涉及决策条目（D-021 / D-012）/ 索引（README §2），按 `决策/README.md` §0.1 治理协议须 **AI 提议 → 用户明确同意 → 才落盘**。此处先固化"待办 + 建议措辞"，待用户批准后由审查组落盘。

### 待办 1：D-021 补充 mmproj 路径锁定
- **现状**：D-021 只锁 `joyai-vl-interaction-preview-iq4_nl-imat.gguf`，未锁 `mmproj-joyai-vl-interaction-preview-f16.gguf`。
- **建议措辞（追加到 D-021 事实字段）**：`；视觉投影器 = D:\AI\models\main\mmproj\mmproj-joyai-vl-interaction-preview-f16.gguf（F16 GGUF，必须配合 LLM 使用，缺之则 VLM 无视觉能力）；启动参数 --mmproj 由 run-windows.ps1:368 注入。`

### 待办 2：D-012 澄清生产引擎
- **现状**：D-012 称"vLLM 是默认生产路径（见 D-020）"，与 D-020（llama-server.exe）矛盾。
- **建议措辞（修订 D-012 事实字段）**：删除"vLLM 是主 VLM + 总结模型的默认生产路径（见 服务-VLM.md D-020）"一句；改为：`生产 VLM(:7060) 推理引擎 = llama.cpp b10155（Win 原生，CUDA 13.3）；vLLM 仅用于 NVFP4 并行测试后端（:7061，非生产、用户明确不替换）。`

### 待办 3：README §2 索引补录本纠偏文档
- **现状**：`决策/README.md` §2 文件索引表未列 `VLM架构与模型组成.md`，导致本钉死文档在索引中不可见。
- **建议**：在 §2 表末追加一行（审查组已在本轮补录）：`| — | [VLM架构与模型组成.md](VLM架构与模型组成.md) | 分离式双模型权威真值 + 漂移纠正（2026-08-04） | ✅ 新增 |`。

### 待办 4（已闭环，记录）：NVFP4 运维文档补一句
- 两份 NVFP4 手册 §6/§12 "生产 IQ4_NL" 处已补"（即 IQ4_NL GGUF + mmproj F16 双模型组合）"，agent 草稿版与模型目录版同步修订。此项无需治理流程，已闭环。
