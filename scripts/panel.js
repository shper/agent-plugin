// 多模型 panel —— 宿主底座 persona 批的确定性 fan-out（**Claude Code 宿主适配层**，Workflow 工具脚本）
//
// 宿主边界（见 to-consult/consult-common.md §3 + mode-panel.md §5/§7）：
//   本脚本是 panel「宿主底座 persona 批」的 **Claude Code 适配层**——`Workflow`/`Agent` 是 Claude Code
//   专属工具，其 model 只能是 Claude，故只有 Claude Code 宿主能用本脚本做确定性 fan-out。
//   Codex / Cursor 宿主没有等价工具，由主会话**串行自扮演** persona（§9 正常路径），不调本脚本。
//   两种路径产出同构角色卡；persona 底座始终 = 当前宿主底座（本脚本里即 Claude）。
//   外部声音批（claude / codex / cursor / API，按 external_voices[host] 取池）由主会话走 Bash 调
//   ai_client/，不在此脚本。综合裁决、落盘、触发判定全留主会话（宿主 skill）。
//   脚本不跑 Bash、不 commit、不 Edit。
//
// 形态边界（to-consult/mode-panel.md + consult-common.md §3）：本脚本只服务 **panel 形态**的并行 persona 批。
//   debate / refine 形态跨底座 + 有串行依赖（立论→反驳→裁决 / 生成→互评/质检→合并/修订），
//   Workflow 既调不了外部底座、也不便表达跨批串行，故整条流程由主会话编排，不调本脚本。
//
// 同质化防护：同一底座派多 persona 易同质，故靠「强制对立 lens + 立场约束」拉开区分度，
//   不靠身份标签（to-consult/consult-common.md §1）。每个 persona 的约束由主 Agent 在 args.roster[].lens 给定，
//   原样注入 prompt，persona 之间互不可见（不附和）。
//
// 输入 args（主 Agent 组装）：
//   {
//     topic:   "一句话议题",
//     context: "自包含上下文（背景 + 待决问题 + 相关架构决策摘录，如有），由主 Agent 摘录，prompt 不漫游",
//     rounds:  1,                                  // 默认 1（panel）；debate 多轮未实现，预留
//     roster:  [{ role: "架构红队", lens: "只挑技术可行性…不评价价值" }, ...]
//   }
//
// 返回：与 roster 等长的角色卡数组（mode-panel.md §3 schema），供主 Agent 汇总 + 综合。

export const meta = {
  name: 'panel-host-persona',
  description: '多模型 panel 的宿主底座 persona 批（Claude Code 适配层）：固定 persona 就一议题各自独立出角色卡（不含外部模型/不落盘/不裁决）',
  whenToUse: '仅 Claude Code 宿主下，由 /to-consult 在命中 to-consult/consult-common.md §6 触发时调用，取宿主 persona 批角色卡；外部声音批主会话另走 Bash 调 ai_client，非 Claude 宿主由主会话自扮演 persona',
  phases: [{ title: 'Panel', detail: '每个 persona 一个子 agent 并发出角色卡' }],
}

// ── 角色卡 schema（to-consult/mode-panel.md §3，强制结构化）──────────────────
const CARD_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['role', 'stance', 'key_points', 'risks', 'challenged_assumptions', 'recommendation'],
  properties: {
    role: { type: 'string', description: '回显本角色名' },
    stance: { type: 'string', description: '一句话总立场' },
    key_points: { type: 'array', items: { type: 'string' }, description: '核心论点' },
    risks: { type: 'array', items: { type: 'string' }, description: '该视角看到的风险' },
    challenged_assumptions: {
      type: 'array',
      items: { type: 'string' },
      description: '质疑的隐含前提——盲区互补的关键产出，宁可多列',
    },
    recommendation: { type: 'string', description: '建议：采纳 / 改造 / 否决 + 理由' },
  },
}

// ── 单个 persona 的自包含 prompt（to-consult/mode-panel.md §4 骨架）────────
function buildPrompt(topic, context, persona) {
  return `你是多模型 panel 的【${persona.role}】。就以下议题独立出一张角色卡。

## 议题
${topic}

## 上下文（自包含，勿据此漫游全仓）
${context || '（主 Agent 未提供额外摘录）'}

## 你的强制视角（不得越界，越界即失职）
${persona.lens || '（未指定，按角色名常识发挥）'}

## 纪律
- 只用你这一视角的判断，**不要附和其它角色**——你看不到他们，也不该揣测他们会说什么。
- challenged_assumptions 是重点：把这个方案**默认成立、其实没验证**的前提挑出来，宁可多列。
- 严格按角色卡 schema 返回：role / stance / key_points / risks / challenged_assumptions / recommendation。`
}

// ── 主流程 ───────────────────────────────────────────────────────────────
phase('Panel')

// 投参兜底：本 harness 的 Workflow 工具会把 args 以 **JSON 字符串** 投递（实测 typeof args === 'string'，
// 非对象），脚本侧统一解析，否则下方 args.topic/args.roster 全 undefined、guard 误判空参直接 return []。
let a = args
if (typeof a === 'string') {
  try {
    a = JSON.parse(a)
  } catch (_) {
    a = {}
  }
}

const topic = a && a.topic ? String(a.topic) : ''
const context = a && a.context ? String(a.context) : ''
const roster = a && Array.isArray(a.roster) ? a.roster : []

if (!topic || roster.length === 0) {
  log('⚠️ panel.js 需要 args.topic 与非空 args.roster（Claude persona 列表）。主 Agent 应在命中触发时组装后调用。')
  return []
}

const rounds = a && a.rounds ? a.rounds : 1
if (rounds !== 1) {
  log(`ℹ️ rounds=${rounds} 暂未实现（debate 形态预留），本次按 1 轮 panel 执行。`)
}

log(`panel Claude 批 ${roster.length} 个 persona 并发：${roster.map((p) => p.role).join(' / ')}`)

// 同波全部并发（parallel 天然 barrier）。persona 之间相互独立，无共享态。
const cards = await parallel(
  roster.map((persona) => () =>
    agent(buildPrompt(topic, context, persona), {
      label: `panel:${persona.role}`,
      phase: 'Panel',
      schema: CARD_SCHEMA,
    }).then((card) =>
      card
        ? { ...card, role: card.role || persona.role, model: 'claude' }
        : {
            role: persona.role,
            model: 'claude',
            stance: '(角色卡缺失：agent 被跳过或返回空)',
            key_points: [],
            risks: [],
            challenged_assumptions: [],
            recommendation: '主 Agent 请按缺席处理或重派',
          },
    ),
  ),
)

return cards
