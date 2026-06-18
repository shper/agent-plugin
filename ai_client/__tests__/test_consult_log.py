"""consult_log 留痕单测 —— 纯标准库，随 `python3 -m pytest __tests__ -q` 跑（无需 httpx）。

覆盖：_sanitize 防目录穿越 + 保留中文；start 回显任务名格式 + 头部内容；
record_call 追加（请求占位 / prompt / 生响应 / error 分支）；record_call 写盘失败不抛（非阻塞）；
record_verdict 追加收口段；_fmt_request 渲染 + API 不泄漏 key。
"""

from __future__ import annotations

import re

import consult_log


# ── _sanitize ─────────────────────────────────────────────────────────────

def test_sanitize_blocks_traversal():
    for evil in ["../../etc/passwd", "a/../b", r"..\..\win", "/abs/path"]:
        out = consult_log._sanitize(evil)
        assert "/" not in out and "\\" not in out and ".." not in out, out


def test_sanitize_empty_and_blank():
    assert consult_log._sanitize("") == "unnamed"
    assert consult_log._sanitize("   ") == "unnamed"
    assert consult_log._sanitize("..") == "unnamed"


def test_sanitize_keeps_cjk_and_slug():
    assert consult_log._sanitize("用SSE还是WS") == "用SSE还是WS"
    assert consult_log._sanitize("sse-vs-websocket") == "sse-vs-websocket"


# ── start ─────────────────────────────────────────────────────────────────

def test_start_returns_timestamped_task_and_header(tmp_path, monkeypatch):
    monkeypatch.setattr(consult_log, "_CACHE_DIR", tmp_path)
    task = consult_log.start(
        slug="sse-vs-ws", mode="debate", trigger="辩论一下该用谁",
        host="claude", models="正方=codex / 反方=cursor",
    )
    assert re.fullmatch(r"\d{8}-\d{6}_sse-vs-ws", task), task
    text = (tmp_path / task / "session.md").read_text(encoding="utf-8")
    assert "启动模式: debate" in text
    assert "启动提示词: 辩论一下该用谁" in text
    assert "宿主: claude" in text
    assert "正方=codex / 反方=cursor" in text


# ── record_call ───────────────────────────────────────────────────────────

def test_record_call_writes_request_prompt_response(tmp_path, monkeypatch):
    monkeypatch.setattr(consult_log, "_CACHE_DIR", tmp_path)
    consult_log.record_call(
        task="t1", mode="debate", provider="codex",
        request={"transport": "cli", "cmd": ["codex", "exec", "<prompt:3字>"]},
        prompt="abc", response="结论X", role="正方", model="gpt-5.5", duration=1.2,
    )
    text = (tmp_path / "t1" / "session.md").read_text(encoding="utf-8")
    assert "debate" in text and "【正方】" in text and "codex" in text
    assert "model=gpt-5.5" in text
    assert "<prompt:3字>" in text   # 请求行是占位
    assert "结论X" in text          # 生响应全文
    assert "1.2s" in text


def test_record_call_error_branch(tmp_path, monkeypatch):
    monkeypatch.setattr(consult_log, "_CACHE_DIR", tmp_path)
    consult_log.record_call(
        task="t3", mode="panel", provider="qwen",
        request={"transport": "api", "method": "POST", "url": "u",
                 "model": "m", "auth": "none", "prompt_chars": 3},
        prompt="abc", error="调用超时",
    )
    text = (tmp_path / "t3" / "session.md").read_text(encoding="utf-8")
    assert "· error ·" in text
    assert "调用超时" in text


def test_record_call_autocreates_header_when_no_start(tmp_path, monkeypatch):
    monkeypatch.setattr(consult_log, "_CACHE_DIR", tmp_path)
    consult_log.record_call(
        task="t2", mode="direct", provider="cursor",
        request={"transport": "cli", "cmd": ["cursor-agent", "<prompt:1字>"]},
        prompt="x", response="ok",
    )
    text = (tmp_path / "t2" / "session.md").read_text(encoding="utf-8")
    assert text.startswith("# to-consult 留痕 · t2")  # 兜底头部
    assert "兜底创建" in text


def test_record_call_never_raises_on_write_failure(monkeypatch):
    def boom(_task):
        raise OSError("disk full")

    monkeypatch.setattr(consult_log, "session_file", boom)
    # 写盘失败必须吞掉、不抛（留痕是增益，不阻断会诊）
    consult_log.record_call(
        task="t", mode="panel", provider="x",
        request={"transport": "cli", "cmd": ["a"]}, prompt="p", response="r",
    )


# ── record_verdict ────────────────────────────────────────────────────────

def test_record_verdict_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(consult_log, "_CACHE_DIR", tmp_path)
    consult_log.record_verdict(task="t4", mode="debate", verdict="裁决：用 SSE，置信度 88%")
    text = (tmp_path / "t4" / "session.md").read_text(encoding="utf-8")
    assert "主裁收口结论 · debate" in text
    assert "裁决：用 SSE，置信度 88%" in text


# ── _redact（落盘前敏感串脱敏，C2）─────────────────────────────────────────

def test_redact_common_secret_shapes():
    cases = [
        "key=sk-ABCDEF0123456789abcdef",            # OpenAI/Anthropic 前缀
        "ark-31635c33-1b02-4f84-acc0-48b021604125", # volces ark 前缀
        "token ghp_ABCDEFGHIJKLMNOP0123",           # GitHub
        "AKIAIOSFODNN7EXAMPLE",                      # AWS Access Key ID
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9", # Bearer
        'api_key = "super-secret-value-123"',       # 显式赋值
    ]
    for raw in cases:
        out = consult_log._redact(raw)
        assert "已脱敏" in out, raw
    # 私钥整块
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    assert "MIIabc" not in consult_log._redact(pem)


def test_redact_keeps_assign_keyname_drops_value():
    out = consult_log._redact('api_key = "ark-DEADBEEFDEADBEEF1234"')
    assert "api_key" in out                  # 键名保留（可读）
    assert "ark-DEADBEEF" not in out         # 值被脱敏


def test_redact_leaves_plain_text_untouched():
    plain = "我们该用 SSE 还是 WebSocket？延迟和重连是关键考量。"
    assert consult_log._redact(plain) == plain


def test_record_call_redacts_secret_in_prompt_and_response(tmp_path, monkeypatch):
    monkeypatch.setattr(consult_log, "_CACHE_DIR", tmp_path)
    consult_log.record_call(
        task="sec", mode="panel", provider="glm",
        request={"transport": "api", "url": "u", "model": "m", "auth": "none", "prompt_chars": 9},
        prompt="分析这份配置：api_key = sk-LEAKED0123456789abcd",
        response="发现密钥 ark-9999888877776666aaaa 建议轮换",
    )
    text = (tmp_path / "sec" / "session.md").read_text(encoding="utf-8")
    assert "sk-LEAKED0123456789abcd" not in text    # prompt 正文脱敏
    assert "ark-9999888877776666aaaa" not in text   # 响应正文脱敏
    assert "已脱敏" in text


# ── record_cards（C1：panel persona 卡回填）──────────────────────────────

def test_record_cards_appends_and_redacts(tmp_path, monkeypatch):
    monkeypatch.setattr(consult_log, "_CACHE_DIR", tmp_path)
    consult_log.record_cards(
        task="pc", mode="panel",
        cards='架构红队: 风险X；含密钥 sk-LEAK0123456789abcd 应脱敏',
    )
    text = (tmp_path / "pc" / "session.md").read_text(encoding="utf-8")
    assert "宿主 persona 卡" in text and "架构红队" in text
    assert "sk-LEAK0123456789abcd" not in text and "已脱敏" in text   # 回填也走脱敏


# ── _fmt_request ──────────────────────────────────────────────────────────

def test_fmt_request_cli():
    s = consult_log._fmt_request({"transport": "cli", "cmd": ["codex", "exec", "<prompt:5字>"]})
    assert s == "codex exec <prompt:5字>"


def test_fmt_request_api_hides_key():
    s = consult_log._fmt_request({
        "transport": "api", "method": "POST",
        "url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat", "auth": "bearer(已隐藏)", "prompt_chars": 42,
    })
    assert "https://api.deepseek.com/v1/chat/completions" in s
    assert "已隐藏" in s and "prompt_chars=42" in s
    assert "sk-" not in s and "api_key" not in s.lower()


def test_fmt_request_none():
    assert consult_log._fmt_request(None) == "(无请求信息)"
