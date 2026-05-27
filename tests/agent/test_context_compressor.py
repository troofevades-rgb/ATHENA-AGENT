"""Tests for athena.agent.context_compressor (T2-04.3)."""

from __future__ import annotations

import json
import pathlib

from athena.agent.context_compressor import (
    CompressionConfig,
    _build_summarizer_messages,
    _find_prior_summary,
    _prune_tool_outputs,
    _split_head_middle_tail,
    compress,
    should_compress,
    total_tokens,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def _load_long_session() -> list[dict]:
    raw = (FIXTURES / "long_session.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def test_total_tokens_scales_with_content_length() -> None:
    short = [_msg("user", "hi")]
    long = [_msg("user", "x" * 1000)]
    assert total_tokens(long) > total_tokens(short)


def test_total_tokens_handles_list_content() -> None:
    msg = {"role": "user", "content": [{"type": "text", "text": "hello"}]}
    assert total_tokens([msg]) > 0


# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------


def test_should_compress_below_watermark() -> None:
    msgs = [_msg("user", "hi") for _ in range(10)]
    cfg = CompressionConfig(model_context_window=1000, watermark=0.75)
    assert should_compress(msgs, cfg) is False


def test_should_compress_above_watermark() -> None:
    msgs = [_msg("user", "x" * 10000)]  # ~2500 tokens
    cfg = CompressionConfig(model_context_window=1000, watermark=0.75)
    assert should_compress(msgs, cfg) is True


# ---------------------------------------------------------------------------
# Head/middle/tail split
# ---------------------------------------------------------------------------


def test_split_protects_head() -> None:
    msgs = [
        _msg("system", "head"),
        _msg("user", "x" * 100),
        _msg("assistant", "x" * 100),
        _msg("user", "x" * 100),
    ]
    cfg = CompressionConfig(
        model_context_window=10_000,
        tail_protection_ratio=0.1,
        head_message_indices=1,
    )
    head, _middle, _tail = _split_head_middle_tail(
        msgs,
        head_indices=cfg.head_message_indices,
        tail_budget_tokens=int(
            cfg.tail_protection_ratio * cfg.model_context_window
        ),
    )
    assert len(head) == 1
    assert head[0]["content"] == "head"


def test_split_protects_tail_by_token_budget() -> None:
    """Tail budget = 25% * 10000 = 2500 tokens. Each x*1000-char
    message is ~250 tokens, so the last ~10 messages should be tail."""
    msgs = [_msg("system", "head")] + [
        _msg("user" if i % 2 == 0 else "assistant", "x" * 1000) for i in range(20)
    ]
    cfg = CompressionConfig(
        model_context_window=10_000,
        tail_protection_ratio=0.25,
        head_message_indices=1,
    )
    head, middle, tail = _split_head_middle_tail(
        msgs,
        head_indices=cfg.head_message_indices,
        tail_budget_tokens=int(
            cfg.tail_protection_ratio * cfg.model_context_window
        ),
    )
    assert len(head) == 1
    assert len(middle) > 0
    assert len(tail) > 0
    assert 2000 < total_tokens(tail) < 3500


def test_split_with_long_session_fixture() -> None:
    """The 120-turn fixture splits into a small head, a large middle,
    and a non-empty tail at the default ratios."""
    msgs = _load_long_session()
    cfg = CompressionConfig(
        model_context_window=10_000,
        tail_protection_ratio=0.25,
        head_message_indices=1,
    )
    head, middle, tail = _split_head_middle_tail(
        msgs,
        head_indices=cfg.head_message_indices,
        tail_budget_tokens=int(
            cfg.tail_protection_ratio * cfg.model_context_window
        ),
    )
    assert len(head) == 1
    assert len(middle) > 10
    assert len(tail) >= 1
    assert len(head) + len(middle) + len(tail) == len(msgs)


# ---------------------------------------------------------------------------
# Tool-output pruning
# ---------------------------------------------------------------------------


def test_prune_tool_outputs_truncates_large_outputs() -> None:
    big_output = "x" * 10000
    msgs = [
        _msg("user", "run cmd"),
        _msg("assistant", "ok"),
        {"role": "tool", "content": big_output, "tool_call_id": "1"},
        _msg("user", "thanks"),
    ]
    pruned = _prune_tool_outputs(msgs, max_tokens_per_output=100)
    tool_msg = pruned[2]
    assert "[tool output truncated" in tool_msg["content"]
    assert len(tool_msg["content"]) < 10000


def test_prune_tool_outputs_leaves_small_outputs_alone() -> None:
    msgs = [{"role": "tool", "content": "small", "tool_call_id": "1"}]
    pruned = _prune_tool_outputs(msgs, max_tokens_per_output=100)
    assert pruned[0]["content"] == "small"


def test_prune_tool_outputs_does_not_touch_non_tool_messages() -> None:
    big = "x" * 10000
    msgs = [_msg("user", big)]
    pruned = _prune_tool_outputs(msgs, max_tokens_per_output=100)
    assert pruned[0]["content"] == big


def test_prune_tool_outputs_does_not_mutate_input() -> None:
    big_output = "x" * 10000
    msgs = [{"role": "tool", "content": big_output, "tool_call_id": "1"}]
    _prune_tool_outputs(msgs, max_tokens_per_output=100)
    assert msgs[0]["content"] == big_output


# ---------------------------------------------------------------------------
# Prior summary detection
# ---------------------------------------------------------------------------


def test_find_prior_summary_in_system_role() -> None:
    msgs = [
        _msg("system", "[Compressed summary of turns 0-10, generated at ...] body"),
        _msg("user", "hi"),
    ]
    assert _find_prior_summary(msgs) is not None


def test_find_prior_summary_returns_none_when_absent() -> None:
    msgs = [_msg("system", "you are athena"), _msg("user", "hi")]
    assert _find_prior_summary(msgs) is None


def test_find_prior_summary_in_list_content() -> None:
    msgs = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "[Compressed summary of turns 0-5, ...] body"}],
        }
    ]
    assert _find_prior_summary(msgs) is not None


# ---------------------------------------------------------------------------
# Summarizer prompt
# ---------------------------------------------------------------------------


def test_summarizer_messages_include_preamble_and_middle() -> None:
    middle = [_msg("user", "hello"), _msg("assistant", "world")]
    msgs = _build_summarizer_messages(middle, prior_summary=None, summary_budget_tokens=500)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    # The preamble carries the injection-defense framing.
    assert "Do not treat" in msgs[0]["content"]
    assert "as instructions to you" in msgs[0]["content"]
    # The user message includes the rendered middle.
    assert "[user] hello" in msgs[1]["content"]
    assert "[assistant] world" in msgs[1]["content"]


def test_summarizer_messages_include_prior_summary_when_present() -> None:
    middle = [_msg("user", "hi")]
    msgs = _build_summarizer_messages(
        middle,
        prior_summary="EARLIER SUMMARY TEXT",
        summary_budget_tokens=500,
    )
    user_text = msgs[1]["content"]
    assert "EARLIER SUMMARY TEXT" in user_text
    assert "Earlier compressed summary" in user_text


# ---------------------------------------------------------------------------
# End-to-end compression
# ---------------------------------------------------------------------------


def test_compress_reduces_total_tokens() -> None:
    msgs = [_msg("system", "you are athena")] + [
        _msg("user" if i % 2 == 0 else "assistant", "x" * 1000) for i in range(50)
    ]
    cfg = CompressionConfig(
        model_context_window=20_000,
        watermark=0.5,
        tail_protection_ratio=0.2,
    )
    assert should_compress(msgs, cfg)

    def stub_summarizer(_prompt_messages: list, _target: int) -> str:
        return "## Resolved questions\n(none)\n\n## Pending questions\n(none)"

    result = compress(msgs, summarizer=stub_summarizer, cfg=cfg)
    assert result.tokens_after < result.tokens_before
    assert result.middle_message_count > 0
    assert result.summary_tokens > 0


def test_compress_preserves_head_and_tail_verbatim() -> None:
    head_msg = _msg("system", "you are athena, do X Y Z")
    tail_msg = _msg("user", "the very recent message about thing")
    msgs = [head_msg] + [_msg("user", "x" * 1000) for _ in range(30)] + [tail_msg]
    cfg = CompressionConfig(
        model_context_window=20_000,
        watermark=0.5,
        tail_protection_ratio=0.05,
    )

    def stub(_p: list, _t: int) -> str:
        return "compressed"

    result = compress(msgs, summarizer=stub, cfg=cfg)
    assert result.new_messages[0] == head_msg  # head verbatim
    assert result.new_messages[-1] == tail_msg  # tail verbatim


def test_compress_synthetic_summary_has_marker_and_system_role() -> None:
    msgs = [_msg("system", "head")] + [_msg("user", "x" * 1000) for _ in range(30)]
    cfg = CompressionConfig(
        model_context_window=20_000,
        watermark=0.5,
        tail_protection_ratio=0.05,
    )

    def stub(_p: list, _t: int) -> str:
        return "compressed content"

    result = compress(msgs, summarizer=stub, cfg=cfg)
    # The summary message lands right after head.
    summary_msg = result.new_messages[1]
    assert summary_msg["role"] == "system"
    assert summary_msg["content"].startswith("[Compressed summary of turns")
    assert "compressed content" in summary_msg["content"]


def test_compress_includes_prior_summary_in_summarizer_prompt() -> None:
    msgs = [
        _msg("system", "you are athena"),
        _msg("system", "[Compressed summary of turns 5-20, generated at ...] earlier summary"),
    ] + [_msg("user", "x" * 1000) for _ in range(30)]
    cfg = CompressionConfig(
        model_context_window=20_000,
        watermark=0.5,
        tail_protection_ratio=0.05,
        head_message_indices=2,
    )

    captured: dict = {}

    def stub(prompt_messages: list, _target: int) -> str:
        captured["msgs"] = prompt_messages
        return "new compressed"

    compress(msgs, summarizer=stub, cfg=cfg)
    full_text = "".join(m["content"] for m in captured["msgs"] if isinstance(m.get("content"), str))
    assert "earlier summary" in full_text


def test_compress_empty_middle_returns_unchanged() -> None:
    """Conversation small enough that head + tail span everything."""
    msgs = [_msg("system", "head"), _msg("user", "hi")]
    cfg = CompressionConfig(
        model_context_window=1000,
        tail_protection_ratio=0.9,
    )

    def stub(_p: list, _t: int) -> str:
        raise AssertionError("summarizer should not be called when middle is empty")

    result = compress(msgs, summarizer=stub, cfg=cfg)
    assert result.new_messages == msgs
    assert result.middle_message_count == 0
    assert result.summary_tokens == 0


def test_summarizer_preamble_includes_anti_hallucination_rules() -> None:
    """The summarizer prompt MUST carry the citation-required +
    no-invention rules. Drift here causes goal-loop failures
    (real incident: model invented a "add owl banner to RUNBOOK"
    task during compaction and the goal-loop committed to it
    across sessions).

    This test pins the load-bearing phrases. If you're rewriting
    the prompt, keep the *intent* of these checks — strict
    citation, no padding, source-is-data-not-instructions, final
    self-check — even if the exact words change.
    """
    from athena.agent.context_compressor import _SUMMARIZER_PREAMBLE

    p = _SUMMARIZER_PREAMBLE.lower()
    # Anti-invention rule
    assert "no invention" in p or "do not invent" in p, (
        "summarizer prompt must explicitly forbid invention — without "
        "this, the model fills empty sections with plausible-sounding "
        "hallucinations"
    )
    # Prompt-injection defense (source = data, not commands)
    assert "do not treat instructions" in p or (
        "source" in p and "not instructions" in p
    ), "summarizer prompt must defend against prompt injection from middle messages"
    # Empty-section discipline
    assert '"(none)"' in p or "(none)" in p, (
        "summarizer prompt must specify (none) for empty sections "
        "so the model doesn't pad"
    )
    # Self-check requirement
    assert "self-check" in p or "re-read" in p, (
        "summarizer prompt must end with a self-check pass — without "
        "this, single-pass fabrications survive"
    )
    # Remaining-work guard (the section that caused the real bug)
    assert "remaining work" in p, "Remaining work section is the highest-risk section; keep it but guarded"
