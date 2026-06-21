"""providers.request_repr 脱敏单测 —— 纯标准库，`python3 -m pytest` 直跑（providers 已无三方依赖）。

脱敏铁律：API request_repr 不含 api_key、不含 messages 正文；CLI cmd 末项是 prompt 占位、不含完整 prompt。
"""

from __future__ import annotations

import providers


def test_api_request_repr_redacts_key_and_body():
    p = providers.OpenAICompatProvider(
        "deepseek",
        {"type": "openai-compat", "base_url": "https://api.deepseek.com/v1",
         "api_key": "sk-SECRET-DO-NOT-LEAK", "model": "deepseek-chat"},
    )
    r = p.request_repr("一段需要分析的长 prompt")
    flat = repr(r)
    assert "sk-SECRET-DO-NOT-LEAK" not in flat        # 绝不泄漏 key
    assert "messages" not in r                          # 不含正文
    assert r["auth"] == "bearer(已隐藏)"
    assert r["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert r["model"] == "deepseek-chat"
    assert r["prompt_chars"] == len("一段需要分析的长 prompt")


def test_api_request_repr_no_key_marks_none():
    p = providers.OpenAICompatProvider(
        "ollama",
        {"type": "openai-compat", "base_url": "http://localhost:11434/v1", "model": "qwen2.5"},
    )
    assert p.request_repr("hi")["auth"] == "none"


def test_cli_request_repr_placeholder_hides_prompt():
    p = providers.CodexCliProvider("codex", {"type": "codex-cli"})
    long_prompt = "x" * 5000
    r = p.request_repr(long_prompt)
    assert r["transport"] == "cli"
    assert r["cmd"][0] == "codex"
    assert r["cmd"][-1] == "<prompt:5000字·stdin>"      # 占位标 stdin（prompt 不进 argv）
    assert r["prompt_via"] == "stdin"
    assert long_prompt not in r["cmd"]                  # 完整 prompt 不入命令行


def test_cli_build_argv_excludes_prompt():
    """prompt 绝不进 argv —— 杜绝进程表/审计日志/shell history 泄漏（C2）。"""
    for cls in (providers.CodexCliProvider, providers.CursorCliProvider, providers.ClaudeCliProvider):
        p = cls("x", {"type": "x"})
        argv = p._build_argv()
        assert "secret-prompt-body" not in " ".join(argv)   # _build_argv 不接收 prompt，自然不含
        assert isinstance(argv, list) and argv               # 非空 flags


def test_cli_request_repr_keeps_model_flag():
    p = providers.CursorCliProvider("cursor", {"type": "cursor-cli", "model": "gpt-5"})
    r = p.request_repr("hello")
    assert "gpt-5" in r["cmd"]
    assert r["cmd"][-1] == "<prompt:5字·stdin>"


# ── openai-compat 响应解析容错（防把『格式不同』误判成『不可用』）─────────────

def test_extract_content_standard_shape():
    data = {"choices": [{"message": {"content": "答案"}}]}
    assert providers._extract_content(data, "x") == "答案"


def test_extract_content_reasoning_model_fallback():
    # 推理模型 content 为空 / 缺，正文在 reasoning_content
    data = {"choices": [{"message": {"content": "", "reasoning_content": "推理后的答案"}}]}
    assert providers._extract_content(data, "x") == "推理后的答案"


def test_extract_content_legacy_completion_and_toplevel():
    assert providers._extract_content({"choices": [{"text": "旧式正文"}]}, "x") == "旧式正文"
    assert providers._extract_content({"output_text": "顶层正文"}, "x") == "顶层正文"


def test_extract_content_unparseable_raises_clear_error():
    import pytest as _pytest
    with _pytest.raises(RuntimeError, match="响应解析失败"):
        providers._extract_content({"unexpected": "shape"}, "glm")
