---
title: 多模型会诊共享规范（跨形态机制）
parent: SKILL.md
updated: 2026-06-18
scope: 多模型会诊的跨形态共享机制——宿主无关三要素 / 角色与底座分配 / 物理架构总原理 / 触发纪律 / 落盘边界 / 外部模型接入 / 降级。被 SKILL.md 与各 mode-*.md 引用。
related:
  - skills/to-consult/SKILL.md
  - skills/to-consult/mode-panel.md
  - skills/to-consult/mode-debate.md
  - skills/to-consult/mode-refine.md
  - skills/to-consult/mode-direct.md
  - ai_client/README.md
---

# 多模型会诊共享规范

> 跨形态共享的机制规范：宿主无关三要素、底座分配、物理架构原理、触发纪律、落盘边界、外部接入、降级。
> 形态判定与 8 步执行流程见 `./SKILL.md`；各形态专属拓扑、角色卡、收口契约、编排骨架见 `./mode-<形态>.md`。

---

## 0. 宿主无关的三要素

| 要素 | 定义 | 落点 |
|---|---|---|
| **主裁（收口者）** | 当前宿主的主模型（Claude Code→Opus / Codex→codex 主模型 / Cursor→cursor 主模型）。运行时主会话自知身份，无需配置。承担各形态的收口（综合 / 裁决 / 合并 / 修订）。 | mode-*.md「收口契约」 |
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

panel 形态的 3 个宿主 persona 强制 lens 见 `./mode-panel.md` §2（架构红队 / 价值质询 / 唱反调者）；其它形态不用 persona lens，用拓扑角色立场（mode-debate.md §3 / mode-refine.md §4）。

---

## 3. 物理架构总原理

任一形态物理上都由**宿主底座批 + 非宿主底座外部批**组成，主会话编排并收口。

> **插件根 `$ROOT` 解析（宿主无关，下面所有脚本路径都相对它）**：`$CLAUDE_PLUGIN_ROOT`（Claude Code）/ `$PLUGIN_ROOT`（Codex）这两个变量**只在插件 hook 命令的环境里可靠存在**，skill 触发的普通 Bash 调用里通常**为空**——不能假定它们有值。根的权威来源是**主会话被告知的本 skill 安装目录**：`ai_client/`、`scripts/` 在插件根、比 skill 目录高两级（布局 `<插件根>/skills/<name>/SKILL.md`）。解析顺序——变量有值就用，否则据本 SKILL.md 所在目录**上溯两级**代入插件根绝对路径：
>
> ```bash
> # 变量在 hook 外常为空 → 主会话把末项换成「本 skill 目录的上两级」的绝对路径
> ROOT="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-<插件根绝对路径=本 SKILL.md 目录上两级>}}"
> uv run "$ROOT/ai_client/…"
> ```
>
> **切勿 `cd` 进 `$ROOT`**——留痕脚本据 cwd / `CLAUDE_PROJECT_DIR` 定位宿主项目，cd 会把缓存误写进插件目录（Codex 不注入项目根变量，更依赖 cwd）。配置则与插件目录解耦：`ai_client/config.py` 统一读 `~/.agent-plugin/env.toml`（缺失自动从模板初始化），不依赖任何插件环境变量。
> `panel.js` 走 Claude Code 的 `Workflow` 工具（工具参数不是 shell 路径，不能用 `$ROOT`），故其 `scriptPath` 仍写 `${CLAUDE_PLUGIN_ROOT}/scripts/panel.js`——它本就只在 Claude Code 宿主下被调用。

| 批次 | 派发者 | 机制 |
|---|---|---|
| **宿主底座批** | 主会话 | **按宿主探测派发**：Claude Code 有 `Workflow` → panel 形态走 `${CLAUDE_PLUGIN_ROOT}/scripts/panel.js` 确定性 `parallel()` fan-out（每角色一个 agent，schema 强制角色卡）；Codex / Cursor **无 `Workflow`** → 主会话**串行自扮演**（lens / 立场照旧强制，质量等价只是不并行）。 |
| **非宿主底座外部批** | 主会话 | **panel 形态**：`Bash` 调 `uv run "$ROOT/ai_client/cli.py" --provider <id>` 取各外部视角（池里每个 provider，可并发）。**debate/refine 形态**：`Bash` 调 `uv run "$ROOT/ai_client/orchestrate.py" <mode> …` 由脚本**确定性编排**外部底座的多步拓扑，输出结构化 JSON 中间产物（`steps` 含各步 text/error）。 |

**为何 debate/refine 的拓扑走 `orchestrate.py`、不进 panel.js**：① 两形态**跨底座**——`Workflow.agent()` 是 Claude Code 专属且 `model` 只能是 Claude，调不了外部底座；② 它们有**串行依赖**（立论→反驳 / 生成→互评/质检），靠主会话「自觉」逐步调模型不可复现。故由 `orchestrate.py`（Python on `ai_client`，asyncio）把外部底座多步拓扑**确定性编排**成结构化 JSON；`panel.js` 仍只服务 **panel 形态的并行宿主 persona 批**。**收口（裁决/合并/修订 = 宿主主裁）调不了主会话自己，留主会话**——与 panel.js 把综合留主会话同一分工。脚本本身**不做门控决策**（门控属收口者），只输出素材（辩论记录 / 双初版+互评 / 初版+质检评分）。

> 确定性 fan-out 用 Workflow，主会话持判断与收口权。panel.js 同样**不**落盘、不 commit、不 Edit，只产角色素材。

各形态的物理架构细节（哪批走哪个脚本、收口在哪）见各 mode 文件「物理架构」节。

---

## 6. 触发纪律（防滥用烧钱）

会诊引擎 **不默认开**，命中下列之一才点燃：

- **真权衡**：某决策出现 ≥2 个可行方案且取舍不明（→ 倾向 debate）。
- **高风险**：触及写入 / 认证 / 金额，或要动项目已记录的重大架构决策（如有）。
- **显式要求**：用户说"会诊 / 压测 / 听听别的模型 / 辩论 / 互评 / 质检"。

**不点燃**：术语对齐、能查代码/文档直接回答的、低风险默认决策。

**形态适配检查**：debate 须二元对立议题（非对立提示换 panel/refine）；refine `one-way`（质检）须有"待审材料/草稿"（无材料则先用别的形态或 `two-way` 产出）。

**用户指定模型（措辞分流）**——点名某个已配 provider 时按措辞分两路（id 须在 `~/.agent-plugin/env.toml [providers.*]`，未配则告知可选项、不臆造）：

| 措辞 | 路由 | 行为 |
|---|---|---|
| "**只用** X / 单独让 X / 让 X 分析这个问题/文档" | direct 旁路（mode-direct.md） | 跳过多角色 + 收口，主会话直接调 X，转述其答案 |
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
- **三条写入路径**：① 主会话编排前 `start` 建头部（SKILL.md 执行步骤 Step 5）；② `cli.py`（panel 外部批 / direct）与 `orchestrate.py`（debate/refine 每步）调用边界**自动**记请求+生响应；③ 主会话收口后 `verdict` 追写收口结论（SKILL.md 执行步骤 Step 8，正文走 stdin）。
- **脱敏（三层，兜底非保证）**：①API 请求**绝不含 api_key**、不含 messages 正文；②**CLI prompt 一律走 stdin、不进 argv**（命令行只留 `<prompt:N字·stdin>` 占位）——杜绝 prompt 出现在系统进程表 / 审计日志 / shell history；③落盘的 **prompt/响应正文**经 `_redact` 对常见密钥/令牌/私钥（sk-/ark-/AKIA/Bearer/PEM/显式赋值）做占位替换。注意这是**兜底**：保守匹配、可能漏放，**敏感议题是否会诊仍由用户自行判断**，缓存目录仍须 gitignore。
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
| `openai-compat` | OpenAI / DeepSeek / ollama / qwen 等任意兼容厂商 | `env.toml` 填 |

**外部声音池按宿主取**：`~/.agent-plugin/env.toml` 的 `[to-consult.external_voices]` 为每个宿主声明一组 provider（**应**排除同底座、且各席尽量异厂商——但这只是约定，故另有 C4 运行时检测兜底，见下）：

```toml
[to-consult.external_voices]
claude = ["codex", "cursor"]     # 宿主 = Claude Code → 外部用 codex + cursor
codex  = ["claude", "cursor"]    # 宿主 = Codex       → 外部用 claude + cursor
cursor = ["claude", "codex"]     # 宿主 = Cursor      → 外部用 claude + codex
```

主会话据**自身宿主身份**取对应数组：池里 `[0]` / `[1]` 分别充当 debate 正/反方、refine ext0/ext1（two-way=A/B、one-way=生成/质检），panel 形态则全部当外部视角。**用户可显式覆盖**——"用 qwen 一起讨论"即把对应席位换成 `qwen`（§6 分流）。三个 CLI provider 的 `model` 缺省即用各工具**主模型**。

> **跨底座独立性检测（C4，强制·非阻塞）**：取池后由 `independence.py` 静态推断各席的模型族 + 推理网关。**独立性由模型族决定，不由网关决定**——同一聚合网关（ark / OpenRouter）后挂的若是不同组织的模型，盲区天然不同、视角仍独立。故只把**模型族重合**当独立性风险（high）：①外部席与主裁同族、②池内两席同族；**同网关仅作可用性提示（low，不计折扣）**，CLI 默认 model 致族未知亦只是提示。命中 high 即告警，主裁须在收口里如实暴露同源折扣、避免多模型退化成**伪交叉验证背书**（比单模型更危险）。debate/refine 经 `orchestrate.py --host` 自动嵌入 envelope `independence`；panel 由 SKILL.md Step 4 / mode-panel §7.2 显式调 `independence.py`。

主会话调用：

```bash
ROOT="${CLAUDE_PLUGIN_ROOT:-$PLUGIN_ROOT}"   # 变量在 hook 外常为空→主会话据本 skill 目录上两级代入插件根（§3）
uv run "$ROOT/ai_client/cli.py" --provider <provider_id> "<角色 prompt>"
```

**分析/审查文档**时加 `--file`（可重复），由 `cli.py` 读出文件内容嵌入 prompt 前部——所有 transport 通用，尤其 `openai-compat`（纯 API，如 qwen）自身无文件访问能力，必须靠这里读出嵌入：

```bash
uv run "$ROOT/ai_client/cli.py" --provider qwen --file <path/to/doc.md> "<分析指令>"
```

---

## 9. 降级与失败处理

| 情形 | 主会话行为 |
|---|---|
| 宿主无 `Workflow`（Codex / Cursor） | **正常路径**，非降级：panel 形态的宿主 persona 批由主会话**串行自扮演**，外部批照常走 `ai_client` |
| 某个外部席位超时 / 报错 / 未登录 / 无 key | panel：跳过该席少一张卡；**debate/refine：`orchestrate.py` 内确定性补位**——给 `--fallback <宿主底座 provider>`，失败步骤自动改用该底座重试，步骤打 `degraded=True` + `requested` + `note`（"<角色>与收口同底座、未经完全独立第三方"），不再靠主会话读 JSON 后自觉手动补（裁判/合并/修订角色本就=主裁，不另补） |
| 外部只剩 1 个（debate/refine 需 2 对抗角色） | 同上：失败方走 `--fallback` 补位、另一方用外部；envelope 顶层 `degraded` 列出降级步骤供主裁判断同源折扣；收口角色仍=主裁 |
| **对抗双方都降级到同一宿主底座**（envelope `degraded` 含全部对抗席） | 跨底座不变量已破、退化为主裁自辩自裁——主裁**应据 `degraded` 流产并告知**，不出具"伪交叉验证"结论 |
| 收口角色（裁判/合并/修订）失败 | 输出已收集的素材（立论+反驳 / 两初版+互评 / 初版+质检）让用户判断，**不把收口降级到对抗方同实例** |
| 某 persona 角色卡 schema 漂移 | 主会话重派 1 次；仍漂移则按缺席处理 |
| 全部外部 + 补位底座 + 多数宿主角色失败 | 该次协作流产，如实告知用户，回退到主裁单模型继续 |

核心：会诊引擎是**增益**不是依赖——任何一环挂掉都能降级回单模型，不阻断需求流程。
