"""读取 ai_client 的 .env.toml —— 缺失时引导复制 example.env.toml。

纯标准库（tomllib，Python 3.11+），不依赖 httpx；httpx 只在 providers 的 API transport 用到。
插件化后：插件目录是共享只读资产，密钥不塞进去——配置位置见 _config_path()。
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent
_EXAMPLE = _DIR / "example.env.toml"


def _config_path() -> Path:
    """解析 .env.toml 位置。优先级：
      显式 CONSULT_ENV_TOML > 插件数据区/.env.toml > 脚本同目录兜底。
    数据区变量 CLAUDE_PLUGIN_DATA / PLUGIN_DATA 仅插件 hook 环境可靠（skill 的普通 Bash 里常为空），
    故 skill 内配 key 建议走 CONSULT_ENV_TOML；缺失时回退脚本同目录 .env.toml。
    """
    explicit = os.environ.get("CONSULT_ENV_TOML")
    if explicit:
        return Path(explicit)
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA") or os.environ.get("PLUGIN_DATA")
    if data_dir:
        return Path(data_dir) / ".env.toml"
    return _DIR / ".env.toml"


def load_config() -> dict[str, Any]:
    """加载 .env.toml；不存在则抛错并提示复制模板。"""
    config = _config_path()
    if not config.exists():
        raise FileNotFoundError(
            f"未找到 {config}。请复制模板并填 key（CLI transport 零 key，仅 openai-compat 厂商需填）：\n"
            f"  cp {_EXAMPLE} {config}\n"
            f"  或设环境变量 CONSULT_ENV_TOML 指向你的配置文件。\n"
            f"  （数据区变量：Claude Code = CLAUDE_PLUGIN_DATA，Codex = PLUGIN_DATA。）"
        )
    with config.open("rb") as f:
        return tomllib.load(f)


def get_providers(conf: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """返回 {provider_id: provider_conf} 映射。"""
    return conf.get("providers", {})


def get_consult(conf: dict[str, Any]) -> dict[str, Any]:
    """返回 [to-consult] 段（roster 选择等）。"""
    return conf.get("to-consult", {})
