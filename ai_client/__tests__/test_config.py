"""config 内联 provider spec 解析单测（consult-common §9 host 交互降级载体）。

只测纯函数 parse_inline_spec / resolve_provider，不读盘、不碰 httpx。
"""

from __future__ import annotations

import config


# ── parse_inline_spec ──────────────────────────────────────────────────────

def test_inline_spec_with_model():
    assert config.parse_inline_spec("claude-cli:opus") == {"type": "claude-cli", "model": "opus"}
    assert config.parse_inline_spec("cursor-cli:gpt-5") == {"type": "cursor-cli", "model": "gpt-5"}


def test_inline_spec_empty_model_uses_default():
    # 空 model = 用工具默认主模型，conf 不带 model 字段
    assert config.parse_inline_spec("cursor-cli:") == {"type": "cursor-cli"}
    assert config.parse_inline_spec("codex-cli:") == {"type": "codex-cli"}


def test_inline_spec_rejects_non_cli_type():
    # openai-compat 需 base_url+api_key，不能内联
    assert config.parse_inline_spec("openai-compat:gpt-4") is None
    assert config.parse_inline_spec("bogus-cli:x") is None


def test_inline_spec_rejects_plain_id_and_bad_model():
    assert config.parse_inline_spec("deepseek") is None          # 无冒号 → 非内联
    assert config.parse_inline_spec("claude-cli:o pus") is None  # model 含空格
    assert config.parse_inline_spec("claude-cli:a/b") is None    # model 含路径分隔


# ── resolve_provider ───────────────────────────────────────────────────────

def test_resolve_prefers_configured_id():
    provs = {"deepseek": {"type": "openai-compat", "model": "deepseek-v4"}}
    assert config.resolve_provider("deepseek", provs) == (
        "deepseek", {"type": "openai-compat", "model": "deepseek-v4"})


def test_resolve_falls_back_to_inline_spec():
    pid, conf = config.resolve_provider("claude-cli:opus", {})
    assert pid == "claude-cli:opus"           # pid 保留原文，供留痕/independence 识别
    assert conf == {"type": "claude-cli", "model": "opus"}


def test_resolve_configured_id_wins_even_if_colon():
    # 配置 id 优先于内联解析（理论上 id 含冒号也先查 provs）
    provs = {"claude-cli:opus": {"type": "openai-compat", "base_url": "x", "model": "custom"}}
    pid, conf = config.resolve_provider("claude-cli:opus", provs)
    assert conf["type"] == "openai-compat"


def test_resolve_unknown_returns_none():
    assert config.resolve_provider("deepseek", {}) is None
    assert config.resolve_provider("nope", {"glm": {}}) is None
