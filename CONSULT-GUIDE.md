---
title: 多模型会诊规范（CONSULT-GUIDE）
version: v1.8.0
status: active
owner: shper
updated: 2026-06-14
scope: 多模型协作讨论的单一来源——宿主无关的多形态协作引擎（3 协作形态 panel / debate / refine + 单声旁路 direct）/ 角色集 / 物理架构（宿主底座批 + 跨底座外部批） / 角色卡 schema / 各形态收口契约 / 触发纪律 / 落盘边界（产出不落文档 + 强制过程留痕到 .consult-cache） / 外部模型接入（含按宿主取声音池、用户指定 provider） / 降级。被 /to-consult 引用，/to-grill 也会在命中真权衡/高风险时内部点燃；底层 transport 见 ai_client/README.md。
related:
  - skills/to-consult/SKILL.md
  - skills/to-grill/SKILL.md
  - ai_client/README.md
  - ai_client/consult_log.py
  - scripts/panel.js
---

# 多模型会诊规范

> 给讨论引入**第二个声音**：多个角色（含跨厂商模型）就一个议题按某种**协作拓扑**各自出观点，**当前宿主的主模型**收口。
> 目的不是凑人头，而是**盲区互补**——一个底座想不到的，另一个想到；一个立场放过的，对立立场逼出来。
> **宿主无关**：本规范不假设宿主是哪个 CLI。谁打开项目（Claude Code / Codex / Cursor）谁就是主裁；角色批的派发方式按宿主能力探测后选择。
> **多形态协作引擎**：同一套底座（宿主 + 外部）能按 **3 种协作形态**协作——panel / debate / refine（refine 一形态两方向：双向互评合并 / 单向质检修订）；外加一条**单声旁路 direct**（非协作形态，§2.4）（§2）。
> 单一来源：`/to-consult`（手动入口）、`/to-grill`（审问中遇真权衡时内部点燃）都调本规范，skill 只写"何时点燃 + 选哪个形态 + 如何喂上下文 + 如何消费"，不复述机制。

---

## 0. 宿主无关的三要素

| 要素 | 定义 | 落点 |
|---|---|---|
| **主裁（收口者）** | 当前宿主的主模型（Claude Code→Opus / Codex→codex 主模型 / Cursor→cursor 主模型）。运行时主会话自知身份，无需配置。承担各形态的收口（综合 / 裁决 / 合并 / 修订）。 | §5 |
| **宿主底座声音** | 当前宿主底座派出的角色（panel 形态是 3 个强制对立 lens 的 persona；其它形态承担拓扑里的某个席位）。派发方式按宿主探测。 | §1 §3 |
| **外部底座声音** | **非宿主底座**的跨厂商声音。按当前宿主取 `external_voices[host]` 声音池（天然排除同底座），承担补盲 / 正反方 / 双 agent / 生成质检等席位。 | §3 §8 |

**关键不变量**：收口者 = 宿主主裁；其余角色尽量分布在**不同底座**上（宿主底座 + 2 个外部底座，共 3 类）。这样"盲区互补 / 不同源对抗"在任何宿主下都成立，而非只在 Claude 宿主成立。

---

## 1. 角色集与底座分配

角色靠**强制对立的评判 lens / 立场**拉开区分度（同底座派多角色有先天同质风险，故不靠身份标签）；跨底座再叠加真正的厂商差异。各形态用到的角色不同，但都从下面三类底座取：

| 底座类 | 来源 | 在各形态承担 |
|---|---|---|
| 宿主底座 | 当前宿主（Workflow / 主会话自扮演） | panel 的 3 persona；debate 裁判（=主裁）；refine 合并/修订（=主裁）；外部不足时补位辩方/agent |
| 外部底座 A | `external_voices[host][0]` | panel 外部视角；debate 正方；refine ext0（two-way=Agent A / one-way=生成） |
| 外部底座 B | `external_voices[host][1]` | panel 外部视角；debate 反方；refine ext1（two-way=Agent B / one-way=质检） |

panel 形态的 3 个宿主 persona 强制 lens（其它形态不用 persona lens，用拓扑角色立场）：

| persona | 强制 lens / 立场约束 |
|---|---|
| 架构红队 | **只**挑技术可行性 / 与项目已记录架构决策（如有）冲突 / 实现风险；不评价产品价值 |
| 价值质询 | **只**挑"是否解决真问题 / ROI / 是否过度设计 / 更省的替代方案"；不碰技术实现细节 |
| 唱反调者 | **强制**只列"这方案会失败 / 被推翻的 ≥3 个理由"，**禁止**说优点 |

强制约束写进各角色 prompt（见 §4），不可松绑成"全面评价"——否则退化为同质独白。

---

## 2. 形态（多形态协作引擎）

**3 种协作形态**共享底座与主裁，区别在**协作拓扑**和**收口契约**（§5）。全部**产出不落 docs/**（过程素材强制留痕到 `.cache`，§7.2），产出是素材交下游（§7）。此外有一条**单声旁路 direct**（§2.4）——不进协作拓扑、无 §5 收口，用户明确"只用 X"时借单个底座看一眼。

### 形态总览（协作形态）

| 形态 | 拓扑 | 角色→底座 | 收口契约 | 门控 | 适用 |
|---|---|---|---|---|---|
| **panel**（默认） | 并行独立出卡 | 宿主 3 persona + 外部 N | 综合：共识/分歧/盲区/结论 | — | 盲区互补、需求讨论 |
| **debate** | 正反立论→反驳→裁决 | 正方=外部A，反方=外部B，裁判=主裁 | 裁决：胜负/逐对比较/分歧/建议/风险 | 置信度≥85 收敛，<60 标争议 | 二元对立的架构选型 / 高风险决策 |
| **refine**（精炼，两方向） | `two-way`：独立生成→交叉互评→合并；`one-way`：生成→质检→修订 | ext0/ext1=外部 A/B，收口=主裁 | two-way→合并（终稿+来源标注+差异）；one-way→修订（H/M/L+质检报告） | 互评/质检整体评分≥85 跳收口 | two-way 方案/草稿多视角打磨；one-way 报告/文档质检润色（含"仅质检"旁路） |

### 形态选择（仿 impl-review 的 mode 分流）

- 入参 `mode=panel|debate|refine`（协作形态），默认 `panel`；refine 再分 `--direction two-way|one-way`（默认 two-way）。
- **旁路分流**：`mode=direct` 或措辞「只用 X / 单独让 X / 让 X 分析」→ **direct 单声旁路**（§2.4 / §6），跳过多角色与收口。
- 无显式 mode 时按措辞自动判定：「辩论 / 选型 / 二选一 / 该用 A 还是 B」→ debate；「互评 / 多视角打磨 / 双人对照」→ refine `two-way`；「质检 / 审一下这篇 / 润色 / 把关」→ refine `one-way`；其余 → panel。
- **显式 mode 优先**。判不准就按默认 panel，并一句话告诉用户"按 panel 形态走，要辩论/精炼请加 mode=debate|refine"。
- **不同源保障**：debate/refine 的对抗角色应分布在不同底座（external_voices[host] 已排除同底座）。底座不足（外部只剩 1 个或全挂）按 §9 降级并标注。

### 2.1 panel（默认，并行独立）

宿主 3 persona（§1 强制 lens）+ external_voices[host] 外部声，**互不可见**地各出一张角色卡（§4），主裁按 §5 综合。这是默认形态，盲区互补最直接。编排见 §3 / §10。

### 2.2 debate（正反辩论 + 裁判裁决）

**议题须二元对立**（"该用 A 还是 B / 要不要做 X"）；非对立议题（"介绍一下 React"）提示换形态。主会话**串行**编排：

1. 正方立论（外部A）：坚持正方，3–5 核心论点 + 论据 + 反驳预判。
2. 反方立论（外部B）：坚持反方，同结构。
3. 反驳（串行）：正方逐条驳反方 → 反方逐条驳正方（后驳方已读先驳方）。
4. 裁判初裁（主裁，含**置信度** 0–100%）：≥85 直接进裁决；<85 且 ≥60 触发第二轮反驳后重评；<60 标"存在重大争议"输出完整记录。
5. 裁判裁决（主裁，§5 debate 契约）：必须明确裁决不回避；势均力敌选风险更低一方。

收敛靠置信度门控，不靠固定轮数。降级见 §9。

### 2.3 refine（精炼：一形态两方向）

"独立生成→互评→收口"的串行精炼链，**互评方向作参数**（`--direction`），共享 2 外部底座 + 主裁收口 + H/M/L 评分门控。两方向同源、按议题措辞或显式入参选：

#### 2.3.1 `two-way`（双向互评 → 合并，默认；原 reflection）

双声部各自独立生成、互相批判后由主裁合并。主会话编排：

1. 独立生成（**可并行**）：Agent A（ext0）、Agent B（ext1）对同一任务各出初版。
2. 交叉互评（串行）：A 评 B → B 评 A，逐条 **H/M/L + 评分(0–100)**，整体附质量分。
   - 门控：双方互评均无 H 且综合 ≥85 → 视为无实质问题，跳过独立修订直接合并。
3. 主裁合并（§5 refine/two-way 契约）：含两初版 + 互评，输出终稿、**标注每段来源（A/B/综合）**、对 M/L 争议裁定 + 关键差异摘要。

适用方案 / PRD 草稿 / 文案的多视角打磨。

#### 2.3.2 `one-way`（单向质检 → 修订；原 review-chain）

串行质检链 + 评分门控。主会话编排：

1. 生成（ext0）：按输入生成初版。**"仅质检"旁路**（`--skip-gen`）：用户已有内容时跳过生成，直接进质检。
2. 质检（ext1，须≠生成底座）：逐条 **H/M/L**（H 事实错/逻辑矛盾/严重遗漏；M 表达/结构/完整性；L 无问题）+ **整体评分(0–100)**。
   - 门控：整体评分 ≥85 → 跳过修订，直接输出初版为终版；<85 → 进入修订。
3. 修订（主裁，§5 refine/one-way 契约）：H 全改、M 尽量改、L 保持，输出修订版 + 折叠质检报告 + 逐条处理说明。

适用报告 / 文档 / 方案草稿的生成-质检-润色。两方向降级均见 §9。

### 2.4 旁路 · direct（单声部直问，非协作形态）

> **不是协作形态，是引擎的单声旁路（逃生舱）。** 缺多角色、缺 §5 主裁收口——**原样转述即终态**，不在 §5 收口契约辖内。它放弃了"摆矛盾 / 盲区互补"（引擎的立身之本），只借单个底座的眼睛看一眼；要交叉验证就升级回 panel/debate/refine。

用户**指定单个模型**（措辞「只用 X / 单独让 X / 让 X 分析这个问题/文档」，或 `mode=direct`）时，**跳过**多角色与收口，主会话直接调 `ai_client`：

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider <X> [--file <文档路径> …] "<§4 角色 prompt 或用户原始问题>"
```

1. 取问题/文档；分析文档用 `--file`（§8，cli.py 读出嵌入，所有 transport 通用，qwen 这类纯 API 也适用）。
2. relay 模型答案 + 一句"这是 X 单方观点、未经多模型交叉验证；要摆矛盾压测走 panel/debate"。
3. 失败/超时按 §9 如实告知——direct 是用户点名单模型，**不降级**到别的声音（点名即排他）。
4. **产出不落 docs/**（同 §7.1 `/to-consult` 行）；过程留痕照常（§7.2，direct 无收口故只含该次请求+生响应）。

---

## 3. 物理架构（两批拼成一次协作）

任一形态物理上都由**宿主底座批 + 非宿主底座外部批**组成，主会话编排并收口。

| 批次 | 派发者 | 机制 |
|---|---|---|
| **宿主底座批** | 主会话 | **按宿主探测派发**：Claude Code 有 `Workflow` → panel 形态走 `orchestration/panel.js` 确定性 `parallel()` fan-out（每角色一个 agent，schema 强制角色卡）；Codex / Cursor **无 `Workflow`** → 主会话**串行自扮演**（lens / 立场照旧强制，质量等价只是不并行）。 |
| **非宿主底座外部批** | 主会话 | **panel 形态**：`Bash` 调 `uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider <id>` 取各外部视角（池里每个 provider，可并发）。**debate/refine 形态**：`Bash` 调 `uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/orchestrate.py" <mode> …` 由脚本**确定性编排**外部底座的多步拓扑，输出结构化 JSON 中间产物（`steps` 含各步 text/error）。 |

**为何 debate/refine 的拓扑走 `orchestrate.py`、不进 panel.js**：① 两形态**跨底座**——`Workflow.agent()` 是 Claude Code 专属且 `model` 只能是 Claude，调不了外部底座；② 它们有**串行依赖**（立论→反驳 / 生成→互评/质检），靠主会话「自觉」逐步调模型不可复现。故由 `orchestrate.py`（Python on `ai_client`，asyncio）把外部底座多步拓扑**确定性编排**成结构化 JSON；`panel.js` 仍只服务 **panel 形态的并行宿主 persona 批**。**收口（裁决/合并/修订 = 宿主主裁）调不了主会话自己，留主会话**——与 panel.js 把综合留主会话同一分工。脚本本身**不做门控决策**（门控属收口者），只输出素材（辩论记录 / 双初版+互评 / 初版+质检评分）。

> 确定性 fan-out 用 Workflow，主会话持判断与收口权。panel.js 同样**不**落盘、不 commit、不 Edit，只产角色素材。

---

## 4. 角色卡 / 角色输出 schema

panel 形态每个角色产一张同构**角色卡**（不直接落盘，多模型产出归素材性质）：

```
{
  role:                    "架构红队",          // 角色名
  model:                   "host | claude-cli | codex-cli | cursor:gpt-5 | deepseek-chat",
  stance:                  "一句话总立场",
  key_points:              ["核心论点 1", ...],
  risks:                   ["它看到的风险 1", ...],
  challenged_assumptions:  ["它质疑的隐含前提 1", ...],   // 盲区互补的关键产出
  recommendation:          "它的建议（采纳 / 改造 / 否决 + 理由）"
}
```

其它形态的角色输出按拓扑约定的结构（debate 立论/反驳的论点表；refine 的 **H/M/L + 评分** 互评/质检表，见 §2.2–§2.3），不强制角色卡 schema。

### panel persona 的 prompt 骨架（panel.js 内 buildPrompt / 或主会话自扮演时同款）

```
你是多模型 panel 的【<角色名>】。议题如下。
<主会话摘录的自包含上下文：背景 + 待决问题 + 相关架构决策摘录（如有）>

你的强制视角（不得越界）：<该角色的 lens / 立场约束，见 §1>
严格按角色卡 schema 输出：stance / key_points / risks / challenged_assumptions / recommendation。
只用你的判断，不要附和其它角色（你看不到他们）。
```

### 外部模型的 prompt 骨架（主会话喂给 ai_client，按形态填角色与任务）

```
你是多模型协作的【<角色：外部视角 / 正方 / 反方 / Agent A / 生成者 / 质检者>】。议题/任务：<自包含上下文>。
<该角色的立场与产出要求：panel 补盲；debate 坚持本方立场；refine two-way 独立生成或互评；refine one-way 生成或按 H/M/L 质检>。
```

> CLI transport 的只读封装（`claude -p --permission-mode plan` / `codex --sandbox read-only` / `cursor-agent --mode ask`）由 `ai_client/providers.py` 固化，prompt 层只管内容。

---

## 5. 收口契约（主裁 = 当前宿主主模型，唯一收口者）

每种形态的收口都由当前宿主主模型完成，**摆矛盾、不和稀泥**。固定契约：

| 形态 | 收口动作 | 固定输出 |
|---|---|---|
| **panel** | 综合 | ①**共识** ②**分歧**（保留张力、谁说什么、为何冲突，不调和）③**被挑出的盲区**（值得正视的 challenged_assumptions）④**综合结论**（可与任一角色不同） |
| **debate** | 裁决 | **置信度(0–100%)** + 胜负判定（支持正/反/有条件支持）+ 逐对论点比较 + 关键分歧/共识 + 综合决策建议 + 风险提示；**必须明确裁决不回避**，势均力敌选风险更低一方 |
| **refine / two-way** | 合并 | 合并终稿（**标注每段来源 A/B/综合**）+ 对 M/L 争议的裁定 + 关键差异摘要；若双方无 H 且≥85 则免独立修订直接合并 |
| **refine / one-way** | 修订 | 修订版（H 全改 / M 尽量 / L 保持）+ 折叠质检报告 + 逐条处理说明；若质检 ≥85 则原样输出初版并注明"质检免修订" |

> 单声旁路 **direct 无收口动作**（原样转述即终态），不在本表——见 §2.4。

多模型产出是**素材**，落地与拍板权归主裁。收口结果小结给用户，不落文档（§7）。

---

## 6. 触发纪律（防滥用烧钱）

会诊引擎 **不默认开**，命中下列之一才点燃：

- **真权衡**：某决策出现 ≥2 个可行方案且取舍不明（→ 倾向 debate）。
- **高风险**：触及写入 / 认证 / 金额，或要动项目已记录的重大架构决策（如有）。
- **显式要求**：用户说"会诊 / 压测 / 听听别的模型 / 辩论 / 互评 / 质检"。

**不点燃**：术语对齐、能查代码/文档直接回答的、低风险默认决策。各宿主的触发点见 §7。

**形态适配检查**：debate 须二元对立议题（非对立提示换 panel/refine）；refine `one-way`（质检）须有"待审材料/草稿"（无材料则先用别的形态或 `two-way` 产出）。

**用户指定模型（措辞分流）**——点名某个已配 provider 时按措辞分两路（id 须在 `ai_client/.env.toml [providers.*]`，未配则告知可选项、不臆造）：

| 措辞 | 路由 | 行为 |
|---|---|---|
| "**只用** X / 单独让 X / 让 X 分析这个问题/文档" | direct 旁路（§2.4） | 跳过多角色 + 收口，主会话直接调 X，转述其答案 |
| "**用** X 一起讨论 / 压测 / 让 X **也**看看" | panel/其它协作形态 | 照常多形态，对应席位 provider **覆盖**为 X（替换 §8 默认池） |

---

## 7. 落盘边界（按宿主分场）

区分两件事：**产出落盘**（结论怎么进 docs/，由宿主 skill 按既有规则决定，§7.1）与**过程留痕**（本次会诊素材进 `.cache`，强制、自动、与产出落盘无关，§7.2）。

### 7.1 产出落盘（结论怎么落，宿主项目决定）

会诊引擎自身**永不把产出落到任何文档**；结论怎么落由**宿主项目的下游 skill** 按自己的既有规则决定（如该项目装了审问 / PRD 起草 / 决策同步类 skill）：

| 场景 | 何时点燃 | 消费 / 产出落盘 |
|---|---|---|
| `/to-consult`（手动） | 用户任意点召唤 | **产出不落文档**，小结给用户；结论交宿主项目下游 skill（如有）取用 |
| `/to-grill`（审问中内部点燃） | 审问命中真权衡（≥2 方案取舍不明）/ 高风险（§6） | 收口结论并入审问、按 to-grill 自身规则回写**被审问文件本体**（决策段） |
| 宿主项目其它下游 skill | 该 skill 自行判定何时调用 | 由该 skill 既有规则消化（本规范不规定具体落盘格式） |

### 7.2 过程留痕（强制·机制，留痕到宿主项目缓存）

**每次会诊全程强制留痕**到宿主项目的 `.consult-cache/to-consult/<任务名>/session.md`（脚本据 `CLAUDE_PROJECT_DIR` / `CONSULT_CACHE_DIR` 定位；宿主项目自行 gitignore，属过程素材≠产出落盘），便于追溯外部模型那次**不可复现**的输出。单一写入点 = `ai_client/consult_log.py`：

- **任务名** `<时间戳>_<议题slug>`：由 `consult_log.py start` 权威生成时间戳并 stdout 回显，主会话据此给所有脚本调用传 `--task`，同次会诊多次调用落同一目录。
- **记录内容**：启动模式 / 启动提示词（触发原话）/ 参与模型 / 每次外部调用的**命令行或 API 请求**（脱敏）+ prompt + **外部生响应** / 主裁**收口结论**。
- **三条写入路径**（§10 骨架）：① 主会话编排前 `start` 建头部；② `cli.py`（panel 外部批 / direct）与 `orchestrate.py`（debate/refine 每步）调用边界**自动**记请求+生响应；③ 主会话收口后 `verdict` 追写收口结论（正文走 stdin）。
- **脱敏铁律**：API 请求**绝不含 api_key**、不含 messages 正文；命令行里 prompt 用 `<prompt:N字>` 占位（正文另记一次）。
- **非阻塞**：写盘失败只 warn 不抛，绝不阻断会诊（§9「增益不是依赖」）。
- **已知限制**：panel 的宿主 persona 批由 `panel.js`（Workflow）产出，Workflow **不能写文件**，故宿主 persona 卡不进留痕；外部批与主裁收口照常留。

---

## 8. 外部模型接入（指向 ai_client）

外部声音的全部 transport 收敛在插件的 `ai_client/`（详见其 README）。统一契约 `ask(provider, prompt) -> text`，四种 transport：

| transport | 模型 | key |
|---|---|---|
| `claude-cli` | Claude（`claude -p --permission-mode plan` 只读 print） | 复用 Claude Code 登录态，零 key |
| `cursor-cli` | gpt-5 / sonnet-4 / sonnet-4-thinking …（`--mode ask` 只读） | 复用登录态，零 key |
| `codex-cli` | GPT 系（`--sandbox read-only`） | 复用登录态，零 key |
| `openai-compat` | OpenAI / DeepSeek / ollama / qwen 等任意兼容厂商 | `.env.toml` 填 |

**外部声音池按宿主取**：`.env.toml` 的 `[to-consult.external_voices]` 为每个宿主声明一组 provider（已排除同底座）：

```toml
[to-consult.external_voices]
claude = ["codex", "cursor"]     # 宿主 = Claude Code → 外部用 codex + cursor
codex  = ["claude", "cursor"]    # 宿主 = Codex       → 外部用 claude + cursor
cursor = ["claude", "codex"]     # 宿主 = Cursor      → 外部用 claude + codex
```

主会话据**自身宿主身份**取对应数组：池里 `[0]` / `[1]` 分别充当 debate 正/反方、refine ext0/ext1（two-way=A/B、one-way=生成/质检），panel 形态则全部当外部视角。**用户可显式覆盖**——"用 qwen 一起讨论"即把对应席位换成 `qwen`（§6 分流）。三个 CLI provider 的 `model` 缺省即用各工具**主模型**。主会话调用：

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider <provider_id> "<§4 角色 prompt>"
```

**分析/审查文档**时加 `--file`（可重复），由 `cli.py` 读出文件内容嵌入 prompt 前部——所有 transport 通用，尤其 `openai-compat`（纯 API，如 qwen）自身无文件访问能力，必须靠这里读出嵌入：

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider qwen --file <path/to/doc.md> "<分析指令>"
```

---

## 9. 降级与失败处理

| 情形 | 主会话行为 |
|---|---|
| 宿主无 `Workflow`（Codex / Cursor） | **正常路径**，非降级：panel 形态的宿主 persona 批由主会话**串行自扮演**，外部批照常走 `ai_client` |
| 某个外部席位超时 / 报错 / 未登录 / 无 key | panel：跳过该席少一张卡；debate/refine：用**宿主底座补位**该角色并标注"<角色>与收口同底座、未经完全独立第三方"（裁判/合并/修订角色本就=主裁，不另补） |
| 外部只剩 1 个（debate/refine 需 2 对抗角色） | 一方用外部、另一方用宿主底座补位，标注同源折扣；收口角色仍=主裁 |
| 收口角色（裁判/合并/修订）失败 | 输出已收集的素材（立论+反驳 / 两初版+互评 / 初版+质检）让用户判断，**不把收口降级到对抗方同实例** |
| 某 persona 角色卡 schema 漂移 | 主会话重派 1 次；仍漂移则按缺席处理 |
| 全部外部 + 多数宿主角色失败 | 该次协作流产，如实告知用户，回退到主裁单模型继续 |

核心：会诊引擎是**增益**不是依赖——任何一环挂掉都能降级回单模型，不阻断需求流程。

---

## 10. 调用骨架

### panel 形态：宿主 persona 批（仅 Claude Code 宿主）args 契约

Claude Code 宿主下，主会话组装后调 `Workflow({scriptPath: "${CLAUDE_PLUGIN_ROOT}/scripts/panel.js", args})`：

```
args = {
  topic:   "一句话议题",
  context: "主会话摘录的自包含上下文（背景 + 待决问题 + 相关架构决策摘录，如有）",
  rounds:  1,                                  // 默认 1
  roster:  [                                   // 宿主 persona 列表
    { role: "架构红队", lens: "<§1 约束>" },
    { role: "价值质询", lens: "<§1 约束>" },
    { role: "唱反调者", lens: "<§1 约束>" },
  ],
}
// 返回：与 roster 等长的角色卡数组（§4 schema）
```

非 Claude 宿主不调 panel.js，主会话按 roster + lens **自扮演**产卡。外部视角批走下方 `ai_client`。

### 各形态完整编排（宿主 skill 的步骤）

1. 判定是否命中 §6 触发；不命中则不开。**先按 §2「形态选择」定 mode**（含 §6 措辞分流到 direct）。
2. 主会话摘录自包含 `context`（不让角色自己漫游）。
3. **探测当前宿主**（claude / codex / cursor），取 `external_voices[host]` 池。
4. **建留痕会话**（§7.2，强制）：取任务名 `$TASK`，本次后续所有脚本调用都带 `--task "$TASK"`。
   ```bash
   TASK=$(uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/consult_log.py" start --slug <议题slug> --mode <M> \
     --trigger "<启动提示词>" --host <host> --models "<席位→模型清单>")
   ```
5. 按形态编排（命令均带 `--task "$TASK"`）：
   - **panel**：宿主 persona 批（Workflow/自扮演）‖ 外部视角批（`Bash` 调 `cli.py --task "$TASK" --mode panel --role 外部视角` 池里每个 provider）并发出卡。
   - **debate / refine**：`Bash` 调 `orchestrate.py` 一次性确定性跑完外部底座多步拓扑，拿结构化 JSON（`steps` 含各步 text/error；refine 还带 `direction`）：
     ```bash
     uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/orchestrate.py" debate --task "$TASK" --pro  <ext0> --con  <ext1> "<topic>" [--context …] [--file …]
     uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/orchestrate.py" refine --task "$TASK" --ext0 <ext0> --ext1 <ext1> "<task>"  --direction two-way|one-way [--context …] [--file …] [--skip-gen]
     ```
     `<ext0>`/`<ext1>` = `external_voices[host]` 两席。refine `two-way`=双声互评合并、`one-way`=单向质检修订（`--skip-gen` 仅 one-way）。脚本跑到收口前即止、不做门控决策；各步请求+生响应自动留痕。
   - **direct 旁路**（非协作形态）：见 §2.4（走 `cli.py --task "$TASK" --mode direct` 直问 + relay，不进收口）。
6. 主裁按 §5 对应契约**收口**（脚本调不了宿主主裁，故收口必在主会话）：
   - debate：读辩论记录裁决 + 置信度门控（<85 可再调一次 `orchestrate.py` 续辩、或主裁直接二轮）。
   - refine `two-way`：读两初版 + 互评合并（双方无 H 且 ≥85 跳独立修订）。
   - refine `one-way`：读质检评分，≥85 免修订直接输出初版，否则主裁修订。
   - 任何步 `error`/`skipped` → 按 §9 降级（外部不足用宿主底座补位）。
7. **写收口留痕**（§7.2）：`printf '%s' "<收口结论>" | uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/consult_log.py" verdict --task "$TASK" --mode <M>`。→ 再按 §7.1 宿主项目下游 skill（如有）规则消费。
