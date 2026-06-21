"""读取 ai_client 的 env.toml —— 缺失时自动从 example.env.toml 初始化并提醒填 base_url/key。

纯标准库（tomllib，Python 3.11+），不依赖 httpx；httpx 只在 providers 的 API transport 用到。
插件化后：插件目录是共享只读资产，密钥不塞进去——配置统一落在用户主目录 ~/.agent-plugin/env.toml，
与插件安装目录解耦（跨版本升级不丢配置）。
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent
_EXAMPLE = _DIR / "example.env.toml"

# 默认配置位置：与插件安装目录解耦，放用户主目录下的固定点。
_DEFAULT_CONFIG = Path.home() / ".agent-plugin" / "env.toml"


def _config_path() -> Path:
    """解析 env.toml 位置：显式 CONSULT_ENV_TOML 覆盖 > 默认 ~/.agent-plugin/env.toml。"""
    explicit = os.environ.get("CONSULT_ENV_TOML")
    return Path(explicit) if explicit else _DEFAULT_CONFIG


def _bootstrap_config(config: Path) -> None:
    """首次运行：把模板复制到目标位置，并提醒用户设置 base_url 与 key。"""
    config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_EXAMPLE, config)
    print(
        f"[ai_client] 首次运行：已从模板初始化配置 → {config}\n"
        f"  · CLI provider（claude / codex / cursor）零 key，开箱即用；\n"
        f"  · 如需 openai-compat 厂商（OpenAI / DeepSeek / ollama …），请编辑该文件填 base_url 与 api_key：\n"
        f"      $EDITOR {config}",
        file=sys.stderr,
    )


def load_config() -> dict[str, Any]:
    """加载 env.toml；不存在则从模板复制并提醒，再继续加载。"""
    config = _config_path()
    if not config.exists():
        _bootstrap_config(config)
    with config.open("rb") as f:
        return tomllib.load(f)


def get_providers(conf: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """返回 {provider_id: provider_conf} 映射。"""
    return conf.get("providers", {})


def get_consult(conf: dict[str, Any]) -> dict[str, Any]:
    """返回 [to-consult] 段（roster 选择等）。"""
    return conf.get("to-consult", {})


# ── 内联 ad-hoc provider spec（consult-common §9「host 交互降级」载体）──────────
# env 不可用（未配 / 失效）时，会诊降级到「探测 host 可用模型 → 让用户逐角色选」。
# 用户选中的 host 模型不写任何 toml，而是当 `<type>:<model>` 内联 spec 透传给
# cli.py / orchestrate.py 的 `--provider`/`--pro`/... ——零写盘、用完即弃、显式可见。
# 仅限零 key 的 host CLI 底座：openai-compat 需 base_url+api_key、不能凭空内联（须配 [providers.*]）。
_INLINE_CLI_TYPES = {"claude-cli", "codex-cli", "cursor-cli"}
# model 段字符白名单：虽走 argv 列表（不进 shell）无注入风险，仍兜防异常字符。
_MODEL_RE = re.compile(r"^[\w.\-]+$")


def parse_inline_spec(spec: str) -> dict[str, Any] | None:
    """`'claude-cli:opus' -> {'type':'claude-cli','model':'opus'}`；
    `'cursor-cli:' -> {'type':'cursor-cli'}`（空 model = 用工具默认主模型）。

    非内联 spec（无 `:` / type 不在白名单 / model 含非法字符）返回 None。
    """
    if ":" not in spec:
        return None
    head, _, model = spec.partition(":")
    if head not in _INLINE_CLI_TYPES:
        return None
    if model and not _MODEL_RE.match(model):
        return None
    conf: dict[str, Any] = {"type": head}
    if model:
        conf["model"] = model
    return conf


def resolve_provider(spec: str, provs: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """把一个 provider 标识解析成 `(pid, conf)`：先查 `[providers.<spec>]`，
    否则尝试内联 spec。两条路都不中返回 None（调用方据此报「未知 provider」）。

    pid 用 spec 原文（含内联 `type:model`）当留痕 / independence 的席位标识——
    故 `cursor-cli:gpt-5` 在 session.md 与同源检测里都能被正确识别（infer_family 只读 type+model）。
    """
    if spec in provs:
        return spec, provs[spec]
    conf = parse_inline_spec(spec)
    if conf is not None:
        return spec, conf
    return None
