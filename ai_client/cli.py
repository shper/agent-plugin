# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.28"]
# ///
"""ai_client CLI 入口 —— 调外部模型，stdout 返回纯文本。

由会诊的主 Agent 走 Bash 调用（ROOT = 插件根；CLAUDE_PLUGIN_ROOT/PLUGIN_ROOT 仅 hook 环境可靠，skill 内由主会话据 skill 目录上两级代入，手动跑则自行 export 或在插件根下跑）：
    uv run "$ROOT/ai_client/cli.py" --provider cursor --task <t> --mode panel --role 外部视角 "<角色 prompt>"
    uv run "$ROOT/ai_client/cli.py" --provider qwen --task <t> --file path/to/doc.md "分析这份文档"

uv 读本文件头部 PEP 723 内联依赖，自动建隔离环境装 httpx；不污染系统 python。
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
import sys
import time
from datetime import datetime
from pathlib import Path

import consult_log
from config import get_providers, load_config
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


async def _run() -> int:
    parser = argparse.ArgumentParser(description="ai_client：调外部模型并返回文本")
    parser.add_argument("--provider", required=True, help=".env.toml 里的 provider id")
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
    args = parser.parse_args()

    try:
        conf = load_config()
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2

    providers = get_providers(conf)
    if args.provider not in providers:
        print(
            f"未知 provider: {args.provider!r}。可选：{sorted(providers)}",
            file=sys.stderr,
        )
        return 2

    try:
        prompt = _embed_files(args.prompt, args.files) if args.files else args.prompt
    except OSError as e:
        print(e, file=sys.stderr)
        return 2

    task = args.task or _fallback_task()
    if not args.task:
        print(f"[consult_log] 未传 --task，留痕落到兜底目录 {task}", file=sys.stderr)

    provider = build_provider(args.provider, providers[args.provider])
    request = provider.request_repr(prompt)
    started = time.monotonic()
    try:
        text = await provider.ask(prompt, timeout=args.timeout)
    except Exception as e:  # noqa: BLE001 —— CLI 边界，统一转非零退出
        consult_log.record_call(
            task=task, mode=args.mode, provider=args.provider, request=request,
            prompt=prompt, error=str(e), role=args.role, model=provider.model,
            duration=time.monotonic() - started,
        )
        print(f"调用失败: {e}", file=sys.stderr)
        return 1

    consult_log.record_call(
        task=task, mode=args.mode, provider=args.provider, request=request,
        prompt=prompt, response=text, role=args.role, model=provider.model,
        duration=time.monotonic() - started,
    )
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
