# agent-plugin

跨项目共享的 Claude Code 插件，目前包含两个 skill + 一套宿主无关的多模型会诊引擎。

> 设计取向：**宿主无关 + 项目无关**——不假设宿主是哪个 CLI（Claude Code / Codex / Cursor），不假设宿主项目有特定目录结构。引擎打底，skill 在上层组装。

## 提供什么

- **`/agent-plugin:to-consult`** — 多模型会诊**手动入口**：召集多个角色（含跨厂商模型）按某种协作拓扑出观点、当前宿主主模型收口。机制规范见 `skills/to-consult/SKILL.md`（入口 + 形态判定 + 流程）+ 同目录 `consult-common.md`（共享规范）+ `mode-{panel,debate,refine,direct}.md`（形态拓扑 / 角色 / 收口契约的单一来源）。
- **`/agent-plugin:to-grill`** — **逐问审问**引擎：grill 式一次一个问题把模糊想法/方案/决策树逼清楚；审问已有草稿文件会回写决策段，审问对话不落盘。命中真权衡/高风险时内部点燃 to-consult。
- **`scripts/panel.js`** — Claude Code 宿主下 panel persona 批的 Workflow fan-out。
- **`ai_client/`** — 独立 Python 模块（cli / orchestrate / providers / consult_log，PEP 723 + uv）。

会诊引擎的 3 种协作形态 + 1 个单声旁路：

| 形态 | 何时用 | 拓扑 |
|---|---|---|
| `panel` | 盲区互补、求多角度 | 多角色并行独立出卡 → 主裁综合 |
| `debate` | 二元对立选型 | 正/反方多步辩论 → 主裁裁决 |
| `refine` (`two-way`) | 双向互评精炼 | A/B 双初版 + 互评 → 主裁合并 |
| `refine` (`one-way`) | 单向质检修订 | 初版 + 质检 → 主裁修订 |
| `direct` | 用户点名"只用 X" | 单底座直问 + 原样转述（非协作） |

机制全文见 `skills/to-consult/SKILL.md`（入口 + 形态判定 + 流程）+ 同目录 `consult-common.md`（共享规范）+ `mode-{panel,debate,refine,direct}.md`（形态专属）。

## 安装（Claude Code）

本仓库同时是**插件**（`.claude-plugin/plugin.json`）和**单插件市场**（`.claude-plugin/marketplace.json`，把 `./` 注册为 `agent-plugin`），所以安装走标准的"加市场 → 装插件"两步。命令均在 Claude Code 会话内输入。

```text
# 1. 添加市场（marketplace）—— GitHub 简写
/plugin marketplace add shper/agent-plugin

#    私有库或简写不通时，用完整地址（任选其一）：
#    /plugin marketplace add git@github.com:shper/agent-plugin.git
#    /plugin marketplace add https://github.com/shper/agent-plugin.git

# 2. 安装插件（格式：插件名@市场名，二者同名）
/plugin install agent-plugin@agent-plugin

# 3. 验证
/plugin list
#    然后在任意项目中：/agent-plugin:to-consult <议题>
```

> 本地开发 / 未 push 时，第 1 步可直接指向工作副本：
> `/plugin marketplace add /Users/shper/Documents/11_AI/agent-plugin`

### 更新

仓库推了新版本后：

```text
/plugin marketplace update agent-plugin   # 拉取市场最新清单
/plugin install agent-plugin@agent-plugin # 重装到新版本
```

## 安装（Codex）

Codex 有与 Claude Code 几乎对称的插件体系，本仓库已同时是 **Codex 插件**（`.codex-plugin/plugin.json`，声明 `"skills": "./skills/"`）和 **Codex 单插件市场**（`.agents/plugins/marketplace.json`，把 `./` 注册为 `agent-plugin`）。同样走"加市场 → 装插件"两步，命令在 Codex 内输入。

```text
# 1. 添加市场（GitHub 简写）
codex plugin marketplace add shper/agent-plugin

#    私有库或简写不通时，用完整 git 地址：
#    codex plugin marketplace add https://github.com/shper/agent-plugin.git
#    本地开发 / 未 push：codex plugin marketplace add ./

# 2. 装插件：在 Codex 里输入 /plugins 打开插件列表，选 agent-plugin 安装
#    （若你的 Codex 版本支持 CLI 安装：codex plugin install agent-plugin）

# 3. 重启 Codex（或开新会话）让 skill 生效，然后：/to-consult <议题>
```

> **skill 怎么找到 ai_client**：`PLUGIN_ROOT` / `PLUGIN_DATA`（及兼容别名 `CLAUDE_PLUGIN_ROOT` / `CLAUDE_PLUGIN_DATA`）**只在插件 hook 命令的环境里**可靠存在，skill 触发的普通 Bash 里通常为空——不靠它们定位。真正的依据是：安装产物全在一个目录内（Codex 默认 `~/.codex/plugins/cache/<市场>/<插件>/<版本>/`，`ai_client/`、`scripts/` 与 `skills/` 同根），且宿主会把**本 skill 的安装目录**告诉主模型，主会话据此**上溯两级**即得插件根。故 skill 里写成 `ROOT="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-<本 skill 目录上两级>}}"` 再 `uv run "$ROOT/ai_client/…"`，无需手工配路径（机制详见 `skills/to-consult/consult-common.md §3`）。

## 安装后配置 ai_client（多模型引擎）

`/plugin install` 只分发 skills / commands / 脚本等清单内容，**不**装 Python 依赖、**不**配 key。`ai_client/` 在第一次被会诊调用前需要完成下面两步（按需）。

### 前置：Python 运行环境（uv）

`ai_client/` 用 [uv](https://docs.astral.sh/uv/) + PEP 723 自管依赖——脚本头部声明 `httpx`，`uv run` 自动建隔离环境，**不污染系统 Python**。只需装一次 uv：

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# 或 Homebrew：brew install uv

# 自检（在插件根目录下执行；应能打印 help 并自动拉起 httpx）
uv run ai_client/cli.py --help
```

`ai_client/` 等脚本都在插件根下。**插件根变量**（Claude Code `$CLAUDE_PLUGIN_ROOT` / Codex `$PLUGIN_ROOT`）**只在插件 hook 命令的环境里**可靠存在，skill 触发的普通 Bash 里通常为空——skill 内由主会话据"本 skill 安装目录上溯两级"得插件根（详见 `skills/to-consult/consult-common.md §3`）；手动自检直接 `cd` 进插件根目录跑相对路径即可。

### 外部模型 key（仅 OpenAI 兼容厂商需要）

CLI transport（`claude` / `codex` / `cursor`）**零 key 即用**——复用对应工具的本地登录态。
仅当你想加 OpenAI 兼容厂商（DeepSeek / qwen / ollama / GPT-4o…）作为外部声音时，才需要配 `.env.toml`：

```bash
# 推荐：显式指定一个你自己的路径，跨宿主/跨版本都稳（数据区变量在普通 shell 里为空，别依赖）
mkdir -p ~/.config/agent-plugin
cp <插件根>/ai_client/example.env.toml ~/.config/agent-plugin/.env.toml
$EDITOR ~/.config/agent-plugin/.env.toml          # 填 base_url + api_key
export CONSULT_ENV_TOML=~/.config/agent-plugin/.env.toml   # 写进 shell profile 持久生效
```

`config.py` 解析配置位置的优先级：`CONSULT_ENV_TOML` > 数据区 `.env.toml`（`$CLAUDE_PLUGIN_DATA` / `$PLUGIN_DATA`，**仅 hook 环境可靠**）> 脚本同目录 `.env.toml`（兜底）。因数据区变量在 skill 的普通 Bash 里通常为空，**手动配 key 走 `CONSULT_ENV_TOML` 最稳**；不设时回退到已安装的 `ai_client/.env.toml`（即插件根下，仍跨版本被覆盖，仅本地开发凑合用）。插件目录是共享只读资产，正式 key **别塞进去**。

`.env.toml` 里的 `[to-consult.external_voices]` 决定每个宿主对应取哪些外部声音；详见模板注释、`ai_client/README.md` 与 `skills/to-consult/consult-common.md` §8。

## 留痕落点

每次会诊全程**强制留痕**到宿主项目的 `.consult-cache/to-consult/<任务名>/session.md`（脚本据宿主项目根定位：Claude Code 注入的 `CLAUDE_PROJECT_DIR` > cwd 兜底；Codex 不注入项目根变量，靠 cwd——故调脚本时别 `cd` 离开项目）。在你常用的项目里把 `.consult-cache/` 加进 `.gitignore` 即可。

显式覆盖：`export CONSULT_CACHE_DIR=/path/to/somewhere`。

## 跨工具接入约定

引擎本身**宿主无关**——主裁恒等于当前宿主主模型；外部声音按 `[to-consult.external_voices][host]` 取池。安装方式按宿主有无插件体系分两类：

- **Claude Code / Codex**：都有原生插件体系，直接按上面「安装（Claude Code）」「安装（Codex）」两节走市场安装；skill 内脚本路径由主会话据"本 skill 安装目录上溯两级"得插件根解析（`CLAUDE_PLUGIN_ROOT` / `PLUGIN_ROOT` 仅 hook 环境可靠，非依赖项），无需手工配路径。
- **Cursor**：暂无统一插件标准、没法一键装。在 `.cursorrules` 或项目 rules 引用本仓库的 `skills/to-consult/SKILL.md` + 同目录 `consult-common.md` + `mode-*.md` 当"会诊操作手册"；脚本调用用绝对路径或先 `export PLUGIN_ROOT=<本仓库绝对路径>`（skill 的 `${CLAUDE_PLUGIN_ROOT:-$PLUGIN_ROOT}` 即可命中）。
- 三个工具的登录态彼此独立，但 `ai_client/` 通过 CLI 子进程复用各自登录态——任何一个工具当宿主，另两个都能作为外部声音。

## 手动验证

```bash
# 1. Python 单测（mock caller，不碰真实 provider，无需 httpx）
cd /Users/shper/Documents/11_AI/agent-plugin/ai_client
python3 -m pytest __tests__ -q

# 2. uv + PEP723 依赖链
uv run /Users/shper/Documents/11_AI/agent-plugin/ai_client/cli.py --help

# 3. 留痕落到宿主项目根（不写到插件目录）
CLAUDE_PROJECT_DIR=/tmp/demo uv run /Users/shper/Documents/11_AI/agent-plugin/ai_client/consult_log.py \
  start --slug t --mode panel --trigger x --host claude --models codex
ls /tmp/demo/.consult-cache/to-consult/

# 4. 零 key 端到端（真实调登录态、耗额度，按需）
uv run /Users/shper/Documents/11_AI/agent-plugin/ai_client/cli.py --provider cursor "回 OK 两个字"
```

## 目录结构

```
agent-plugin/
├── .claude-plugin/             # Claude Code 插件清单 + 单插件市场
│   ├── plugin.json
│   └── marketplace.json
├── .codex-plugin/              # Codex 插件清单（skills: ./skills/）
│   └── plugin.json
├── .agents/plugins/            # Codex 单插件市场清单
│   └── marketplace.json
├── skills/
│   ├── to-consult/
│   │   ├── SKILL.md            # 会诊入口 + 形态判定 + 8 步执行流程（精简引导）
│   │   ├── consult-common.md   # 跨形态共享规范（宿主无关 / 底座 / 物理架构 / 触发 / 落盘 / 外部接入 / 降级）
│   │   ├── mode-panel.md       # 形态：并行独立盲区互补（拓扑 / 角色卡 / 收口契约 / 编排骨架）
│   │   ├── mode-debate.md      # 形态：正反辩论 + 裁判裁决
│   │   ├── mode-refine.md      # 形态：精炼（two-way 互评 / one-way 质检）
│   │   └── mode-direct.md      # 旁路：单声直问（非协作形态）
│   └── to-grill/SKILL.md
├── scripts/
│   └── panel.js                # Claude Code Workflow 脚本（panel persona 批）
├── ai_client/                  # 独立 Python 模块（uv + PEP 723）
│   ├── cli.py
│   ├── orchestrate.py
│   ├── providers.py
│   ├── consult_log.py
│   ├── config.py
│   ├── example.env.toml
│   ├── README.md
│   └── __tests__/
├── README.md                   # 本文件
└── .gitignore
```

## 许可

MIT
