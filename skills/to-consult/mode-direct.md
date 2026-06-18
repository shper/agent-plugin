---
title: direct 旁路（单声部直问，非协作形态）
mode: direct
parent: SKILL.md
updated: 2026-06-18
---

# direct 旁路 — 单声部直问

> **不是协作形态，是引擎的单声旁路（逃生舱）**：用户点名"只用 X / 单独让 X / 让 X 分析"时跳过整套协作、借单个底座看一眼。
> 缺多角色、缺主裁收口——**原样转述即终态**，不在 consult-common §5 收口契约辖内。
> 它放弃了"摆矛盾 / 盲区互补"（引擎的立身之本），要交叉验证就升级回 panel/debate/refine。
> 共享规范（宿主无关 §0 / 底座 §1 / 触发 §6 / 落盘 §7 / 外部接入 §8 / 降级 §9）见 `./consult-common.md`。

---

## 1. 触发与分流（与协作形态的边界）

| 措辞 | 路由 |
|---|---|
| "**只用** X / 单独让 X / 让 X 分析这个问题/文档" | **direct 旁路**（本文件） |
| "**用** X 一起讨论 / 压测 / 让 X **也**看看" | panel / 协作形态，对应席位 provider 覆盖为 X |

显式入参 `mode=direct` 同走 direct（consult-common §6）。`X` 必须在 `~/.agent-plugin/env.toml [providers.*]`，未配则告知可选项、不臆造。

## 2. 拓扑

无拓扑。一次 `cli.py` 调用 → relay → 完。

| 步骤 | 角色 | 底座 |
|---|---|---|
| 1 取问题/文档 | 主会话 | — |
| 2 调用 X | 主会话 → cli.py | 用户点名的单个 provider |
| 3 relay 答案 + 一句话警示 | 主会话 | — |

## 3. 收口

**无主裁收口动作**——原样转述模型答案即终态，不进 consult-common §5 之外的契约（direct 本就不在收口契约辖内）。

## 4. 落盘 / 留痕

- **产出不落 docs/**（同 consult-common §7.1）。
- 过程留痕照常（consult-common §7.2）：因 direct 无收口，留痕只含**该次请求+生响应**（cli.py 自动落，不调 `verdict`）。

## 5. 编排骨架

```bash
ROOT="${CLAUDE_PLUGIN_ROOT:-$PLUGIN_ROOT}"   # 变量在 hook 外常为空→据本 skill 目录上两级代入插件根（consult-common §3）

# 1. 建留痕会话（mode=direct）
TASK=$(uv run "$ROOT/ai_client/consult_log.py" start \
  --slug <议题slug> --mode direct \
  --trigger "<启动提示词/触发原话>" \
  --host <claude|codex|cursor> \
  --models "<X>")

# 2. 直问 X（分析文档加 --file，可重复）
uv run "$ROOT/ai_client/cli.py" \
  --provider <X> --task "$TASK" --mode direct \
  [--file <doc> ...] \
  "<§4 角色 prompt 或用户原始问题>"
```

- `--file` 由 `cli.py` 读出嵌入 prompt 前部，**所有 transport 通用**（尤其 `openai-compat` 这类纯 API，如 qwen，自身无文件访问能力，必须靠这里读出嵌入）。
- 答案**原样转述** + 一句警示："这是 X 单方观点、未经多模型交叉验证；要摆矛盾压测走 panel/debate"。

## 6. 失败处理

- 失败/超时按 consult-common §9 如实告知。
- **不降级**到别的声音——用户点名 X 即排他。
- direct 无主裁收口，故无 `verdict` 步骤；留痕仅含该次请求+生响应。
