# /// script
# requires-python = ">=3.11"
# ///
"""会诊留痕 —— 把一次 to-consult / ai_client「任务」的过程强制落到磁盘。

定位（to-consult/consult-common.md §7）：
  会诊引擎的产出（外部模型那次**不可复现**的生响应、用了哪些模型、发起的命令行/API 请求、
  主裁收口结论）默认只进 stdout、跑完即丢。本模块是所有留痕的**单一写入点**，把它们
  追加到 `<宿主项目根>/.consult-cache/to-consult/<任务名>/session.md`（宿主项目 gitignore，属过程留痕≠产出落盘）。

三条写入路径都走这里，统一 markdown 拼装与脱敏：
  ① start    —— 主会话编排前调一次：建 `<时间戳>_<slug>/session.md` 头部，stdout 回显任务名。
  ② record_call —— cli.py / orchestrate.py 每次外部调用自动 append（请求 + prompt + 生响应）。
  ③ verdict  —— 主会话收口后调：append 主裁收口结论（正文从 stdin 读）。

边界：
  - 纯标准库（datetime / pathlib / argparse / re），无三方依赖——可被 orchestrate 顶层 import 而不破坏「无 httpx 单测」。
  - 脱敏：API 请求**绝不含 api_key**、不含 messages 正文；命令行里 prompt 用占位符，正文另记一次。
  - **非阻塞**：record_* 写盘失败只 warn 到 stderr，绝不抛错中断会诊（对齐 to-consult/consult-common.md §9「增益不是依赖」）。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# 留痕根目录（插件化后必须落到「宿主项目」而非插件安装目录）。优先级：
#   显式 CONSULT_CACHE_DIR > Claude Code 注入的 CLAUDE_PROJECT_DIR（宿主项目根）> 当前工作目录。
# Codex 不注入项目根变量，靠 cwd 兜底——故主会话调脚本时**不要** cd 进插件根，保持 cwd = 宿主项目。
# 不假设宿主有 `.harness/`，统一落 `<root>/.consult-cache/to-consult/`（宿主项目自行 gitignore）。
_root = (
    os.environ.get("CONSULT_CACHE_DIR")
    or os.environ.get("CLAUDE_PROJECT_DIR")
    or os.getcwd()
)
_CACHE_DIR = Path(_root) / ".consult-cache" / "to-consult"

# prompt 全文可能嵌入整份文档而失控；超过此长度记首尾 + 标注省略（生响应不截断——那是核心产出）。
_PROMPT_MAX = 4000


# ── 时间 / 路径工具 ────────────────────────────────────────────────────────

def _ts() -> str:
    """任务名时间戳前缀（可排序、文件名安全）。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _clock() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sanitize(name: str) -> str:
    """目录名净化：杀路径分隔 / `..` 穿越 / 控制字符；保留中英文、数字、`.-_`。空则 `unnamed`。"""
    name = (name or "").strip().replace("\x00", "")
    name = re.sub(r"[\\/]+", "-", name)          # 路径分隔 → -
    name = re.sub(r"\.\.+", ".", name)            # 连续点（含 ..）→ 单点，杀穿越
    name = re.sub(r"\s+", "-", name)              # 空白 → -
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)   # 控制字符
    name = name.strip(".-")                        # 首尾点 / 连字符
    return name or "unnamed"


def session_file(task: str) -> Path:
    """某任务的留痕文件路径（不创建）。"""
    return _CACHE_DIR / _sanitize(task) / "session.md"


def _truncate(text: str | None, limit: int = _PROMPT_MAX) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    head, tail = text[: limit * 2 // 3], text[-(limit // 3):]
    return f"{head}\n…<已截断，共 {len(text)} 字，省略中段>…\n{tail}"


# ── markdown 渲染 ─────────────────────────────────────────────────────────

def _render_header(task: str, mode: str, trigger: str, host: str, models: str) -> str:
    return (
        f"# to-consult 留痕 · {task}\n"
        f"- 启动时间: {_stamp()}\n"
        f"- 启动模式: {mode or '(未提供)'}\n"
        f"- 启动提示词: {trigger or '(未提供)'}\n"
        f"- 宿主: {host or '(未提供)'}\n"
        f"- 参与模型: {models or '(未提供)'}\n"
    )


def _fmt_request(request: dict | None) -> str:
    """把脱敏请求 dict 渲染成单行命令行 / API 请求描述。"""
    if not request:
        return "(无请求信息)"
    transport = request.get("transport")
    if transport == "cli":
        return " ".join(str(x) for x in request.get("cmd", []))
    if transport == "api":
        return (
            f"{request.get('method', 'POST')} {request.get('url', '')}  "
            f"model={request.get('model')}  auth={request.get('auth', 'none')}  "
            f"prompt_chars={request.get('prompt_chars')}"
        )
    return str(request)


def _render_call(
    *, mode: str, role: str, provider: str, model: str | None,
    request: dict | None, prompt: str, response: str | None,
    error: str | None, duration: float | None,
) -> str:
    status = "error" if error else "ok"
    dur = f"{duration:.1f}s" if isinstance(duration, (int, float)) else "-"
    role_s = f"【{role}】" if role else "—"
    transport = (request or {}).get("transport", "?")
    lines = [
        "",
        f"## [{_clock()}] {mode} · {role_s} · {provider} (model={model or '默认'}) · {status} · {dur}",
        f"**请求** ({transport}):",
        f"`{_fmt_request(request)}`",
        "**prompt**:",
        "```text",
        _truncate(prompt),
        "```",
    ]
    if error:
        lines += ["**错误**:", str(error), ""]
    else:
        lines += ["**生响应**:", response if response is not None else "(空)", ""]
    return "\n".join(lines) + "\n"


# ── 写入（全部非阻塞：失败只 warn，不抛）──────────────────────────────────

def _warn(e: object) -> None:
    print(f"[consult_log] 留痕失败（不中断会诊）: {e}", file=sys.stderr)


def _ensure_header(task: str, mode: str) -> None:
    """record_* 兜底：主会话漏调 start 时也保证有头部。已存在则不动。"""
    path = session_file(task)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _render_header(task, mode, "(由脚本兜底创建，未经 start)", "", ""),
        encoding="utf-8",
    )


def start(*, slug: str, mode: str, trigger: str = "", host: str = "", models: str = "") -> str:
    """建会话留痕文件，返回完整任务名 `<时间戳>_<slug>`（CLI 打到 stdout 供主会话捕获）。"""
    task = f"{_ts()}_{_sanitize(slug)}"
    path = session_file(task)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_header(task, mode, trigger, host, models), encoding="utf-8")
    return task


def record_call(
    *, task: str, mode: str, provider: str, request: dict | None, prompt: str,
    response: str | None = None, error: str | None = None,
    role: str = "", model: str | None = None, duration: float | None = None,
) -> None:
    """追加一段外部调用记录（请求 + prompt + 生响应/error）。非阻塞。"""
    try:
        _ensure_header(task, mode)
        block = _render_call(
            mode=mode, role=role, provider=provider, model=model,
            request=request, prompt=prompt, response=response,
            error=error, duration=duration,
        )
        with session_file(task).open("a", encoding="utf-8") as f:
            f.write(block)
    except Exception as e:  # noqa: BLE001 —— 留痕是增益，绝不阻断会诊
        _warn(e)


def record_verdict(*, task: str, mode: str, verdict: str) -> None:
    """追加主裁收口结论段。非阻塞。"""
    try:
        _ensure_header(task, mode)
        block = (
            f"\n---\n## 主裁收口结论 · {mode} · [{_clock()}]\n"
            f"{verdict.strip() or '(空)'}\n"
        )
        with session_file(task).open("a", encoding="utf-8") as f:
            f.write(block)
    except Exception as e:  # noqa: BLE001
        _warn(e)


# ── CLI（start / verdict；record_call 仅作库函数供 cli.py / orchestrate.py 调）──

def main() -> int:
    parser = argparse.ArgumentParser(description="会诊留痕：建会话 / 写收口结论")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("start", help="建 <时间戳>_<slug>/session.md 头部，stdout 回显任务名")
    ps.add_argument("--slug", required=True, help="议题 slug（脚本自动加时间戳前缀）")
    ps.add_argument("--mode", required=True, help="启动模式 panel|debate|refine|direct")
    ps.add_argument("--trigger", default="", help="启动提示词（发起本次会诊的原话）")
    ps.add_argument("--host", default="", help="宿主 claude|codex|cursor")
    ps.add_argument("--models", default="", help="席位→模型清单（自由文本）")

    pv = sub.add_parser("verdict", help="追加主裁收口结论（正文从 stdin 读）")
    pv.add_argument("--task", required=True, help="start 回显的任务名")
    pv.add_argument("--mode", required=True, help="启动模式（同 start）")

    args = parser.parse_args()

    if args.cmd == "start":
        task = start(
            slug=args.slug, mode=args.mode, trigger=args.trigger,
            host=args.host, models=args.models,
        )
        print(task)
        return 0

    # verdict：从 stdin 读收口正文（便于大段 markdown）
    verdict = sys.stdin.read()
    record_verdict(task=args.task, mode=args.mode, verdict=verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
