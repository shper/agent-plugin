"""Provider 抽象：把 codex / cursor CLI 与 OpenAI 兼容 API 统一成 `ask(prompt) -> text`。

上层（会诊等）只认 `Provider.ask`，不关心底下是 subprocess CLI 还是 HTTP API。
所有 CLI transport 一律走只读/问答模式——会诊角色是纯讨论，绝不让它改文件或跑命令。

留痕（to-consult/consult-common.md §7）：每个 Provider 另暴露 `request_repr(prompt) -> dict`，给出**已脱敏、
可序列化**的请求描述（CLI 的命令行 / API 的请求行），供 consult_log 记录。脱敏铁律：API 永不
吐 api_key、不吐 messages 正文；CLI 命令行里 prompt 用占位符（正文由 consult_log 另记一次）。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

import httpx

# CLI 调用统一超时（秒）。外部模型推理较慢，给足余量。
_DEFAULT_TIMEOUT = 120.0


class Provider(ABC):
    """外部模型来源的统一契约。一个 [providers.<id>] 配置对应一个实例。"""

    def __init__(self, pid: str, conf: dict[str, Any]) -> None:
        self.pid = pid
        self.conf = conf
        self.model: str | None = conf.get("model")

    @abstractmethod
    async def ask(self, prompt: str, *, timeout: float = _DEFAULT_TIMEOUT) -> str:
        """把 prompt 发给模型，返回纯文本应答。失败抛 RuntimeError。"""
        ...

    @abstractmethod
    def request_repr(self, prompt: str) -> dict[str, Any]:
        """返回**已脱敏、可序列化**的请求描述（供留痕）。不发起网络、不含密钥。"""
        ...


class CliProvider(Provider):
    """CLI 子进程类 provider 的公共逻辑：子类只定义 `_build_cmd`，`ask` / `request_repr` 共用。

    约定：`_build_cmd` 把完整 prompt 作为**末项** append（request_repr 据此把它换成占位符）。
    """

    def _build_cmd(self, prompt: str) -> list[str]:
        raise NotImplementedError

    async def ask(self, prompt: str, *, timeout: float = _DEFAULT_TIMEOUT) -> str:
        return await _run_cli(self._build_cmd(prompt), timeout=timeout, pid=self.pid)

    def request_repr(self, prompt: str) -> dict[str, Any]:
        cmd = self._build_cmd(prompt)
        # 末项是完整 prompt——换占位避免命令行复述巨型 prompt（正文由 consult_log 另记一次）。
        safe = cmd[:-1] + [f"<prompt:{len(prompt)}字>"] if cmd else cmd
        return {"transport": "cli", "cmd": safe}


class CodexCliProvider(CliProvider):
    """走 `codex exec`：只读沙箱 + ephemeral + 不吃用户 config/rules，复用 ChatGPT 登录态，无需 key。"""

    def _build_cmd(self, prompt: str) -> list[str]:
        cmd = [
            "codex", "exec",
            "--sandbox", "read-only",   # 即便模型生成命令也只读
            "--ephemeral",              # 不落 session 到 ~/.codex
            "--ignore-user-config",     # 不吃个人 config/hooks
            "--ignore-rules",           # 不吃项目 rules → 行为可复现
        ]
        if self.model:
            cmd += ["-m", self.model]
        cmd.append(prompt)
        return cmd


class CursorCliProvider(CliProvider):
    """走 `cursor-agent -p --mode ask`：只读问答，复用 Cursor 登录态，无需 key。

    `--model` 可在 gpt-5 / sonnet-4 / sonnet-4-thinking 间切（`cursor-agent --list-models` 查）。
    """

    def _build_cmd(self, prompt: str) -> list[str]:
        cmd = [
            "cursor-agent", "-p",            # 非交互打印模式
            "--output-format", "text",
            "--mode", "ask",                 # 只读 Q&A，不写文件不跑命令
            "-f",                            # 信任当前工作区，跳过交互式 Workspace Trust 提示（ask 模式仍只读）
        ]
        if self.model:
            cmd += ["--model", self.model]
        cmd.append(prompt)
        return cmd


class ClaudeCliProvider(CliProvider):
    """走 `claude -p --permission-mode plan`：print 非交互 + plan 只读（不写文件/不跑命令），

    复用 Claude Code 登录态，无需 key。用途：非 Claude 宿主（Codex / Cursor）下让
    Claude 当外部盲区声音——对称补全 codex / cursor，使会诊在任何宿主都能跨底座互补。
    `--model` 可选；缺省用 claude 默认模型。
    """

    def _build_cmd(self, prompt: str) -> list[str]:
        cmd = [
            "claude", "-p",                  # print 模式，非交互
            "--permission-mode", "plan",     # 只读规划：不写文件、不跑命令
        ]
        if self.model:
            cmd += ["--model", self.model]
        cmd.append(prompt)
        return cmd


class OpenAICompatProvider(Provider):
    """走 OpenAI 兼容 `/v1/chat/completions`（httpx 异步）。覆盖 OpenAI / DeepSeek / ollama 等。"""

    def _endpoint(self) -> str:
        return f"{str(self.conf['base_url']).rstrip('/')}/chat/completions"

    async def ask(self, prompt: str, *, timeout: float = _DEFAULT_TIMEOUT) -> str:
        api_key = self.conf.get("api_key") or ""
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(self._endpoint(), json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            raise RuntimeError(f"[{self.pid}] HTTP {e.response.status_code}: {body}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"[{self.pid}] 网络错误: {e}") from e
        return data["choices"][0]["message"]["content"]

    def request_repr(self, prompt: str) -> dict[str, Any]:
        # 铁律：不吐 api_key、不吐 messages 正文（即 prompt，consult_log 另记一次）。
        return {
            "transport": "api",
            "method": "POST",
            "url": self._endpoint(),
            "model": self.model,
            "stream": False,
            "auth": "bearer(已隐藏)" if self.conf.get("api_key") else "none",
            "prompt_chars": len(prompt),
        }


async def _run_cli(cmd: list[str], *, timeout: float, pid: str) -> str:
    """异步跑 CLI 子进程，返回 stdout。超时杀进程，非零退出码抛错。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"[{pid}] CLI 超时 ({timeout}s): {' '.join(cmd[:2])}")
    if proc.returncode != 0:
        raise RuntimeError(
            f"[{pid}] CLI 退出码 {proc.returncode}: {err.decode(errors='replace')[:300]}"
        )
    return out.decode(errors="replace").strip()


_TYPE_MAP: dict[str, type[Provider]] = {
    "claude-cli": ClaudeCliProvider,
    "codex-cli": CodexCliProvider,
    "cursor-cli": CursorCliProvider,
    "openai-compat": OpenAICompatProvider,
}


def build_provider(pid: str, conf: dict[str, Any]) -> Provider:
    """按 conf['type'] 构造对应 Provider。未知 type 抛 ValueError。"""
    ptype = conf.get("type")
    cls = _TYPE_MAP.get(ptype)
    if cls is None:
        raise ValueError(
            f"未知 provider type: {ptype!r}（provider={pid}）。可选：{sorted(_TYPE_MAP)}"
        )
    return cls(pid, conf)
