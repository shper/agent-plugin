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

## 安装后配置 ai_client（多模型引擎）

`/plugin install` 只分发 skills / commands / 脚本等清单内容，**不**装 Python 依赖、**不**配 key。`ai_client/` 在第一次被会诊调用前需要完成下面两步（按需）。

### 前置：Python 运行环境（uv）

`ai_client/` 用 [uv](https://docs.astral.sh/uv/) + PEP 723 自管依赖——脚本头部声明 `httpx`，`uv run` 自动建隔离环境，**不污染系统 Python**。只需装一次 uv：

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# 或 Homebrew：brew install uv

# 自检（应能打印 help 并自动拉起 httpx）
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --help
```

`${CLAUDE_PLUGIN_ROOT}` 由 Claude Code 注入，指向已安装的插件目录；在会诊主会话的 Bash 调用里可直接用。

### 外部模型 key（仅 OpenAI 兼容厂商需要）

CLI transport（`claude` / `codex` / `cursor`）**零 key 即用**——复用对应工具的本地登录态。
仅当你想加 OpenAI 兼容厂商（DeepSeek / qwen / ollama / GPT-4o…）作为外部声音时，才需要配 `.env.toml`：

```bash
# 推荐：放到 Claude 注入的插件持久数据区（跨版本更新保留）
cp "${CLAUDE_PLUGIN_ROOT}/ai_client/example.env.toml" "${CLAUDE_PLUGIN_DATA}/.env.toml"
$EDITOR "${CLAUDE_PLUGIN_DATA}/.env.toml"   # 填 base_url + api_key

# 或显式指定路径
export CONSULT_ENV_TOML=/path/to/your/.env.toml
```

`config.py` 解析配置位置的优先级：`CONSULT_ENV_TOML` > `$CLAUDE_PLUGIN_DATA/.env.toml` > 脚本同目录 `.env.toml`（兜底，仅本地开发）。插件目录是共享只读资产，**别把 key 塞进去**。

`.env.toml` 里的 `[to-consult.external_voices]` 决定每个宿主对应取哪些外部声音；详见模板注释、`ai_client/README.md` 与 `skills/to-consult/consult-common.md` §8。

## 留痕落点

每次会诊全程**强制留痕**到宿主项目的 `.consult-cache/to-consult/<任务名>/session.md`（脚本据 `CLAUDE_PROJECT_DIR` 自动定位）。在你常用的项目里把 `.consult-cache/` 加进 `.gitignore` 即可。

显式覆盖：`export CONSULT_CACHE_DIR=/path/to/somewhere`。

## 跨工具（codex / cursor）接入约定

引擎本身**宿主无关**——主裁恒等于当前宿主主模型；外部声音按 `[to-consult.external_voices][host]` 取池。但 codex / cursor 没有统一的"插件"标准，没法一键安装。建议：

- **Codex**：在你的全局 `AGENTS.md` 或项目 `AGENTS.md` 引用本仓库的 `skills/to-consult/SKILL.md` + 同目录 `consult-common.md` + `mode-*.md` 路径，把它们当作"会诊操作手册"喂给主会话；脚本调用走 `uv run /Users/shper/Documents/11_AI/agent-plugin/ai_client/...`（绝对路径或自己软链）。
- **Cursor**：同理，写进 `.cursorrules` 或项目 rules 即可。
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
├── .claude-plugin/
│   ├── plugin.json
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
