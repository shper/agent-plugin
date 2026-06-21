# /// script
# requires-python = ">=3.11"
# ///
"""ai_client CLI 入口 —— 调外部模型，stdout 返回纯文本。

由会诊的主 Agent 走 Bash 调用（ROOT = 插件根；CLAUDE_PLUGIN_ROOT/PLUGIN_ROOT 仅 hook 环境可靠，skill 内由主会话据 skill 目录上两级代入，手动跑则自行 export 或在插件根下跑）：
    python3 "$ROOT/ai_client/cli.py" --provider cursor --task <t> --mode panel --role 外部视角 "<角色 prompt>"
    python3 "$ROOT/ai_client/cli.py" --provider qwen --task <t> --file path/to/doc.md "分析这份文档"

纯标准库实现（需 Python ≥ 3.11），裸 python3 直接跑、无第三方依赖；`uv run` 仍可选（自动管 Python 版本与隔离）。
provider id 来自 .env.toml 的 [providers.<id>]。
--file 由本 CLI 读出文件内容嵌入 prompt 前部——所有 transport 通用，尤其 openai-compat（纯 API）
自身无文件访问能力，必须靠这里读出嵌入。

留痕（to-consult/consult-common.md §7）：每次调用都把「请求 + prompt + 生响应」强制 append 到
`<宿主项目根>/.consult-cache/to-consult/<task>/session.md`（consult_log，非阻塞）。`--task` 由主会话
经 `consult_log.py start` 取得；漏传则兜底一个 `<时间戳>_adhoc` 目录，保证必留痕。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import consult_log
from config import get_providers, load_config, resolve_provider
from providers import build_provider


def _embed_files(prompt: str, files: list[str]) -> str:
    """把每个文件内容作为 fenced 上下文块拼到 prompt 前，指令留在末尾（recency）。

    缺失文件抛 FileNotFoundError、读取失败抛 OSError，由调用方转 exit 2。
    """
    blocks: list[str] = []
    for fp in files:
        path = Path(fp)
        if not path.exists():
            raise FileNotFoundError(f"未找到文件: {fp}")
        blocks.append(f"## 待分析材料：{fp}\n```\n{path.read_text(encoding='utf-8')}\n```")
    return "\n\n".join(blocks) + "\n\n---\n\n" + prompt


def _fallback_task() -> str:
    """主会话漏传 --task 时的兜底目录名（保证「必须留痕」不落空）。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "_adhoc"


async def _run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cli.py [ask]",
        description="ai_client：调外部模型并返回文本（缺省子命令；probe-models 见 --help）",
    )
    parser.add_argument("--provider", required=True,
                        help="[providers.<id>] 的 id，或内联 host spec（如 claude-cli:opus / cursor-cli:gpt-5）")
    parser.add_argument("prompt", help="喂给模型的提示词")
    parser.add_argument("--timeout", type=float, default=120.0, help="单次调用超时（秒）")
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        dest="files",
        metavar="PATH",
        help="把文件内容作为上下文嵌入 prompt 前部，可重复；所有 transport 通用",
    )
    parser.add_argument("--task", default="", help="留痕会话目录名（consult_log.py start 取得；漏传则兜底）")
    parser.add_argument("--mode", default="direct", choices=["panel", "direct"],
                        help="留痕标注的启动模式（panel 外部批 / direct 旁路）")
    parser.add_argument("--role", default="", help="留痕标注的角色（如 外部视角）")
    args = parser.parse_args(argv)

    try:
        conf = load_config()
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2

    providers = get_providers(conf)
    resolved = resolve_provider(args.provider, providers)
    if resolved is None:
        print(
            f"未知 provider: {args.provider!r}。可选：{sorted(providers)}"
            "（或内联 host spec，如 claude-cli:opus / cursor-cli:gpt-5）",
            file=sys.stderr,
        )
        return 2
    pid, pconf = resolved

    try:
        prompt = _embed_files(args.prompt, args.files) if args.files else args.prompt
    except OSError as e:
        print(e, file=sys.stderr)
        return 2

    task = args.task or _fallback_task()
    if not args.task:
        print(f"[consult_log] 未传 --task，留痕落到兜底目录 {task}", file=sys.stderr)

    provider = build_provider(pid, pconf)
    request = provider.request_repr(prompt)
    started = time.monotonic()
    try:
        text = await provider.ask(prompt, timeout=args.timeout)
    except Exception as e:  # noqa: BLE001 —— CLI 边界，统一转非零退出
        consult_log.record_call(
            task=task, mode=args.mode, provider=pid, request=request,
            prompt=prompt, error=str(e), role=args.role, model=provider.model,
            duration=time.monotonic() - started,
        )
        print(f"调用失败: {e}", file=sys.stderr)
        return 1

    consult_log.record_call(
        task=task, mode=args.mode, provider=pid, request=request,
        prompt=prompt, response=text, role=args.role, model=provider.model,
        duration=time.monotonic() - started,
    )
    print(text)
    return 0


# ── probe-models 子命令：探测当前 host 可调用的 CLI 模型 ─────────────────────
# env 不可用（未配 / 失效）时，主会话据此 JSON 用 AskUserQuestion 让用户逐角色选 host 模型
# （consult-common §9「host 交互降级」）。探测是增益：恒 exit 0、绝不抛、未装的标 installed:false。

# 三个零 key host CLI 底座。models = 无机器可读列表时的已知别名兜底；list_cmd 有则实跑取真列表。
_PROBE_TOOLS = [
    {"tool": "claude", "bin": "claude", "type": "claude-cli",
     "models": ["opus", "sonnet", "haiku"], "list_cmd": None},
    {"tool": "cursor-agent", "bin": "cursor-agent", "type": "cursor-cli",
     "models": [], "list_cmd": ["cursor-agent", "--list-models"]},
    {"tool": "codex", "bin": "codex", "type": "codex-cli",
     "models": [], "list_cmd": None},
]
# host 身份 → 同底座 CLI type（标 same_base_as_host，供主会话提示「与主裁同源、独立性打折」）。
_HOST_SAME_TYPE = {"claude": "claude-cli", "codex": "codex-cli", "cursor": "cursor-cli"}
_MODEL_TOKEN_RE = re.compile(r"^[\w.\-]+$")


async def _capture(cmd: list[str], *, timeout: float = 20.0) -> tuple[bool, str]:
    """跑一条只读命令取 stdout；失败/超时返回 (False, err)，绝不抛（探测是增益）。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, OSError) as e:
        return False, str(e)
    if proc.returncode != 0:
        return False, err.decode(errors="replace")[:200]
    return True, out.decode(errors="replace")


def _parse_cursor_models(stdout: str) -> list[str]:
    """从 `cursor-agent --list-models` 输出抽模型 id（格式漂移就尽量少误收）。

    实测格式每行 `<model-id> - <人读描述>`（如 `gpt-5.2 - GPT-5.2`），另有 `Available models`
    标题/空行。取 ` - ` 前的 id；无 ` - ` 时整行须是单 token。id 须匹配 [\\w.\\-]、保序去重。
    解析为空 → 调用方回落「用 cursor 默认模型」(cursor-cli: 空 model)。
    """
    models: list[str] = []
    for line in stdout.splitlines():
        s = line.strip().lstrip("*•· \t").strip()
        if not s:
            continue
        head = s.split(" - ", 1)[0].strip() if " - " in s else s
        if " " in head or ":" in head:          # 跳过标题/说明行（如 "Available models"）
            continue
        if _MODEL_TOKEN_RE.match(head) and head not in models:
            models.append(head)
    return models


async def _probe_tool(spec: dict, host: str) -> dict:
    """探测单个 host CLI：装没装、可用模型列表、是否与主裁同底座。绝不抛。"""
    installed = shutil.which(spec["bin"]) is not None
    out = {
        "tool": spec["tool"], "type": spec["type"], "installed": installed,
        "models": list(spec["models"]), "models_unknown": False,
        "same_base_as_host": _HOST_SAME_TYPE.get((host or "").lower()) == spec["type"],
        "note": "",
    }
    if not installed:
        out["note"] = "未安装（which 未找到）"
        out["models_unknown"] = not out["models"]
        return out
    if spec["list_cmd"]:
        ok, text = await _capture(spec["list_cmd"])
        models = _parse_cursor_models(text) if ok else []
        if models:
            out["models"] = models
        else:
            out["models_unknown"] = True
            why = "解析为空" if ok else f"失败：{text[:120]}"
            out["note"] = f"已安装但 --list-models {why}；可用「{spec['type']}:」空 model 走默认主模型"
    elif not out["models"]:
        out["models_unknown"] = True
        out["note"] = f"已安装但无机器可读模型列表，用「{spec['type']}:」空 model 走默认主模型或自填"
    return out


async def probe_models(host: str) -> dict:
    """汇总三个 host CLI 的可用模型，供 AskUserQuestion 逐角色选。恒成功。"""
    tools = await asyncio.gather(*[_probe_tool(s, host) for s in _PROBE_TOOLS])
    return {
        "host": host or None,
        "tools": list(tools),
        "usable_any": any(t["installed"] for t in tools),
    }


async def _run_probe(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="cli.py probe-models",
        description="探测当前 host 可调用的 CLI 模型，输出 JSON（env 不可用时的交互降级用）",
    )
    p.add_argument("--host", default="", help="宿主 claude|codex|cursor（标注 same_base_as_host）")
    args = p.parse_args(argv)
    print(json.dumps(await probe_models(args.host), ensure_ascii=False, indent=2))
    return 0


def _main() -> int:
    """顶层分发：`probe-models` 走探测，其余（含显式 `ask`）走原 ask 路径（向后兼容）。"""
    argv = sys.argv[1:]
    if argv and argv[0] == "probe-models":
        return asyncio.run(_run_probe(argv[1:]))
    if argv and argv[0] == "ask":
        argv = argv[1:]
    return asyncio.run(_run(argv))


if __name__ == "__main__":
    raise SystemExit(_main())
