---
name: to-consult
description: >
  就一个议题召集多模型会诊：3 种协作形态——panel（并行独立盲区互补）/ debate（正反辩论+裁判裁决）/ refine（精炼：two-way 双声互评合并 / one-way 单向质检修订）；外加 direct 单声旁路（点名"只用 X"时跳过协作直问单个模型，非协作形态）。宿主底座 + 跨底座外部声协作、当前宿主主模型收口。宿主无关——谁打开项目（Claude Code/Codex/Cursor）谁就是主裁。
  形态按 mode 入参或措辞自动判定；外部声按当前宿主取池（排除同底座）。手动入口，产出不落文档（过程强制留痕到宿主项目缓存）——结论交下游工具取用（如项目装了审问/起草类 skill）。
  当用户说"会诊"、"找几个模型会诊"、"多模型讨论"、"听听别的模型怎么说"、"压测这个方案"、"辩论一下/该用 A 还是 B"、"互评/多视角打磨"、"质检/审一下这篇/润色"、"让 GPT/cursor 也看看"、"只用 qwen/某模型 分析这个问题或文档"时触发。
argument-hint: "[mode=panel|debate|refine|direct] [--direction two-way|one-way] [--用 <provider>] <议题或文档路径>"
---

# to-consult — 多模型会诊引擎

就一个议题，让多个角色（含跨厂商模型）按某种**协作拓扑**出观点、**当前宿主的主模型**收口，给讨论引入**第二个声音**做盲区互补。

> 定位：多模型会诊的**手动入口**。机制、形态集、角色映射、收口契约的单一来源是 `${CLAUDE_PLUGIN_ROOT}/CONSULT-GUIDE.md`——本文件只写编排路由，不复述规范。
> **宿主无关**：不假设宿主是哪个 CLI。主裁 = 当前宿主主模型；角色批派发按宿主能力探测（CONSULT-GUIDE §3）。
> 边界：**产出不落文档、不改代码**；但过程素材**强制留痕**到宿主项目的 `.consult-cache/to-consult/<任务名>/`（脚本据 `CLAUDE_PROJECT_DIR` 定位，宿主项目自行 gitignore，§7）。小结给用户，结论交下游工具取用。

## 通用原则

- 执行前加载必要上下文（由宿主项目约定其上下文加载纪律），把议题相关背景读够。
- 全程遵循 `${CLAUDE_PLUGIN_ROOT}/CONSULT-GUIDE.md`：宿主无关三要素（§0）、角色集与底座分配（§1）、形态（§2）、物理架构两批（§3）、角色 schema（§4）、各形态收口契约（§5）、触发（§6）、降级（§9）、调用骨架（§10）。

## 执行步骤

### Step 1: 定形态

**形态与措辞映射的单一来源是 `CONSULT-GUIDE.md` §2「形态选择」**（3 协作形态 panel / debate / refine[two-way|one-way] + direct 单声旁路，含「只用 X」→ direct 旁路分流）——本文件不复述映射表，按 §2 判定即可。

- 按 `mode=` 入参选形态（refine 再按 `--direction` 或措辞分 two-way|one-way）；无显式 mode 则按 §2 措辞自动判定，**显式 mode 优先**。
- **命中 `direct` 旁路**（"只用 X / 让 X 分析"）→ 走文末「旁路 · direct」小节，**早退结束，不进后续步骤**。
- 判不准就按 `panel`，并提示用户"按 panel 走，要辩论/精炼请加 mode=debate|refine"。
- 指定 provider 措辞（"用 X 一起讨论"）→ 把对应席位 provider 覆盖为 X（CONSULT-GUIDE §6 分流）。

### Step 2: 触发与形态适配（CONSULT-GUIDE §6）

- 取入参议题（无参则取当前对话焦点）。手动 `/to-consult` 即视为显式要求，直接进 Step 3；但能查代码/文档直接答的低风险问题，先告知"这个不必会诊"。
- **形态适配检查**：debate 须二元对立议题（非对立提示换 panel/refine）；refine `one-way`（质检）须有"待审材料/草稿"（无则先用别的形态或 `two-way` 产出）。

### Step 3: 摘录自包含上下文

把议题相关背景 + 待决问题 + 相关架构决策（如有）摘录成一段**自包含 context**（角色据此判断，不自行漫游全仓）。

### Step 4: 探测宿主 + 取外部声音池

探测当前宿主（claude / cursor / codex），读 `.env.toml` 的 `[to-consult.external_voices][host]` 取池（Step 1 有覆盖则用覆盖值）。池里 `[0]`/`[1]` 充当 debate 正/反方、refine ext0/ext1（two-way=A/B、one-way=生成/质检）；panel 形态则全部当外部视角。

### Step 5: 按形态编排（CONSULT-GUIDE §3 §10）

**先建留痕会话**（强制，§7）：编排前调一次 `consult_log.py start` 取任务名 `$TASK`，本次会诊后续所有脚本调用都带 `--task "$TASK"`（脚本据此把请求+生响应落到同一目录）：

```bash
TASK=$(uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/consult_log.py" start \
  --slug <议题slug> --mode <panel|debate|refine> \
  --trigger "<启动提示词/触发原话>" --host <claude|codex|cursor> --models "<席位→模型清单>")
```

- **panel**：宿主 persona 批（Claude Code 走 `Workflow({scriptPath: "${CLAUDE_PLUGIN_ROOT}/scripts/panel.js", args})`、其它宿主主会话自扮演）‖ 外部视角批（`Bash` 调 `cli.py` 池里每个 provider，带 `--task "$TASK" --mode panel --role 外部视角`）并发出卡。
- **debate / refine**：`Bash` 调 `orchestrate.py`（带 `--task "$TASK"`）一次性**确定性**跑完外部底座多步拓扑（不靠主会话逐步自觉），拿结构化 JSON（`steps` 含各步 text/error；refine 带 `direction`）：
  ```bash
  uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/orchestrate.py" debate --task "$TASK" --pro  <ext0> --con  <ext1> "<议题>" [--context …] [--file …]
  uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/orchestrate.py" refine --task "$TASK" --ext0 <ext0> --ext1 <ext1> "<任务>" --direction two-way|one-way [--context …] [--file …] [--skip-gen]
  ```
  角色 provider 取 `external_voices[host]` 两席。refine `two-way`=双声互评合并、`one-way`=单向质检修订（`--skip-gen` 仅 one-way）。脚本跑到收口前即止、不做门控决策；外部各声的请求+生响应由脚本**自动留痕**（§7）。

某步 `error`/`skipped` → 按 CONSULT-GUIDE §9 降级（外部不足用宿主底座补位，收口角色恒=主裁）。

### Step 6: 主裁收口（CONSULT-GUIDE §5）

当前宿主主模型按形态契约收口，**摆矛盾不调和**：panel→综合（共识/分歧/盲区/结论）；debate→裁决（置信度/胜负/逐对比较/建议/风险）；refine `two-way`→合并（终稿+来源标注+差异）；refine `one-way`→修订（修订版+质检报告）。

### Step 7: 收尾（写收口留痕 + 小结）

- **把主裁收口结论写进留痕**（强制，§7）：主裁按 §6 收口后，经脚本把结论追写进本会话目录（正文走 stdin）：
  ```bash
  printf '%s' "<主裁收口结论全文>" | uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/consult_log.py" verdict --task "$TASK" --mode <同 start 的 mode>
  ```
  至此本次会诊全程（启动模式 / 模型 / 启动提示词 / 命令行或 API 请求 / 外部生响应 / 主裁结论）留痕在宿主项目 `.consult-cache/to-consult/$TASK/session.md`。注：panel 宿主 persona 卡因 `panel.js` 是 Workflow 不能写文件，**不在留痕内**（§7 已知限制）。
- 收口结果小结给用户，提示下游：要把结论审问落文件 / 综合成 PRD，交宿主项目对应的下游 skill（如已安装）。

---

### 旁路 · direct（单声部直问，非协作形态）

> 不是流水线步骤，是 Step 1 的**早退分支**：用户点名"只用 X"时跳过整套协作、借单个底座看一眼。完整定义见 CONSULT-GUIDE §2.4。

主会话直接走 Bash 调指定模型并 relay（同样先 `start` 取 `$TASK` 留痕）：

```bash
TASK=$(uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/consult_log.py" start --slug <议题slug> --mode direct \
  --trigger "<启动提示词/触发原话>" --host <host> --models "<X>")
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider <X> --task "$TASK" --mode direct [--file <文档路径> …] "<§4 角色 prompt 或用户原始问题>"
```

- 分析文档用 `--file`（cli.py 读出嵌入，所有 transport 通用，qwen 这类纯 API 也适用）。
- 答案**原样转述** + 一句"这是 X 单方观点、未经多模型交叉验证；要摆矛盾压测走 panel/debate"。
- 失败/超时按 §9 如实告知，**不降级**到别的声音（点名即排他）。direct 无主裁收口，故留痕只含该次请求+生响应（cli.py 自动落）；**产出仍不落文档。**

## 注意事项

- **产出不落文档、不改代码**——这是协作引擎，产出是素材，落地由下游 skill 或用户决定；但**过程素材强制留痕**到宿主项目 `.consult-cache/to-consult/<任务名>/`（§7），便于追溯外部模型那次不可复现的输出。
- 会诊是增益不是依赖：任一席位或宿主批挂掉都按 `CONSULT-GUIDE §9` 降级回单模型，不阻断。
- 触发要克制（§6）：低风险、能查就答的问题不必会诊，避免空烧多模型额度；形态别越级（简单问题别上 debate）。
- 角色的强制对立 lens / 立场不可松绑成"全面评价"，否则退化为同质独白（§1）。
