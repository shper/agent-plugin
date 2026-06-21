"""orchestrate 三形态编排单测 —— mock caller，不碰真实 provider。

覆盖：debate 拓扑顺序 + 反驳带对方立论 + 反方反驳带正方反驳(prior)；
reflection 并行生成 + 交叉互评带对方初版；review 生成→质检 + 质检带初版；
review 仅质检模式跳过生成；单步失败转 error 不中断 + 依赖失败跳过 + ok 标记。
"""

from __future__ import annotations

import asyncio
import sys

import orchestrate


def make_caller(fail: set[str] | None = None):
    """返回带标签文本 `<<pid|role>>` 的 fake caller；role 按 prompt 特征判定。

    role 标签让下游 prompt 能断言「上游输出被带入」。fail 里的 provider 调用即抛错。
    """
    fail = fail or set()
    calls: list[tuple[str, str]] = []

    def _role(prompt: str) -> str:
        if "逐条反驳对方立论" in prompt:
            return "rebuttal"
        if "互评" in prompt:
            return "review"
        if "质检" in prompt:
            return "qc"
        if "坚持「" in prompt:
            return "opening"
        if "独立产出" in prompt:
            return "generate"
        return "other"

    async def caller(pid: str, prompt: str) -> str:
        calls.append((pid, prompt))
        if pid in fail:
            raise RuntimeError(f"boom:{pid}")
        return f"<<{pid}|{_role(prompt)}>>"

    caller.calls = calls  # type: ignore[attr-defined]
    return caller


def _prompt_of(caller, pid: str, needle: str) -> str:
    """取 caller 对 pid 的、含 needle 的那次调用 prompt（断言依赖传递用）。"""
    hits = [p for (q, p) in caller.calls if q == pid and needle in p]
    assert hits, f"未找到 {pid} 含 {needle!r} 的调用"
    return hits[0]


# ── debate ──────────────────────────────────────────────────────────────

def test_debate_topology_and_dependency():
    caller = make_caller()
    env = asyncio.run(orchestrate.run_debate(
        caller, topic="用 A 还是 B", context="ctx", pro="codex", con="cursor"))

    assert env["mode"] == "debate"
    assert env["ok"] is True
    assert env["providers"] == {"pro": "codex", "con": "cursor"}
    assert set(env["steps"]) == {"pro_opening", "con_opening", "pro_rebuttal", "con_rebuttal"}

    # 正方反驳里带了反方立论
    pro_reb_prompt = _prompt_of(caller, "codex", "逐条反驳对方立论")
    assert "<<cursor|opening>>" in pro_reb_prompt
    # 反方反驳里带了正方立论 + 正方反驳(prior)
    con_reb_prompt = _prompt_of(caller, "cursor", "逐条反驳对方立论")
    assert "<<codex|opening>>" in con_reb_prompt
    assert "<<codex|rebuttal>>" in con_reb_prompt  # prior_rebuttal 透传


def test_debate_opponent_failure_skips_rebuttal():
    caller = make_caller(fail={"cursor"})  # 反方挂
    env = asyncio.run(orchestrate.run_debate(
        caller, topic="t", context="", pro="codex", con="cursor"))

    assert env["ok"] is False
    assert env["steps"]["con_opening"]["error"].startswith("boom:")
    # 反方立论失败 → 正方无可反驳，跳过
    assert env["steps"]["pro_rebuttal"]["error"].startswith("skipped")
    # 正方立论成功 → 反方仍尝试反驳，但反方 provider 挂 → boom
    assert env["steps"]["con_rebuttal"]["error"].startswith("boom:")


# ── 降级补位（C3：§9 外部失败→宿主底座确定性补位）────────────────────────

def test_step_fallback_substitutes_on_failure():
    caller = make_caller(fail={"cursor"})  # 反方挂
    env = asyncio.run(orchestrate.run_debate(
        caller, topic="t", context="", pro="codex", con="cursor", fallback="claude"))

    # 反方立论失败 → 由宿主底座 claude 补位，整轮仍 ok
    assert env["ok"] is True
    con_open = env["steps"]["con_opening"]
    assert con_open["error"] is None
    assert con_open["provider"] == "claude"      # 实际答者是补位底座
    assert con_open["degraded"] is True
    assert con_open["requested"] == "cursor"     # 原请求席位
    assert "同底座" in con_open["note"]
    # envelope 顶层汇总降级步骤，供主裁判断同源折扣
    assert "con_opening" in env["degraded"]
    # 反方反驳也由 claude 补位（cursor 仍挂）
    assert env["steps"]["con_rebuttal"]["provider"] == "claude"


def test_step_fallback_also_fails_records_both_errors():
    caller = make_caller(fail={"cursor", "claude"})  # 反方 + 补位都挂
    env = asyncio.run(orchestrate.run_debate(
        caller, topic="t", context="", pro="codex", con="cursor", fallback="claude"))

    assert env["ok"] is False
    con_open = env["steps"]["con_opening"]
    assert con_open["error"] is not None
    assert "补位" in con_open["error"]           # 两段错误都记下
    assert "degraded" not in env                  # 没有任何步骤成功降级


def test_no_fallback_keeps_legacy_error_behavior():
    caller = make_caller(fail={"cursor"})
    env = asyncio.run(orchestrate.run_debate(
        caller, topic="t", context="", pro="codex", con="cursor"))  # 不传 fallback
    assert env["ok"] is False
    assert env["steps"]["con_opening"]["error"].startswith("boom:")
    assert "degraded" not in env


# ── reflection ──────────────────────────────────────────────────────────

def test_reflection_parallel_and_cross_review():
    caller = make_caller()
    env = asyncio.run(orchestrate.run_reflection(
        caller, topic="优化方案", context="", a="codex", b="cursor"))

    assert env["mode"] == "reflection"
    assert env["ok"] is True
    assert set(env["steps"]) == {"draft_a", "draft_b", "review_a_on_b", "review_b_on_a"}

    # A 评 B：codex 的互评 prompt 带 B(cursor) 的初版
    a_review = _prompt_of(caller, "codex", "互评")
    assert "<<cursor|generate>>" in a_review
    # B 评 A：cursor 的互评 prompt 带 A(codex) 的初版
    b_review = _prompt_of(caller, "cursor", "互评")
    assert "<<codex|generate>>" in b_review


def test_reflection_draft_failure_skips_its_review():
    caller = make_caller(fail={"codex"})  # A 生成挂
    env = asyncio.run(orchestrate.run_reflection(
        caller, topic="t", context="", a="codex", b="cursor"))

    assert env["ok"] is False
    assert env["steps"]["draft_a"]["error"].startswith("boom:")
    # A 初版失败 → B 无从评 A
    assert env["steps"]["review_b_on_a"]["error"].startswith("skipped")


# ── review-chain ────────────────────────────────────────────────────────

def test_review_chain_qc_sees_draft():
    caller = make_caller()
    env = asyncio.run(orchestrate.run_review(
        caller, topic="写一份报告", context="", gen="codex", qc="cursor"))

    assert env["mode"] == "review-chain"
    assert env["ok"] is True
    assert env["providers"] == {"gen": "codex", "qc": "cursor"}
    # 质检 prompt 带了生成的初版
    qc_prompt = _prompt_of(caller, "cursor", "质检")
    assert "<<codex|generate>>" in qc_prompt


def test_review_skip_gen_uses_material_and_skips_generation():
    caller = make_caller()
    env = asyncio.run(orchestrate.run_review(
        caller, topic="审这篇", context="", gen="codex", qc="cursor",
        material="## 待分析材料：x.md\n```\n用户已有内容\n```", skip_gen=True))

    assert env["ok"] is True
    assert env["steps"]["draft"]["provider"] == "user-material"
    assert "用户已有内容" in env["steps"]["draft"]["text"]
    # 生成 provider 完全没被调用
    assert all(pid != "codex" for (pid, _) in caller.calls)
    # 质检仍带材料
    assert "用户已有内容" in _prompt_of(caller, "cursor", "质检")


def test_review_skip_gen_without_material_errors():
    caller = make_caller()
    env = asyncio.run(orchestrate.run_review(
        caller, topic="t", context="", gen="codex", qc="cursor", material="", skip_gen=True))

    assert env["ok"] is False
    assert env["steps"]["draft"]["error"].startswith("skipped")
    assert env["steps"]["qc_report"]["error"].startswith("skipped")
    assert caller.calls == []  # 一次模型都没调


# ── refine 路由（一形态两方向，复用上面拓扑，仅覆盖 mode/direction + 席位映射）──

def test_refine_two_way_routes_to_reflection():
    caller = make_caller()
    env = asyncio.run(orchestrate.run_refine(
        caller, direction="two-way", topic="优化方案", context="", ext0="codex", ext1="cursor"))

    # 对外统一 mode=refine + direction；底层仍是 reflection 拓扑的 steps
    assert env["mode"] == "refine"
    assert env["direction"] == "two-way"
    assert set(env["steps"]) == {"draft_a", "draft_b", "review_a_on_b", "review_b_on_a"}
    # ext0→A(codex)、ext1→B(cursor)：A 评 B 带 B 初版
    assert "<<cursor|generate>>" in _prompt_of(caller, "codex", "互评")


def test_refine_one_way_routes_to_review():
    caller = make_caller()
    env = asyncio.run(orchestrate.run_refine(
        caller, direction="one-way", topic="写一份报告", context="", ext0="codex", ext1="cursor"))

    assert env["mode"] == "refine"
    assert env["direction"] == "one-way"
    assert set(env["steps"]) == {"draft", "qc_report"}
    # ext0→生成(codex)、ext1→质检(cursor)：质检带生成初版
    assert "<<codex|generate>>" in _prompt_of(caller, "cursor", "质检")


def test_refine_one_way_rejects_same_gen_and_qc(monkeypatch, capsys):
    """one-way 质检者须 ≠ 生成者底座（CLI 守卫，在建 caller / 读 config 前即 exit 2）。"""
    monkeypatch.setattr(sys, "argv", [
        "orchestrate.py", "refine", "--direction", "one-way",
        "--ext0", "qwen", "--ext1", "qwen", "任务"])
    assert orchestrate.main() == 2
    assert "须 ≠" in capsys.readouterr().err


def test_refine_one_way_skip_gen_uses_material():
    caller = make_caller()
    env = asyncio.run(orchestrate.run_refine(
        caller, direction="one-way", topic="审这篇", context="", ext0="codex", ext1="cursor",
        material="## 待分析材料：x.md\n```\n用户已有内容\n```", skip_gen=True))

    assert env["mode"] == "refine"
    assert env["direction"] == "one-way"
    assert env["steps"]["draft"]["provider"] == "user-material"
    assert all(pid != "codex" for (pid, _) in caller.calls)  # 生成方未被调
    assert "用户已有内容" in _prompt_of(caller, "cursor", "质检")
