"""读取 ai_client 的 env.toml —— 缺失时自动从 example.env.toml 初始化并提醒填 base_url/key。

纯标准库（tomllib，Python 3.11+），不依赖 httpx；httpx 只在 providers 的 API transport 用到。
插件化后：插件目录是共享只读资产，密钥不塞进去——配置统一落在用户主目录 ~/.agent-plugin/env.toml，
与插件安装目录解耦（跨版本升级不丢配置）。
"""

from __future__ import annotations

import os
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
