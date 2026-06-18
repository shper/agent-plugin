# agent-plugin

跨项目共享的 Claude Code 插件，目前包含两个 skill + 一套宿主无关的多模型会诊引擎。

> 设计取向：**宿主无关 + 项目无关**——不假设宿主是哪个 CLI（Claude Code / Codex / Cursor），不假设宿主项目有特定目录结构。引擎打底，skill 在上层组装。

## 提供什么

- **`/agent-plugin:to-consult`** — 多模型会诊**手动入口**：召集多个角色（含跨厂商模型）按某种协作拓扑出观点、当前宿主主模型收口。
- **`/agent-plugin:to-grill`** — **逐问审问**引擎：grill 式一次一个问题把模糊想法/方案/决策树逼清楚；审问已有草稿文件会回写决策段，审问对话不落盘。命中真权衡/高风险时内部点燃 to-consult。
- **`CONSULT-GUIDE.md`** — 会诊机制规范（形态 / 角色 / 收口契约的单一来源）。
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

机制全文见 `CONSULT-GUIDE.md`。

## 安装（Claude Code）

```bash
# 在 Claude Code 里：
/plugin marketplace add /Users/shper/Documents/11_AI/agent-plugin
/plugin install agent-plugin@agent-plugin

# 验证：
/plugin list
# 在任意项目中 /agent-plugin:to-consult <议题>
```

如果以后 push 到远程 git 仓库，把上面的本地路径换成 `git@github.com:...` 即可。

## 配置外部模型（一次性）

CLI transport（`claude` / `codex` / `cursor`）零 key 即用——复用对应工具的本地登录态。
仅当你想加 OpenAI 兼容厂商（DeepSeek / qwen / ollama / GPT-4o…）作为外部声音时才需配置 API key。

```bash
# 推荐：放到 Claude 注入的插件持久数据区（跨版本更新保留）
cp "${CLAUDE_PLUGIN_ROOT}/ai_client/example.env.toml" "${CLAUDE_PLUGIN_DATA}/.env.toml"
$EDITOR "${CLAUDE_PLUGIN_DATA}/.env.toml"

# 或显式指定
export CONSULT_ENV_TOML=/path/to/your/.env.toml
```

`.env.toml` 里的 `[to-consult.external_voices]` 决定每个宿主对应取哪些外部声音；详见模板注释与 `CONSULT-GUIDE.md` §8。

## 留痕落点

每次会诊全程**强制留痕**到宿主项目的 `.consult-cache/to-consult/<任务名>/session.md`（脚本据 `CLAUDE_PROJECT_DIR` 自动定位）。在你常用的项目里把 `.consult-cache/` 加进 `.gitignore` 即可。

显式覆盖：`export CONSULT_CACHE_DIR=/path/to/somewhere`。

## 跨工具（codex / cursor）接入约定

引擎本身**宿主无关**——主裁恒等于当前宿主主模型；外部声音按 `[to-consult.external_voices][host]` 取池。但 codex / cursor 没有统一的"插件"标准，没法一键安装。建议：

- **Codex**：在你的全局 `AGENTS.md` 或项目 `AGENTS.md` 引用本仓库的 `CONSULT-GUIDE.md` + `skills/to-consult/SKILL.md` 路径，把它们当作"会诊操作手册"喂给主会话；脚本调用走 `uv run /Users/shper/Documents/11_AI/agent-plugin/ai_client/...`（绝对路径或自己软链）。
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
│   ├── to-consult/SKILL.md
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
├── CONSULT-GUIDE.md            # 机制规范
├── README.md                   # 本文件
└── .gitignore
```

## 许可

MIT
