# ai_client — 多模型调用层（插件内独立模块）

把"调一个外部模型、拿回一段文本"封装成统一契约，供会诊（to-consult）等上层工具调用。
本目录是 `agent-plugin` 插件的内部模块，**完全独立**：不依赖任何宿主项目目录结构，可整目录单独验证。

## 设计要点

- **统一契约**：`Provider.ask(prompt) -> str`。上层只认这个，不关心底下是 CLI 子进程还是 HTTP API。
- **四种 transport**（`type` 字段决定）：
  | type | 模型 | key | 封装 |
  |---|---|---|---|
  | `claude-cli` | Claude（opus/sonnet…） | 复用 Claude Code 登录态，零 key | `claude -p --permission-mode plan`（print 只读） |
  | `codex-cli` | GPT 系 | 复用 ChatGPT 登录态，零 key | `codex exec --sandbox read-only --ephemeral --ignore-user-config --ignore-rules` |
  | `cursor-cli` | gpt-5 / sonnet-4 / sonnet-4-thinking … | 复用 Cursor 登录态，零 key | `cursor-agent -p --mode ask`（只读问答） |
  | `openai-compat` | 任意 OpenAI 兼容厂商（OpenAI / DeepSeek / ollama / qwen …） | `.env.toml` 填 | httpx → `/v1/chat/completions` |
- **CLI transport 一律只读**：会诊角色是纯讨论，绝不让外部 agent 改文件或跑命令（`--permission-mode plan` / `read-only` 沙箱 / `--mode ask`）。
- **claude-cli 的用途**：非 Claude 宿主（Codex / Cursor）下让 Claude 当外部盲区声音——对称补全 codex / cursor，使会诊在任何宿主都能跨底座互补（见 CONSULT-GUIDE §8）。
- **依赖隔离**：`cli.py` 头部 PEP 723 声明 `httpx`，`uv run` 自动建隔离环境。**不污染系统 python**。

## 文件

| 文件 | 职责 |
|---|---|
| `cli.py` | 单声入口（PEP 723 声明 httpx）；`--provider <id> --task <t> "<prompt>"` → stdout 文本（panel 外部批 / direct 旁路），每次调用经 consult_log 留痕 |
| `orchestrate.py` | 多形态编排入口（PEP 723）；`debate / refine`（refine 含 `--direction two-way\|one-way`）子命令确定性跑外部底座多步拓扑 → stdout 结构化 JSON；每步外部调用自动留痕（收口=宿主主裁留主会话，见 CONSULT-GUIDE §3 §10） |
| `providers.py` | `Provider` 基类 + `ClaudeCli` / `CodexCli` / `CursorCli` / `OpenAICompat` 四实现 + `build_provider` 工厂；另暴露 `request_repr`（脱敏请求描述，留痕用） |
| `consult_log.py` | 会诊留痕单一写入点（纯标准库）；`start` / `verdict` 子命令 + `record_call` 库函数 → 写 `<宿主项目根>/.consult-cache/to-consult/<任务名>/session.md`（CONSULT-GUIDE §7.2） |
| `config.py` | 纯标准库 `tomllib` 读 `.env.toml`（缺失引导复制模板） |
| `example.env.toml` | 配置模板（进 git，key 留空） |
| `.env.toml` | 实际配置（**gitignore**，含 key） |

## 配置（`.env.toml` 位置）

插件目录是共享只读资产，**密钥不应塞进去**。`config.py` 按以下优先级解析配置位置：

1. 环境变量 `CONSULT_ENV_TOML`（显式指定路径）
2. `$CLAUDE_PLUGIN_DATA/.env.toml`（Claude Code 注入的插件持久数据区，跨版本更新保留）
3. 脚本同目录 `.env.toml`（兜底，仅本地开发用）

```bash
# 推荐方式：放到 Claude 插件数据区
cp "${CLAUDE_PLUGIN_ROOT}/ai_client/example.env.toml" "${CLAUDE_PLUGIN_DATA}/.env.toml"
# 编辑：CLI transport（claude/codex/cursor）零 key 即用；API transport 填 base_url + api_key

# 或显式指定
export CONSULT_ENV_TOML=/path/to/your/.env.toml
```

## 留痕落点

`consult_log.py` 的留痕根目录解析顺序：

1. `CONSULT_CACHE_DIR`（显式指定）
2. `CLAUDE_PROJECT_DIR/.consult-cache/to-consult/`（宿主项目根，Claude Code 注入）
3. `<cwd>/.consult-cache/to-consult/`（兜底）

宿主项目把 `.consult-cache/` 加进自己的 `.gitignore` 即可。

## 用法

```bash
# 由会诊主会话走 Bash 调用；也可手动验证
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider claude "用一句话说明 CQRS 适合什么场景"
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider cursor "同上"
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider codex  "同上"
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider deepseek --timeout 60 "同上"

# --file（可重复）：由 cli.py 读出文件内容嵌入 prompt 前部，所有 transport 通用。
# openai-compat（纯 API，如 qwen）自身读不了文件，分析文档必须走这里。
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider qwen --file path/to/doc.md "分析这份文档的风险"
```

多形态编排（debate / refine；输出结构化 JSON，收口留主会话）：

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/orchestrate.py" debate --pro  codex --con  cursor "用 SSE 还是 WebSocket 做实时推送"
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/orchestrate.py" refine --ext0 codex --ext1 cursor --direction two-way "给历史日报列表设计分页方案"
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/orchestrate.py" refine --ext0 codex --ext1 cursor --direction one-way --skip-gen --file draft.md "质检这份草稿"
```

留痕（强制，CONSULT-GUIDE §7.2）：会诊主会话编排前先 `start` 取任务名，各调用带 `--task`，收口后 `verdict` 写结论；外部各声的请求+生响应由 cli/orchestrate 自动落，脱敏（API 不记 key、prompt 占位）、非阻塞（写盘失败不中断会诊）：

```bash
TASK=$(uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/consult_log.py" start --slug demo --mode panel \
  --trigger "压测这个方案" --host claude --models "codex/cursor")
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider cursor --task "$TASK" --mode panel --role 外部视角 "回 OK 两个字"
printf '综合结论…' | uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/consult_log.py" verdict --task "$TASK" --mode panel
# → <宿主项目根>/.consult-cache/to-consult/$TASK/session.md
```

测试（mock caller，不碰真实 provider / httpx）：

```bash
cd "${CLAUDE_PLUGIN_ROOT}/ai_client" && python3 -m pytest __tests__ -q
```

退出码：`0` 成功（文本进 stdout）/ `1` 调用失败 / `2` 配置或参数错误（含文件缺失，信息进 stderr）。

## 验证

```bash
# 1. uv 读 PEP723 + 装 httpx + import 链
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --help

# 2. 零 key CLI transport 端到端（会真实调模型、耗登录态额度）
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/cli.py" --provider cursor "回 OK 两个字"
```

## 在会诊中的位置

会诊是**宿主无关的多形态协作引擎**：主裁 = 当前宿主主模型。「宿主底座批」在 Claude Code 走 `Workflow`（model 限 Claude）、其它宿主主会话自扮演；「外部声音批」由主会话走 Bash 调本工具，按 `[to-consult.external_voices][host]` 取**非宿主底座**的跨厂商声音（排除同底座）。

- **panel 形态**：外部批走 `cli.py`（每 provider 一张视角卡），宿主批走 `panel.js` / 自扮演，主裁综合。
- **debate / refine 形态**：外部底座的多步拓扑（立论→反驳 / 生成→互评 / 生成→质检）走 `orchestrate.py` **确定性编排**成结构化 JSON；收口（裁决/合并/修订 = 宿主主裁）留主会话。

详见插件根目录 `CONSULT-GUIDE.md` §0 §2 §3 §8 §10。
