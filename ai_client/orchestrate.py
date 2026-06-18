# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.28"]
# ///
"""多形态协作编排 —— debate / refine 的外部底座多步拓扑。

定位（to-consult/mode-debate.md / mode-refine.md，物理架构见 consult-common.md §3）：
  这两种形态跨底座 + 有串行依赖（立论→反驳→裁决 / 生成→互评/质检→合并/修订），靠主会话「自觉」
  逐步调模型不可复现（已知反模式）。本脚本把**外部底座的多步拓扑**
  确定性化：按固定顺序/并发调 ai_client provider，输出结构化中间产物（JSON）。
  **收口（裁决/合并/修订 = 当前宿主主裁）调不了主会话自己，留主会话**——与 panel.js 把综合
  留主会话同一分工。

refine（精炼）一形态两方向，互评方向作参数（原 reflection + review-chain 收敛）：
  two-way = 双声独立生成 + 交叉互评 + 合并；one-way = 生成 + 单向质检 + 修订（--skip-gen 仅质检）。

用法（主会话走 Bash；ROOT = 插件根，CLAUDE_PLUGIN_ROOT/PLUGIN_ROOT 仅 hook 环境可靠、skill 内据 skill 目录上两级代入；分析文档加 --file，可重复）：
  uv run "$ROOT/ai_client/orchestrate.py" debate --pro  codex --con  cursor "<议题>" [--context ...] [--file ...] [--fallback <宿主底座>]
  uv run "$ROOT/ai_client/orchestrate.py" refine --ext0 codex --ext1 cursor "<任务>" [--direction two-way|one-way] [--context ...] [--file ...] [--skip-gen] [--fallback <宿主底座>]

降级（§9）已下沉为确定性：给 --fallback <宿主底座 provider> 后，任一外部步骤失败即由该底座补位重试，
对应步骤打 degraded=True + requested + note（同源折扣），envelope 顶层附 degraded 列表——不再依赖主会话读 JSON 后自觉手动补位。

stdout = 结构化 JSON；主会话解析后由当前宿主主模型按 to-consult/mode-debate.md「收口契约」/ mode-refine.md「收口契约」收口。
exit: 0 全部步骤成功 / 1 有步骤失败或跳过（JSON 仍输出，error 字段标注，主会话据此降级）/ 2 配置或参数错误。

核心编排函数依赖注入 `caller`（async (provider_id, prompt) -> str），顶层**不** import
providers / httpx（延迟到 CLI 内），故可在无 httpx 环境单测（mock caller）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable

import consult_log  # 纯标准库，顶层 import 不破坏「无 httpx 单测」（单测 mock caller 不走 _build_caller）
import independence  # 同上纯标准库：跨底座独立性检测（C4），结果嵌入 envelope 供主裁如实暴露

# caller: 把一个 prompt 发给某 provider，返回纯文本；失败抛异常（由 _step 捕获）。
Caller = Callable[[str, str], Awaitable[str]]


# ── 上下文 + 角色 prompt 模板（对齐 to-consult/mode-debate.md §3 / mode-refine.md §4）───

def _embed_files(files: list[str]) -> str:
    """把每个文件读成 fenced 材料块（与 cli.py 同构）。缺失抛 FileNotFoundError。"""
    blocks: list[str] = []
    for fp in files:
        path = Path(fp)
        if not path.exists():
            raise FileNotFoundError(f"未找到文件: {fp}")
        blocks.append(f"## 待分析材料：{fp}\n```\n{path.read_text(encoding='utf-8')}\n```")
    return "\n\n".join(blocks)


def _context_block(topic: str, context: str, material: str) -> str:
    parts = [f"## 议题/任务\n{topic}"]
    if context:
        parts.append(f"## 上下文（自包含，勿据此漫游全仓）\n{context}")
    if material:
        parts.append(material)
    return "\n\n".join(parts)


def _p_opening(side: str, base: str) -> str:
    return (
        f"你是多模型辩论的【{side}】。就以下议题坚持「{side}」立场，给出有力论证。\n\n"
        f"{base}\n\n"
        f"要求：3–5 个核心论点，每个配支撑论据；预判对方可能的反驳并预先回应。"
        f"只站「{side}」，不要中立、不要倒戈。"
    )


def _p_rebuttal(side: str, base: str, opponent_opening: str, prior_rebuttal: str | None = None) -> str:
    extra = (
        f"\n\n## 对方刚才对你的反驳\n{prior_rebuttal}\n（请一并回应，别让对方的反驳站住）"
        if prior_rebuttal
        else ""
    )
    return (
        f"你是多模型辩论的【{side}】。逐条反驳对方立论，指出其论据漏洞 / 隐含前提 / 风险。\n\n"
        f"{base}\n\n"
        f"## 对方立论\n{opponent_opening}{extra}\n\n"
        f"要求：逐条回应对方论点，坚持「{side}」立场，不要倒戈。"
    )


def _p_generate(base: str) -> str:
    return (
        f"就以下任务/议题独立产出一版方案/答案。\n\n"
        f"{base}\n\n"
        f"要求：完整、自洽、可执行；这是你独立的初版，不要假设有人会补充。"
    )


def _p_cross_review(reviewer: str, base: str, target_draft: str) -> str:
    return (
        f"你是多模型互评的【{reviewer}】。审查另一位的初版，逐条挑问题（不要改写）。\n\n"
        f"{base}\n\n"
        f"## 待审初版\n{target_draft}\n\n"
        f"要求：逐条用 H/M/L 标记 + 每条评分(0–100)——"
        f"H 必须改（事实错/逻辑矛盾/严重遗漏）、M 建议改（表达/结构/完整性）、L 无需改；"
        f"末尾给整体质量评分(0–100)。只评不写。"
    )


def _p_qc(base: str, draft: str) -> str:
    return (
        f"你是多模型质检链的【质检者】。审查初版，逐条挑问题（不要修订）。\n\n"
        f"{base}\n\n"
        f"## 待质检初版\n{draft}\n\n"
        f"要求：逐条 H/M/L 标记（H 事实错/逻辑矛盾/严重遗漏、M 表达/结构/完整性、L 无需改）"
        f"+ 末尾整体质量评分(0–100)。只质检不修订。"
    )


# ── 步骤包装（单步失败不中断整条拓扑，error 字段标注）─────────────────────

def _skipped(provider: str, reason: str) -> dict:
    return {"provider": provider, "text": None, "error": f"skipped: {reason}"}


async def _step(caller: Caller, provider: str, prompt: str, *, fallback: str = "") -> dict:
    """跑一步外部调用。失败时若给了 `fallback`（宿主底座）则**确定性补位**重试一次。

    这把 consult-common §9『外部失败→宿主底座补位』从「主会话读 JSON 后自觉手动补」下沉成
    脚本内逻辑，使降级与编排同样确定性可复现（to-consult C3 修复）。补位成功的步骤打
    `degraded=True` + `requested`（原 provider）+ `note`（同源折扣标注），供主裁收口如实暴露。
    """
    try:
        text = await caller(provider, prompt)
        return {"provider": provider, "text": text, "error": None}
    except Exception as e:  # noqa: BLE001 —— 编排边界：单步失败转 error 字段，不中断其它步骤
        if fallback and fallback != provider:
            try:
                text = await caller(fallback, prompt)
                return {
                    "provider": fallback, "text": text, "error": None,
                    "degraded": True, "requested": provider,
                    "note": (f"{provider} 失败（{e}），由宿主底座 {fallback} 补位"
                             "——与收口同底座、未经完全独立第三方"),
                }
            except Exception as e2:  # noqa: BLE001 —— 补位亦失败：如实记两段错误
                return {"provider": provider, "text": None,
                        "error": f"{e}；补位 {fallback} 亦失败：{e2}"}
        return {"provider": provider, "text": None, "error": str(e)}


def _envelope(mode: str, providers: dict, steps: dict, **extra) -> dict:
    ok = all(s.get("error") is None for s in steps.values())
    env = {"mode": mode, "providers": providers, "ok": ok, "steps": steps, **extra}
    degraded = [k for k, s in steps.items() if s.get("degraded")]
    if degraded:
        # 主裁据此判断同源折扣：若对抗双方都降级到同一宿主底座，§9 建议流产而非降级。
        env["degraded"] = degraded
    return env


# ── 三形态编排（收口留主会话；这里只跑到收口前）──────────────────────────

async def run_debate(
    caller: Caller, *, topic: str, context: str, pro: str, con: str,
    material: str = "", fallback: str = ""
) -> dict:
    """正方立论 ‖ 反方立论 → 正方反驳 → 反方反驳（带正方反驳）。裁决=主裁，留主会话。

    `fallback`（宿主底座 provider）非空时，任一外部步骤失败即确定性补位（§9，见 `_step`）。
    """
    base = _context_block(topic, context, material)
    pro_open, con_open = await asyncio.gather(
        _step(caller, pro, _p_opening("正方", base), fallback=fallback),
        _step(caller, con, _p_opening("反方", base), fallback=fallback),
    )
    # 反驳串行：正方先驳反方立论，反方后驳（读得到正方反驳）。对方立论缺失则跳过反驳。
    if con_open["error"]:
        pro_reb = _skipped(pro, "反方立论失败，无可反驳")
    else:
        pro_reb = await _step(caller, pro, _p_rebuttal("正方", base, con_open["text"]), fallback=fallback)
    if pro_open["error"]:
        con_reb = _skipped(con, "正方立论失败，无可反驳")
    else:
        con_reb = await _step(
            caller, con, _p_rebuttal("反方", base, pro_open["text"], prior_rebuttal=pro_reb.get("text")),
            fallback=fallback,
        )
    steps = {
        "pro_opening": pro_open,
        "con_opening": con_open,
        "pro_rebuttal": pro_reb,
        "con_rebuttal": con_reb,
    }
    return _envelope("debate", {"pro": pro, "con": con}, steps)


async def run_reflection(
    caller: Caller, *, topic: str, context: str, a: str, b: str,
    material: str = "", fallback: str = ""
) -> dict:
    """A、B 并行独立生成 → 交叉互评（A 评 B ‖ B 评 A）。合并=主裁，留主会话。

    `fallback` 非空时任一外部步骤失败即确定性补位（§9，见 `_step`）。
    """
    base = _context_block(topic, context, material)
    draft_a, draft_b = await asyncio.gather(
        _step(caller, a, _p_generate(base), fallback=fallback),
        _step(caller, b, _p_generate(base), fallback=fallback),
    )

    async def _maybe_review(reviewer: str, reviewer_label: str, target: dict, target_label: str) -> dict:
        if target["error"]:
            return _skipped(reviewer, f"{target_label} 初版失败，无可互评")
        return await _step(caller, reviewer, _p_cross_review(reviewer_label, base, target["text"]), fallback=fallback)

    review_a_on_b, review_b_on_a = await asyncio.gather(
        _maybe_review(a, "Agent A", draft_b, "B"),
        _maybe_review(b, "Agent B", draft_a, "A"),
    )
    steps = {
        "draft_a": draft_a,
        "draft_b": draft_b,
        "review_a_on_b": review_a_on_b,
        "review_b_on_a": review_b_on_a,
    }
    return _envelope("reflection", {"a": a, "b": b}, steps)


async def run_review(
    caller: Caller,
    *,
    topic: str,
    context: str,
    gen: str,
    qc: str,
    material: str = "",
    skip_gen: bool = False,
    fallback: str = "",
) -> dict:
    """生成 → 质检（H/M/L+评分）。仅质检模式用 material 当初版。修订=主裁，留主会话。

    `fallback` 非空时任一外部步骤失败即确定性补位（§9，见 `_step`）。
    """
    base = _context_block(topic, context, material)
    if skip_gen:
        if not material:
            draft = _skipped("user-material", "仅质检模式但未提供待审材料（--file）")
        else:
            draft = {"provider": "user-material", "text": material, "error": None}
    else:
        draft = await _step(caller, gen, _p_generate(base), fallback=fallback)

    if draft["error"]:
        qc_report = _skipped(qc, "初版缺失，无可质检")
    else:
        qc_report = await _step(caller, qc, _p_qc(base, draft["text"]), fallback=fallback)
    steps = {"draft": draft, "qc_report": qc_report}
    return _envelope("review-chain", {"gen": gen if not skip_gen else "user-material", "qc": qc}, steps)


async def run_refine(
    caller: Caller,
    *,
    direction: str,
    topic: str,
    context: str,
    ext0: str,
    ext1: str,
    material: str = "",
    skip_gen: bool = False,
    fallback: str = "",
) -> dict:
    """精炼形态路由（to-consult/mode-refine.md）：一形态两方向，复用 reflection / review-chain 拓扑。

    two-way = 双声独立生成 + 交叉互评（ext0=A, ext1=B）；
    one-way = 生成 + 单向质检（ext0=生成, ext1=质检；--skip-gen 用 material 当初版）。
    `fallback`（宿主底座）非空时外部步骤失败即确定性补位（§9）。
    收口（合并/修订 = 主裁）留主会话。envelope 的 mode 统一为 'refine' + direction 字段，
    底层 run_* 仍返回各自拓扑 mode（保留其单测语义）。
    """
    if direction == "two-way":
        env = await run_reflection(
            caller, topic=topic, context=context, a=ext0, b=ext1, material=material, fallback=fallback
        )
    else:  # one-way
        env = await run_review(
            caller, topic=topic, context=context, gen=ext0, qc=ext1,
            material=material, skip_gen=skip_gen, fallback=fallback,
        )
    env["mode"] = "refine"
    env["direction"] = direction
    return env


# ── CLI（真实 caller 在此延迟构造，避免顶层 import httpx）────────────────────

_ROLE_RE = re.compile(r"【(.+?)】")


def _extract_role(prompt: str) -> str:
    """从角色 prompt 提取 `【…】` 角色名（立论/反驳/质检 等）；纯生成步无标签则留空。"""
    m = _ROLE_RE.search(prompt)
    return m.group(1) if m else ""


def _fallback_task() -> str:
    """主会话漏传 --task 时的兜底目录名（保证「必须留痕」不落空）。"""
    return time.strftime("%Y%m%d-%H%M%S") + "_adhoc"


def _build_caller(
    provider_ids: list[str], timeout: float, *, task: str = "", mode: str = ""
) -> Caller:
    """延迟 import providers/config；校验 provider 都已配（缺失则 exit 2）。

    返回的 caller 在每次外部调用前后把「请求 + prompt + 生响应/error」强制留痕（consult_log，
    非阻塞）——故 debate/refine 的每一步外部调用都自动落 session.md，核心编排函数零改动。
    """
    from config import get_providers, load_config  # noqa: PLC0415
    from providers import build_provider  # noqa: PLC0415

    try:
        conf = load_config()
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        raise SystemExit(2)
    provs = get_providers(conf)
    missing = [p for p in dict.fromkeys(provider_ids) if p not in provs]
    if missing:
        print(f"未知 provider: {missing}。可选：{sorted(provs)}", file=sys.stderr)
        raise SystemExit(2)

    async def caller(pid: str, prompt: str) -> str:
        provider = build_provider(pid, provs[pid])
        request = provider.request_repr(prompt)
        role = _extract_role(prompt)
        started = time.monotonic()
        try:
            text = await provider.ask(prompt, timeout=timeout)
        except Exception as e:
            consult_log.record_call(
                task=task, mode=mode, provider=pid, request=request, prompt=prompt,
                error=str(e), role=role, model=provider.model,
                duration=time.monotonic() - started,
            )
            raise
        consult_log.record_call(
            task=task, mode=mode, provider=pid, request=request, prompt=prompt,
            response=text, role=role, model=provider.model,
            duration=time.monotonic() - started,
        )
        return text

    return caller


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("topic", help="议题 / 任务")
    p.add_argument("--context", default="", help="自包含上下文")
    p.add_argument("--file", action="append", default=[], dest="files", metavar="PATH",
                   help="把文件内容作为材料嵌入，可重复")
    p.add_argument("--timeout", type=float, default=120.0, help="单步调用超时（秒）")
    p.add_argument("--task", default="", help="留痕会话目录名（consult_log.py start 取得；漏传则兜底）")
    p.add_argument("--fallback", default="", metavar="PROVIDER",
                   help="宿主底座 provider id：外部步骤失败时确定性补位（§9 降级，步骤打 degraded 标注）")
    p.add_argument("--host", default="", metavar="HOST",
                   help="宿主 claude|codex|cursor：用于跨底座独立性检测（C4），判外部席是否与主裁同族")


def main() -> int:
    parser = argparse.ArgumentParser(description="多形态协作编排（debate / refine）")
    sub = parser.add_subparsers(dest="mode", required=True)

    pd = sub.add_parser("debate", help="正反辩论 + 反驳（裁决留主会话）")
    _add_common(pd)
    pd.add_argument("--pro", required=True, help="正方 provider id")
    pd.add_argument("--con", required=True, help="反方 provider id")

    pr = sub.add_parser("refine", help="精炼：双声互评合并 / 单向质检修订（收口留主会话）")
    _add_common(pr)
    pr.add_argument("--direction", choices=["two-way", "one-way"], default="two-way",
                    help="two-way=双声独立生成+交叉互评（原 reflection）/ one-way=生成+单向质检（原 review-chain）")
    pr.add_argument("--ext0", required=True, help="外部底座 0：two-way=Agent A / one-way=生成者")
    pr.add_argument("--ext1", required=True, help="外部底座 1：two-way=Agent B / one-way=质检者（须≠生成）")
    pr.add_argument("--skip-gen", action="store_true", help="仅 one-way：用 --file 材料当初版，跳过生成")

    args = parser.parse_args()

    try:
        material = _embed_files(args.files) if args.files else ""
    except OSError as e:
        print(e, file=sys.stderr)
        return 2

    task = args.task or _fallback_task()
    # fallback（宿主底座）若给了也要纳入 provider 校验，否则补位时会 KeyError。
    fb = [args.fallback] if args.fallback else []
    if args.mode == "debate":
        caller = _build_caller([args.pro, args.con] + fb, args.timeout, task=task, mode="debate")
        env = asyncio.run(run_debate(caller, topic=args.topic, context=args.context,
                                     pro=args.pro, con=args.con, material=material,
                                     fallback=args.fallback))
    else:  # refine
        if args.skip_gen and args.direction != "one-way":
            print("--skip-gen 仅 one-way（质检）方向有效", file=sys.stderr)
            return 2
        if args.skip_gen and not material:
            print("仅质检模式（--skip-gen）需用 --file 提供待审材料", file=sys.stderr)
            return 2
        caller = _build_caller([args.ext0, args.ext1] + fb, args.timeout,
                               task=task, mode=f"refine/{args.direction}")
        env = asyncio.run(run_refine(caller, direction=args.direction, topic=args.topic,
                                     context=args.context, ext0=args.ext0, ext1=args.ext1,
                                     material=material, skip_gen=args.skip_gen,
                                     fallback=args.fallback))

    # 跨底座独立性检测（C4，非阻塞）：把外部两席 + 主裁的同源重合嵌入 envelope，供主裁如实暴露。
    try:
        from config import get_providers, load_config  # noqa: PLC0415
        _provs = get_providers(load_config())
        _seat_ids = [args.pro, args.con] if args.mode == "debate" else [args.ext0, args.ext1]
        _warns = independence.analyze(args.host, {p: _provs[p] for p in _seat_ids if p in _provs})
        if _warns:
            env["independence"] = _warns
    except Exception as e:  # noqa: BLE001 —— 检测是增益，失败不拦输出
        print(f"[independence] 检测跳过（不阻断）：{e}", file=sys.stderr)

    print(json.dumps(env, ensure_ascii=False, indent=2))
    return 0 if env["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
