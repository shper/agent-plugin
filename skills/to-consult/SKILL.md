---
name: to-consult
description: >
  就一个议题召集多模型会诊：3 种协作形态——panel（并行独立盲区互补）/ debate（正反辩论+裁判裁决）/ refine（精炼：two-way 双声互评合并 / one-way 单向质检修订）；外加 direct 单声旁路（点名"只用 X"时跳过协作直问单个模型，非协作形态）。宿主底座 + 跨底座外部声协作、当前宿主主模型收口。宿主无关——谁打开项目（Claude Code/Codex/Cursor）谁就是主裁。
  形态按 mode 入参或措辞自动判定；外部声按当前宿主取池（排除同底座）。手动入口，产出不落文档（过程强制留痕到宿主项目缓存）——结论交下游工具取用（如项目装了审问/起草类 skill）。
  当用户说"会诊"、"找几个模型会诊"、"多模型讨论"、"听听别的模型怎么说"、"压测这个方案"、"辩论一下/该用 A 还是 B"、"互评/多视角打磨"、"质检/审一下这篇/润色"、"让 GPT/cursor 也看看"、"只用 qwen/某模型 分析这个问题或文档"时触发。
argument-hint: "[mode=panel|debate|refine|direct] [--direction two-way|one-way] [--用 <provider>] <议题或文档路径>"
version: v2.1.0
status: active
owner: shper
updated: 2026-06-18
related:                                            # 路径相对插件根（agent-plugin/）
  - skills/to-consult/consult-common.md
  - skills/to-consult/mode-panel.md
  - skills/to-consult/mode-debate.md
  - skills/to-consult/mode-refine.md
  - skills/to-consult/mode-direct.md
  - skills/to-grill/SKILL.md
  - ai_client/README.md
  - ai_client/consult_log.py
  - scripts/panel.js
---

# to-consult — 多模型会诊引擎

就一个议题，让多个角色（含跨厂商模型）按某种**协作拓扑**出观点、**当前宿主的主模型**收口，给讨论引入**第二个声音**做盲区互补。

> **本文件 = 入口 + 形态判定 + 8 步执行流程**，按形态 router 加载下面文件：
>
> | 文件 | 角色 | 何时读 |
> |---|---|---|
> | `./consult-common.md` | 跨形态共享规范（§0 宿主无关 / §1 底座 / §3 物理架构 / §6 触发 / §7 落盘 / §8 外部接入 / §9 降级） | 全程兜底 |
> | `./mode-panel.md` | panel 形态：并行独立盲区互补 | Step 1 命中 panel |
> | `./mode-debate.md` | debate 形态：正反辩论 + 裁判裁决 | Step 1 命中 debate |
> | `./mode-refine.md` | refine 形态：双向互评 / 单向质检 | Step 1 命中 refine |
> | `./mode-direct.md` | direct 旁路（非协作形态） | Step 1 命中 direct，早退 |
>
> **宿主无关**：不假设宿主是哪个 CLI。主裁 = 当前宿主主模型；角色批派发按宿主能力探测（consult-common §3）。
> 边界：**产出不落文档、不改代码**；但过程素材**强制留痕**到宿主项目的 `.consult-cache/to-consult/<任务名>/`（脚本据宿主项目根定位：`CLAUDE_PROJECT_DIR` / cwd 兜底，宿主项目自行 gitignore，consult-common §7）。小结给用户，结论交下游工具取用。

---

## 通用原则

- 执行前加载必要上下文（由宿主项目约定其上下文加载纪律），把议题相关背景读够。
- 全程遵循 `./consult-common.md` 的共享规范；命中形态后**必读对应 mode 文件**取拓扑/契约/骨架。

## 执行步骤

### Step 1: 定形态（含 direct 早退分流）

- 按 `mode=` 入参选形态（refine 再按 `--direction` 或措辞分 two-way|one-way）；无显式 mode 则按下表措辞自动判定，**显式 mode 优先**。
- **命中 `direct` 旁路**（"只用 X / 让 X 分析"）→ 读 `./mode-direct.md` 走单声直问，**早退结束，不进后续步骤**。
- 判不准就按 `panel`，并提示用户"按 panel 走，要辩论/精炼请加 mode=debate|refine"。
- 指定 provider 措辞（"用 X 一起讨论"）→ 把对应席位 provider 覆盖为 X（consult-common §6 分流）。

措辞表须与本 skill `description` 的触发词**全量对齐**（描述里宣传的每个触发词都要能在此落到某形态，不靠"其它/默认"兜走）：

| 措辞 | 形态 | 加载文件 |
|---|---|---|
| "会诊 / 多模型讨论 / 压测这个方案 / 听听别的模型怎么说 / 让 X **也**看看 / 多模型看看" | panel | mode-panel.md |
| "辩论 / 选型 / 二选一 / **该用 A 还是 B**"（须**真**二元决策，见下） | debate | mode-debate.md |
| "互评 / 多视角打磨 / 双人对照" | refine `two-way` | mode-refine.md |
| "质检 / 审一下这篇 / 润色 / 把关" | refine `one-way` | mode-refine.md |
| "只用 X / 单独让 X / 让 X 分析" | direct | mode-direct.md |
| 无任何关键词命中 | panel（默认）+ 提示"按 panel 走，要辩论/精炼请加 mode=debate\|refine" | mode-panel.md |

> **debate 防误触发**：仅当议题是**待决的真二元选择**（要据此拍板）才进 debate；闲聊式"你觉得 A 好还是 B 好"、并非要做决策的随口比较 → 按 panel 或直接答，不空烧正反辩论（与 Step 2 形态适配检查一致）。

### Step 2: 触发与形态适配检查（consult-common §6）

- 取入参议题（无参则取当前对话焦点）。手动 `/to-consult` 即视为显式要求，直接进 Step 3；但能查代码/文档直接答的低风险问题，先告知"这个不必会诊"。
- **形态适配检查**：debate 须二元对立议题（非对立提示换 panel/refine）；refine `one-way`（质检）须有"待审材料/草稿"（无则先用别的形态或 `two-way` 产出）。

### Step 3: 摘录自包含上下文

把议题相关背景 + 待决问题 + 相关架构决策（如有）摘录成一段**自包含 context**（角色据此判断，不自行漫游全仓）。

### Step 4: 探测宿主 + 取外部声音池 + 独立性检测（consult-common §8）

探测当前宿主（claude / cursor / codex），读 `~/.agent-plugin/env.toml` 的 `[to-consult.external_voices][host]` 取池（Step 1 有覆盖则用覆盖值）。池里 `[0]`/`[1]` 充当 debate 正/反方、refine ext0/ext1（two-way=A/B、one-way=生成/质检）；panel 形态则全部当外部视角。

**跨底座独立性检测（C4，强制·非阻塞）**：取池后调一次 `independence.py`，按**模型族**检出真同源（外部席与主裁同族 / 池内两席同族）——杜绝多模型退化成**伪交叉验证背书**；同网关只作可用性提示、不计折扣（同网关≠同源）：

```bash
uv run "$ROOT/ai_client/independence.py" --host <claude|codex|cursor> --pool <池逗号分隔>
```

有重合（`INDEPENDENCE: warn(N)`）则**在小结里如实告诉用户哪些席位同源、独立性打折**；重合严重（如对抗双方同族）按 consult-common §9 流产。debate/refine 走 `orchestrate.py` 时已自动把该检测嵌进 envelope 的 `independence` 字段（传 `--host` 即可），panel 形态由本步显式调用。

### Step 5: 建留痕会话（consult-common §7.2 强制）

编排前调一次 `consult_log.py start` 取任务名 `$TASK`，本次会诊后续所有脚本调用都带 `--task "$TASK"`（脚本据此把请求+生响应落到同一目录）：

```bash
ROOT="${CLAUDE_PLUGIN_ROOT:-$PLUGIN_ROOT}"   # 变量在 hook 外常为空→主会话据本 skill 目录上两级代入插件根（consult-common §3）
TASK=$(uv run "$ROOT/ai_client/consult_log.py" start \
  --slug <议题slug> --mode <panel|debate|refine|direct> \
  --trigger "<启动提示词/触发原话>" \
  --host <claude|codex|cursor> \
  --models "<席位→模型清单>")
```

### Step 6: 加载 mode 文件 + 按其编排骨架执行

**进入对应 mode 文件**（Step 1 判定结果），按其中「编排骨架」执行：

- panel → `./mode-panel.md` §7（宿主 persona 批 + 外部视角批，并发出卡）
- debate → `./mode-debate.md` §6（`orchestrate.py debate` 一次性确定性跑完正反立论+反驳）
- refine → `./mode-refine.md` §6（`orchestrate.py refine --direction two-way|one-way`）
- direct → 已在 Step 1 早退，不进入此步

某步 `error`/`skipped` → 按 consult-common §9 降级（外部不足用宿主底座补位，收口角色恒=主裁）。

### Step 7: 主裁收口（mode 文件中的收口契约）

当前宿主主模型按对应 mode 文件中的**收口契约**收口，**摆矛盾不调和**：

- panel → 综合（共识/分歧/盲区/结论）
- debate → 裁决（置信度/胜负/逐对比较/建议/风险）
- refine `two-way` → 合并（终稿+来源标注+差异）
- refine `one-way` → 修订（修订版+质检报告）

### Step 8: 写收口留痕（consult-common §7.2）+ 小结

- **把主裁收口结论写进留痕**（强制）：主裁收口后，经脚本把结论追写进本会话目录（正文走 stdin）：
  ```bash
  printf '%s' "<主裁收口结论全文>" | uv run "${CLAUDE_PLUGIN_ROOT:-$PLUGIN_ROOT}/ai_client/consult_log.py" verdict --task "$TASK" --mode <同 start 的 mode>
  ```
  至此本次会诊全程（启动模式 / 模型 / 启动提示词 / 命令行或 API 请求 / 外部生响应 / 主裁结论）留痕在宿主项目 `.consult-cache/to-consult/$TASK/session.md`。注：panel 宿主 persona 卡虽由 Workflow 产出（不能写文件），但主会话用 `consult_log.py cards` 回填，留痕完整（C1，mode-panel §7.2）。
- 收口结果小结给用户，提示下游：要把结论审问落文件 / 综合成 PRD，交宿主项目对应的下游 skill（如已安装）。

---

## 注意事项

- **产出不落文档、不改代码**——这是协作引擎，产出是素材，落地由下游 skill 或用户决定；但**过程素材强制留痕**到宿主项目 `.consult-cache/to-consult/<任务名>/`（consult-common §7.2），便于追溯外部模型那次不可复现的输出。
- 会诊是增益不是依赖：任一席位或宿主批挂掉都按 `consult-common §9` 降级回单模型，不阻断。
- 触发要克制（consult-common §6）：低风险、能查就答的问题不必会诊，避免空烧多模型额度；形态别越级（简单问题别上 debate）。
- 角色的强制对立 lens / 立场不可松绑成"全面评价"，否则退化为同质独白（consult-common §1）。
