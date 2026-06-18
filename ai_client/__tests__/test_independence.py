"""跨底座独立性检测单测（C4）—— 纯标准库，随 `python3 -m pytest __tests__ -q` 跑。

覆盖：模型族/网关推断；外部席与主裁同族（judge_overlap）；池内同族（pool_same_family）；
池内同网关（pool_same_gateway，含用户真实 ark 三席场景）；CLI 默认 model 未知（family_unknown）；
全异质池无告警。
"""

from __future__ import annotations

import independence


def _api(model, base_url):
    return {"type": "openai-compat", "model": model, "base_url": base_url}


# ── 推断 ──────────────────────────────────────────────────────────────────

def test_infer_family_api_uses_model_and_gateway():
    fam, gw = independence.infer_family(_api("deepseek-v4-pro", "https://ark.cn-beijing.volces.com/api/v3"))
    assert fam == "deepseek"
    assert gw == "ark.cn-beijing.volces.com"


def test_infer_family_cli_defaults():
    assert independence.infer_family({"type": "claude-cli"}) == ("anthropic", None)
    assert independence.infer_family({"type": "codex-cli"}) == ("openai", None)
    assert independence.infer_family({"type": "cursor-cli"}) == ("unknown", None)   # 默认模型不定
    # cursor 显式配 sonnet → 归 anthropic 族
    assert independence.infer_family({"type": "cursor-cli", "model": "sonnet-4"})[0] == "anthropic"


# ── analyze ───────────────────────────────────────────────────────────────

def test_judge_overlap_external_same_family_as_host():
    # 宿主 claude（anthropic 主裁）+ 外部席走 claude-cli 或 sonnet → 同族
    warns = independence.analyze("claude", {
        "via_cursor": {"type": "cursor-cli", "model": "sonnet-4"},
        "ds": _api("deepseek-chat", "https://api.deepseek.com/v1"),
    })
    codes = {w["code"] for w in warns}
    assert "judge_overlap" in codes
    hi = [w for w in warns if w["code"] == "judge_overlap"][0]
    assert hi["level"] == "high" and "via_cursor" in hi["seats"]


def test_pool_same_family_flagged_high():
    warns = independence.analyze("claude", {
        "gpt_a": _api("gpt-5", "https://api.openai.com/v1"),
        "gpt_b": _api("gpt-4o", "https://other-gateway.example/v1"),  # 异网关但同族
    })
    fam = [w for w in warns if w["code"] == "pool_same_family"]
    assert fam and fam[0]["level"] == "high"
    assert set(fam[0]["seats"]) == {"gpt_a", "gpt_b"}


def test_user_real_config_same_gateway_ark():
    """用户真实配置：host=claude，glm/deepseek/minimax 三席异族但同 ark 网关 → 三条 same_gateway。"""
    ark = "https://ark.cn-beijing.volces.com/api/coding/v3"
    warns = independence.analyze("claude", {
        "glm": _api("glm-5.2", ark),
        "deepseek": _api("deepseek-v4-pro", ark),
        "minimax": _api("minimax-m3", ark),
    })
    gw = [w for w in warns if w["code"] == "pool_same_gateway"]
    assert len(gw) == 3                                   # C(3,2)=3 对同网关
    assert all(w["level"] == "medium" for w in gw)
    assert not [w for w in warns if w["code"] == "judge_overlap"]   # 三族均非 anthropic
    assert not [w for w in warns if w["code"] == "family_unknown"]  # 均显式配 model


def test_cli_unknown_model_flagged():
    warns = independence.analyze("claude", {"cur": {"type": "cursor-cli"}})
    assert any(w["code"] == "family_unknown" and "cur" in w["seats"] for w in warns)


def test_fully_heterogeneous_pool_no_warning():
    warns = independence.analyze("claude", {
        "ds": _api("deepseek-chat", "https://api.deepseek.com/v1"),
        "qwen": _api("qwen-max", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    })
    assert warns == []                                   # 异族 + 异网关 + 非 anthropic → 全独立
    assert "✅" in independence.render(warns)


def test_render_lists_warnings():
    warns = independence.analyze("claude", {"c": {"type": "claude-cli"}})
    out = independence.render(warns)
    assert "⚠️" in out and "judge_overlap" not in out    # render 出人读文案而非 code
    assert "同族" in out
