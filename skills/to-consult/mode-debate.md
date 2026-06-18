---
title: debate 形态（正反辩论 + 裁判裁决）
mode: debate
parent: SKILL.md
updated: 2026-06-18
---

# debate 形态 — 正反辩论 + 裁判裁决

> 二元对立议题专用。正方（外部 A）/ 反方（外部 B）轮流立论与反驳，主裁带置信度门控裁决。
> 共享规范（宿主无关 §0 / 底座 §1 / 触发 §6 / 落盘 §7 / 外部接入 §8 / 降级 §9）见 `./consult-common.md`，本文件只写 debate 专属。

---

## 1. 适配检查（必读）

- 议题须**二元对立**："该用 A 还是 B / 要不要做 X / 选 A 还是 B"。
- 非对立议题（"介绍一下 React"、"梳理这个模块"）→ 提示用户换 panel/refine。
- 高风险决策（写入 / 认证 / 金额 / 动重大架构）首选 debate（consult-common §6）。

## 2. 拓扑

主会话**串行**编排（外部底座由 `orchestrate.py` 一次性确定性跑完）：

| 步骤 | 角色 | 底座 | 产出 |
|---|---|---|---|
| 1 立论 | 正方 | external_voices[host][0] | 3–5 核心论点 + 论据 + 反驳预判 |
| 2 立论 | 反方 | external_voices[host][1] | 同结构（坚持反方立场） |
| 3 反驳 | 正方逐条驳反方 → 反方逐条驳正方 | 外部 A / B | 后驳方已读先驳方内容 |
| 4 初裁（含置信度） | 裁判 = 主裁 | 当前宿主主模型 | 0–100% 置信度，门控收敛 |
| 5 裁决 | 裁判 = 主裁 | 当前宿主主模型 | §5 contract 固定输出 |

### 置信度门控（不靠固定轮数，主裁判断）

| 置信度 | 行为 |
|---|---|
| ≥ 85 | 直接进裁决 |
| 60 – 84 | 触发**第二轮反驳**后重评 |
| < 60 | 标"存在重大争议"，输出完整记录，**必须明确裁决不回避**（势均力敌选风险更低一方） |

## 3. 角色立场 prompt 骨架

外部模型的 prompt（主会话喂给 `orchestrate.py`，由其按形态填角色）：

```
你是多模型协作的【正方 / 反方】。议题：<自包含上下文>。
立场约束：坚持本方立场（采纳 A / 否决 X），不要假装中立、不要"两面都对"。
产出：3–5 核心论点 + 论据 + 对对方常见反驳的预判应对。反驳轮已能读到对方立论。
```

> 所有外部 transport 的只读封装在 `ai_client/providers.py`，prompt 层只管内容（见 consult-common §8）。

## 4. 物理架构（debate 专属）

**为何走 `orchestrate.py` 而不是 `panel.js`**：①debate **跨底座**（Workflow.agent() 是 Claude Code 专属且只能调 Claude，调不了外部底座）；②有**串行依赖**（立论→反驳），靠主会话「自觉」逐步调模型不可复现。故由 `orchestrate.py`（Python on `ai_client`，asyncio）确定性编排成结构化 JSON。

**收口（裁决 = 宿主主裁）**调不了主会话自己，留主会话——脚本跑到收口前即止、不做门控决策，只输出辩论记录。各步外部调用的请求+生响应由脚本**自动留痕**（consult-common §7.2）。

## 5. 收口契约（主裁 = 当前宿主主模型）

| 收口动作 | 固定输出 |
|---|---|
| **裁决** | **置信度(0–100%)** + 胜负判定（支持正/反/有条件支持）+ 逐对论点比较 + 关键分歧/共识 + 综合决策建议 + 风险提示 |

**铁律**：必须明确裁决不回避；势均力敌选风险更低一方。**摆矛盾不调和**。

## 6. 编排骨架

### 6.1 一次性确定性编排（推荐）

承接：留痕会话 `$TASK` 已建立（SKILL.md Step 5 / consult-common §7.2），外部声音池 `external_voices[host]` 已取定。

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/ai_client/orchestrate.py" debate \
  --task "$TASK" \
  --pro  <ext0> --con <ext1> \
  "<议题>" \
  [--context "<自包含背景>"] [--file <doc>]
```

`<ext0>`/`<ext1>` = `external_voices[host]` 两席（debate 命中用户「用 X 一起讨论」分流时把对应席位覆盖为 X，见 consult-common §6）。

输出：结构化 JSON，`steps` 含各步 text/error，主会话据此读辩论记录裁决。

### 6.2 主裁收口（接 SKILL.md Step 6）

1. 主会话读 `orchestrate.py` 输出的 JSON 辩论记录。
2. **初裁含置信度** → 按 §2 门控：
   - ≥85 → 进裁决（§5 contract）
   - 60–84 → 主会话再调一次 `orchestrate.py` 续辩、或主裁直接二轮反驳
   - <60 → 标重大争议输出完整记录 + 强制裁决
3. 任何步 `error`/`skipped` → 按 consult-common §9 降级（外部不足用宿主底座补位辩方并标"<角色>与收口同底座、未经完全独立第三方"；裁判恒=主裁）。
4. 收口结论按 SKILL.md Step 8 写入留痕（`consult_log.py verdict --mode debate`）。

降级特例：**裁判失败**输出已收集的「立论+反驳」让用户判断，**不把收口降级到对抗方同实例**（consult-common §9）。
