"""cli.probe-models 解析单测（cursor --list-models stdout → 裸模型名）。

cli 顶层 import providers → httpx，故无 httpx 环境跳过（与 conftest「无 httpx 单测」约定一致）。
"""

from __future__ import annotations

import pytest

pytest.importorskip("httpx")

import cli  # noqa: E402


def test_parse_cursor_models_real_format():
    # 实测格式：'Available models' 标题 + 每行 '<id> - <描述>'
    out = (
        "Available models\n\n"
        "auto - Auto\n"
        "gpt-5.2 - GPT-5.2\n"
        "gpt-5.3-codex-low - Codex 5.3 Low\n"
        "claude-opus-4-8-thinking-high - Opus 4.8 1M Thinking\n"
    )
    assert cli._parse_cursor_models(out) == [
        "auto", "gpt-5.2", "gpt-5.3-codex-low", "claude-opus-4-8-thinking-high",
    ]


def test_parse_cursor_models_plain_lines_fallback():
    # 无 ' - ' 描述时整行当裸 id（格式漂移兜底）
    out = "gpt-5\nsonnet-4\nsonnet-4-thinking\n"
    assert cli._parse_cursor_models(out) == ["gpt-5", "sonnet-4", "sonnet-4-thinking"]


def test_parse_cursor_models_strips_bullets_and_dedups():
    out = "* gpt-5 - GPT 5\n• gpt-5 - dup\nsonnet-4 - Sonnet\n"
    assert cli._parse_cursor_models(out) == ["gpt-5", "sonnet-4"]


def test_parse_cursor_models_skips_headers():
    assert cli._parse_cursor_models("Available models\n\n") == []
    assert cli._parse_cursor_models("") == []
