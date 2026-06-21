---
title: panel 形态（并行独立盲区互补）
mode: panel
parent: SKILL.md
updated: 2026-06-18
---

# panel 形态 — 并行独立、盲区互补

> 默认形态。宿主 3 persona（强制对立 lens）+ 外部声音池**互不可见**地并行各出一张角色卡，主裁综合。
> 共享规范（宿主无关 §0 / 底座 §1 / 触发 §6 / 落盘 §7 / 外部接入 §8 / 降级 §9）见 `./consult-common.md`，本文件只写 panel 专属。

---

## 1. 拓扑

并行独立出卡，无串行依赖。3 个宿主 persona + 池里全部外部 provider 各产 1 张角色卡，主会话编排并发后由主裁综合。

适用：盲区互补、需求讨论、方案初探。

## 2. 宿主 persona 强制 lens（拉开同底座区分度）

| persona | 强制 lens / 立场约束 |
|---|---|
| 架构红队 | **只**挑技术可行性 / 与项目已记录架构决策（如有）冲突 / 实现风险；不评价产品价值 |
| 价值质询 | **只**挑"是否解决真问题 / ROI / 是否过度设计 / 更省的替代方案"；不碰技术实现细节 |
| 唱反调者 | **强制**只列"这方案会失败 / 被推翻的 ≥3 个理由"，**禁止**说优点 |

约束写进各 persona prompt（见 §4），不可松绑成"全面评价"——否则退化为同质独白。

## 3. 角色卡 schema（panel 专属强制结构化）

panel 形态每个角色产一张同构**角色卡**（不直接落盘，多模型产出归素材性质）：

```
{
  role:                    "架构红队",          // 角色名
  model:                   "<产出该卡的底座 id>",  // 宿主 persona = 当前宿主底座 id（claude / codex / cursor）；外部视角 = 该席的 env.toml provider id（取自 council[host]，如 deepseek / glm / minimax / claude / codex）。**非固定枚举**——随 env.toml 实配的 provider 变；由编排方（panel.js / 主会话）回填，非角色自报
  stance:                  "一句话总立场",
  key_points:              ["核心论点 1", ...],
  risks:                   ["它看到的风险 1", ...],
  challenged_assumptions:  ["它质疑的隐含前提 1", ...],   // 盲区互补的关键产出
  recommendation:          "它的建议（采纳 / 改造 / 否决）+ 理由 + 该建议的优缺点/代价/前提（不抛裸结论）"
}
```

## 4. Prompt 骨架

### panel persona 的 prompt 骨架（panel.js 内 buildPrompt / 或主会话自扮演时同款）

```
你是多模型 panel 的【<角色名>】。议题如下。
<主会话摘录的自包含上下文：背景 + 待决问题 + 相关架构决策摘录（如有）>

你的强制视角（不得越界）：<该角色的 lens / 立场约束，见 §2>
严格按角色卡 schema 输出：stance / key_points / risks / challenged_assumptions / recommendation。
只用你的判断，不要附和其它角色（你看不到他们）。
```

### 外部视角的 prompt 骨架（主会话喂给 ai_client）

外部声**不得**给"全面评价/温和综述"——否则会退化成主裁的背景板（评测 risk：外部声 prompt 强度远弱于宿主 persona）。给每个外部席**强制一个对立 lens**（池内多席就轮派下表，或复用 §2 的三 lens），与宿主 persona 同等锋利：

| 外部 lens | 强制约束 |
|---|---|
| 反例猎手 | **只**找"这方案在什么场景/边界会崩"的具体反例 ≥3 个；不夸优点 |
| 隐性成本 | **只**挑被忽略的成本（运维 / 迁移 / 认知 / 长期维护 / 锁定）；不谈功能 |
| 更优替代 | **只**论证"有没有更简单/更省/已有的方案能替掉它"；不评细节实现 |

```
你是多模型协作的【外部视角·<本席 lens 名>】。议题：<自包含上下文>。
你的强制视角（不得越界，不许给全面评价/和稀泥）：<该 lens 约束>。
只用这一视角挑问题，按上方角色卡 schema 输出（challenged_assumptions 宁可多列）。
```

> CLI transport 的只读封装由 `ai_client/providers.py` 固化（见 consult-common §8），prompt 层只管内容。

## 5. 物理架构（panel 专属：两批拼成一次会诊）

| 批次 | 派发者 | 机制 |
|---|---|---|
| **宿主底座批**（3 persona） | 主会话 | **按宿主探测派发**：Claude Code 有 `Workflow` → 走 `<$ROOT 解析后的绝对路径>/scripts/panel.js` 确定性 `parallel()` fan-out（scriptPath 不展开变量，须传绝对路径）（每角色一个 agent，schema 强制角色卡）；Codex / Cursor **无 `Workflow`** → 主会话**串行自扮演**（lens 照旧强制，质量等价只是不并行） |
| **非宿主底座外部批** | 主会话 | `Bash` 调 `uv run "$ROOT/ai_client/cli.py" --provider <id>` 取各外部视角（`$ROOT` 见 consult-common §3；池里每个 provider，可并发） |

> 确定性 fan-out 用 Workflow，主会话持判断与收口权。`panel.js` 同样**不**落盘、不 commit、不 Edit，只产角色素材。

## 6. 收口契约（主裁 = 当前宿主主模型）

| 收口动作 | 固定输出 |
|---|---|
| **综合** | ①**共识** ②**分歧**（保留张力、谁说什么、为何冲突，不调和）③**被挑出的盲区**（值得正视的 challenged_assumptions）④**综合结论 + 详细说明**（见下「结论详述要求」，可与任一角色不同） |

**结论详述要求**（④综合结论不抛裸结论，至少讲清）：
- **是什么**：综合推荐的具体方案 / 取向，不止一句结论。
- **为什么**：依据哪些角色卡的论点 / 风险 / 盲区得出，逻辑链交代清。
- **优缺点 / 弊端 / 代价**：该结论好在哪、牺牲了什么、有何风险副作用、什么前提下不成立。
- **备选与弃因**：角色间有真分歧时，列出被否的取向并说明为何不选——保留张力而非抹平。
- **业界 / 先例对照**：综合结论相对业界成熟做法 / 既有先例处于什么位置（沿用 / 偏离 / 重造轮子）；偏离给出理由。⚠️ 注明是判断非权威，能查证就查证，不硬凑"最佳实践"。
- **最强反对（pre-mortem）**：给一条反对【本结论本身】的最强论据（最可能因为什么被推翻），而非只说备选更差。

**摆矛盾不调和**——多模型产出是素材，落地与拍板权归主裁。

## 7. 编排骨架

### 7.1 宿主 persona 批 args 契约（仅 Claude Code 宿主）

**调用前先用一条 Bash 把绝对根算出来并校验**（确定性、穿透 symlink，别让主会话心算路径——见 consult-common §3 红线）：

```bash
ROOT="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-<主会话代入：realpath 本 SKILL.md 目录上两级的绝对路径，勿留空>}}"
test -f "$ROOT/scripts/panel.js" && echo "PANEL_JS=$ROOT/scripts/panel.js" || echo "MISSING"   # 回显绝对路径供下步代入；MISSING 则走兜底
```

拿到回显的绝对路径后再调 `Workflow({scriptPath: "<上一步回显的绝对路径>", args})`——**`scriptPath` 不展开环境变量**，只接受算好的绝对字面路径，绝不能写 `${CLAUDE_PLUGIN_ROOT}/...` 或相对路径。args 契约：

```
args = {
  topic:   "一句话议题",
  context: "主会话摘录的自包含上下文（背景 + 待决问题 + 相关架构决策摘录，如有）",
  rounds:  1,                                  // 默认 1
  roster:  [                                   // 宿主 persona 列表
    { role: "架构红队", lens: "<§2 约束>" },
    { role: "价值质询", lens: "<§2 约束>" },
    { role: "唱反调者", lens: "<§2 约束>" },
  ],
}
// 返回：与 roster 等长的角色卡数组（§3 schema）
```

非 Claude 宿主不调 panel.js，主会话按 roster + lens **自扮演**产卡。

### 7.2 完整步骤（接 SKILL.md 「执行步骤」 Step 6 进入本节）

承接：留痕会话 `$TASK` 已建立（SKILL.md Step 5 / consult-common §7.2），外部声音池 `council[host]` 已取定、并已过 Step 4 的独立性检测（panel 形态外部席多，尤其要看 `independence.py` 报的同族/同网关告警）。

0. **跨底座独立性检测**（C4，承 SKILL.md Step 4）：`uv run "$ROOT/ai_client/independence.py" --host <host> --pool <池>`；有重合则在综合收口里如实标注哪些外部视角同源、其卡的"独立补盲"价值打折。
1. **宿主 persona 批**：Claude Code → 先按 §7.1 用 Bash 算出 `panel.js` 绝对路径并校验，再 Workflow(panel.js)；Codex / Cursor → 主会话自扮演 3 角色卡。**失败兜底**：若上步校验报 `MISSING`、或 Workflow 报 `script file not found`，**不阻断**——直接退回「主会话自扮演 3 角色卡」（与非 Claude 宿主同款正常路径），别让一次路径失误打挂 panel 整批。
2. **外部视角批**（并发出卡）：池里每个 provider 单独调一次 `cli.py`：
   ```bash
   ROOT="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-<主会话代入：realpath 本 SKILL.md 目录上两级的绝对路径，勿留空>}}"   # 三档缺一不可：裸二档双空→ROOT=空串→路径退化 /ai_client/…（consult-common §3）
   uv run "$ROOT/ai_client/cli.py" \
     --provider <id> --task "$TASK" --mode panel --role 外部视角 \
     [--file <doc>] "<§4 外部视角 prompt>"
   ```
3. **补录宿主 persona 卡留痕**（C1）：`panel.js` 是 Workflow 不能写文件，主会话收齐后把 3 张卡（JSON 或精简 markdown）经 stdin 回填 session.md：
   ```bash
   printf '%s' "<3 张宿主 persona 卡>" | uv run "$ROOT/ai_client/consult_log.py" cards --task "$TASK" --mode panel
   ```
4. 收齐两批角色卡 → 主裁按 §6 综合契约收口。
5. 收口结论按 SKILL.md Step 8 写入留痕（`consult_log.py verdict`）。

降级：某外部席位失败跳过该卡（少一张，不补位）；persona schema 漂移重派 1 次，仍漂移按缺席处理（详见 consult-common §9）。**外部批全部失败 / 池本就为空**（取不到任何独立外部声）→ 不止留 3 张宿主 persona 自检，先进 consult-common **§9.1 host 交互降级**：probe + 逐角色让用户选 host 模型当各外部视角席（`--provider` 传内联 spec `type:model`，lens 分配不变）；用户跳过 / 非交互才退纯宿主 persona + 主裁。

> 留痕完整性（C1 已补）：`panel.js`（Workflow）本身不能写文件，但主会话收齐后用 `consult_log.py cards` **回填** 3 张宿主 persona 卡——默认形态 panel 的留痕不再缺最有料的那批（外部批与主裁收口照常自动留，见 consult-common §7.2）。
