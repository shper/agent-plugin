# /// script
# requires-python = ">=3.11"
# ///
"""跨底座独立性检测（to-consult C4）——静态推断模型族/网关，检出池内或与主裁的重合。

定位（consult-common §0/§1/§8）：会诊的立身之本是「不同源对抗 / 盲区互补」，但 external_voices
池只是 toml 数组、从无校验。名义「跨厂商」可能实质同源（同模型族、或同一推理网关），此时多模型
会诊退化成**伪交叉验证背书**——比单模型更危险（用户以为拿到独立第三方意见，实则同质共识）。

独立性由**模型族**决定，不由网关决定——同一个聚合网关（ark / OpenRouter 等）后面挂的
若是不同组织、不同训练数据/RLHF 的模型（如智谱 glm vs deepseek vs minimax），盲区天然不同、
视角仍独立。故本模块只把**模型族重合**当独立性风险，**同网关仅作可用性提示**（不计折扣）。

本模块从 provider 配置**静态**推断每席的模型族 + 来源网关（零网络、不发请求）：
  独立性风险（high）：① 外部席与主裁（宿主主模型）同族 → 非独立第三方；② 池内两席同模型族 → 盲区互补名不副实；
  提示（low，不计折扣）：③ 某席模型族未知（CLI 默认未配 model）→ 无法确认；④ 池内两席同推理网关 → 仅可用性相关（一起挂时同时降级）。

非阻塞：只产告警供主裁如实暴露，绝不阻断会诊（consult-common §9「增益不是依赖」）。
被 orchestrate.py 顶层 import（纯标准库，不破坏「无 httpx 单测」），也可作 CLI 供 panel Step 4 调。

用法（CLI）：
  uv run "$ROOT/ai_client/independence.py" --host claude --pool glm,deepseek,minimax
  → 人读告警 + 末行 `INDEPENDENCE: ok|warn(N)`；exit 0 恒成立（非阻塞）。
"""

from __future__ import annotations

import argparse
import sys
from typing import Any
from urllib.parse import urlsplit

# 模型名子串 → 厂商/模型族。命中即归类（小写子串匹配，首个命中为准）。
_FAMILY_SUBSTR: list[tuple[tuple[str, ...], str]] = [
    (("gpt", "o1-", "o3-", "o4-", "chatgpt", "davinci"), "openai"),
    (("claude", "sonnet", "opus", "haiku"), "anthropic"),
    (("deepseek",), "deepseek"),
    (("glm", "chatglm"), "zhipu"),
    (("qwen", "tongyi"), "alibaba"),
    (("minimax", "abab"), "minimax"),
    (("gemini", "palm"), "google"),
    (("llama",), "meta"),
    (("mistral", "mixtral", "magistral"), "mistral"),
    (("moonshot", "kimi"), "moonshot"),
    (("doubao",), "bytedance"),
    (("grok",), "xai"),
]

# CLI transport → 其默认厂商族（model 缺省时用工具主模型；cursor 默认模型不定 → unknown）。
_CLI_FAMILY: dict[str, str] = {
    "claude-cli": "anthropic",
    "codex-cli": "openai",
    "cursor-cli": "unknown",   # cursor 默认可在 gpt-5 / sonnet 间切，静态不可知
}

# 宿主主模型（主裁）所属族。
_HOST_FAMILY: dict[str, str] = {
    "claude": "anthropic",
    "codex": "openai",
    "cursor": "unknown",       # 同 cursor-cli
}


def _family_from_model(model: str | None) -> str:
    if not model:
        return "unknown"
    m = model.lower()
    for needles, fam in _FAMILY_SUBSTR:
        if any(n in m for n in needles):
            return fam
    return "unknown"


def host_family(host: str) -> str:
    return _HOST_FAMILY.get((host or "").lower(), "unknown")


def infer_family(conf: dict[str, Any]) -> tuple[str, str | None]:
    """返回 (模型族, 推理网关 host)。CLI transport 无网关 → None。

    openai-compat 优先按 model 名判族，网关取 base_url 的 netloc（同网关=同推理服务/安全栈）。
    CLI transport 显式配了 model 就按 model 判族，否则用工具默认族（cursor 为 unknown）。
    """
    ptype = conf.get("type", "")
    model = conf.get("model")
    if ptype == "openai-compat":
        fam = _family_from_model(model)
        gw = urlsplit(str(conf.get("base_url", ""))).netloc or None
        return fam, gw
    # CLI transport
    fam = _family_from_model(model) if model else _CLI_FAMILY.get(ptype, "unknown")
    return fam, None


def _warn(code: str, level: str, msg: str, seats: list[str]) -> dict[str, Any]:
    return {"code": code, "level": level, "msg": msg, "seats": seats}


def analyze(host: str, seats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """检出外部席与主裁/彼此的同源重合，返回告警列表（空=各席独立，未检出重合）。"""
    hf = host_family(host)
    info: dict[str, tuple[str, str | None]] = {pid: infer_family(c) for pid, c in seats.items()}
    warns: list[dict[str, Any]] = []

    # ① 外部席与主裁同族
    for pid, (fam, _gw) in info.items():
        if fam != "unknown" and hf != "unknown" and fam == hf:
            warns.append(_warn(
                "judge_overlap", "high",
                f"外部席「{pid}」与主裁同族（{fam}）——非独立第三方，等于主裁家族给自己背书", [pid],
            ))

    # ②③ 池内两两比较：同族（高）优先于同网关（中）
    pids = list(info)
    for i in range(len(pids)):
        for j in range(i + 1, len(pids)):
            a, b = pids[i], pids[j]
            (fa, ga), (fb, gb) = info[a], info[b]
            if fa != "unknown" and fa == fb:
                warns.append(_warn(
                    "pool_same_family", "high",
                    f"池内「{a}」与「{b}」同模型族（{fa}）——盲区互补名不副实", [a, b],
                ))
            elif ga and ga == gb:
                # 同网关 ≠ 同源：模型族不同则视角仍独立，这里只作可用性提示、不计独立性折扣。
                warns.append(_warn(
                    "shared_gateway", "low",
                    f"池内「{a}」与「{b}」同推理网关（{ga}）——模型族不同、视角仍独立（不计独立性折扣）；"
                    "仅提示可用性相关：该网关故障会令两席同时降级", [a, b],
                ))

    # ④ 模型族未知
    for pid, (fam, _gw) in info.items():
        if fam == "unknown":
            warns.append(_warn(
                "family_unknown", "low",
                f"「{pid}」模型族未知（CLI 默认未配 model 或无法识别）——无法确认与主裁/他席是否同源，建议显式配 model",
                [pid],
            ))
    if hf == "unknown":
        warns.append(_warn(
            "host_unknown", "low",
            f"主裁宿主「{host or '(未知)'}」模型族未知——无法判定外部席是否与主裁同族", [],
        ))
    return warns


_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def risks(warns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """真正损害独立性的项（high）——模型族 / 与主裁同族；同网关等 low 项不算。"""
    return [w for w in warns if w["level"] == "high"]


def render(warns: list[dict[str, Any]]) -> str:
    hi = risks(warns)
    notes = [w for w in warns if w["level"] != "high"]
    lines: list[str] = []
    if hi:
        lines.append("⚠️ 跨底座独立性风险（多模型会诊可能退化为伪交叉验证背书）：")
        lines += [f"  {_ICON['high']} {w['msg']}" for w in hi]
        lines.append("→ 主裁收口时须对相关席位标注同源折扣，重合严重者按 consult-common §9 流产。")
    else:
        lines.append("✅ 跨底座独立性：各外部席与主裁均无模型族重合，未发现伪交叉验证风险。")
    if notes:
        lines.append("提示（不计独立性折扣）：")
        lines += [f"  {_ICON.get(w['level'], '·')} {w['msg']}" for w in notes]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="跨底座独立性检测（to-consult C4）")
    parser.add_argument("--host", default="", help="宿主 claude|codex|cursor（主裁底座）")
    parser.add_argument("--pool", required=True, help="外部声音池 provider id，逗号分隔")
    args = parser.parse_args()

    try:
        from config import get_providers, load_config  # 延迟 import：CLI 才需要读盘
        provs = get_providers(load_config())
    except Exception as e:  # noqa: BLE001 —— 非阻塞：读配置失败也别拦会诊
        print(f"[independence] 读取配置失败（跳过检测，不阻断）：{e}", file=sys.stderr)
        print("INDEPENDENCE: skipped")
        return 0

    pool = [p.strip() for p in args.pool.split(",") if p.strip()]
    seats = {pid: provs[pid] for pid in pool if pid in provs}
    missing = [pid for pid in pool if pid not in provs]
    if missing:
        print(f"[independence] 池内未知 provider（跳过这些）：{missing}", file=sys.stderr)

    warns = analyze(args.host, seats)
    print(render(warns))
    n = len(risks(warns))   # 只有 high（模型族/主裁同族）才算独立性风险；同网关等 low 项不计
    print(f"INDEPENDENCE: {'warn(' + str(n) + ')' if n else 'ok'}")
    return 0  # 恒 0：检测是增益不是门禁


if __name__ == "__main__":
    raise SystemExit(main())
