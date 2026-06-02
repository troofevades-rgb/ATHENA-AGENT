"""Tests for ``/compact`` — manually trigger context compression."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from athena.commands.compact import cmd_compact


def _capture():
    lines: list[str] = []
    patches = []
    for fn in ("info", "warn", "error"):
        patches.append(
            patch(
                f"athena.commands.compact.ui.{fn}",
                side_effect=lambda msg, *a, _n=fn, **kw: lines.append(f"{_n}: {msg}"),
            )
        )
    return lines, patches


def _run(agent) -> str:
    lines, patches = _capture()
    for p in patches:
        p.start()
    try:
        cmd_compact(agent, "")
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


def _agent(
    *,
    messages: list[dict] | None = None,
    ingest_on_compact: bool = False,
    user_model_backend: str = "none",
):
    """Build an agent stub with the surface compact.py reads."""
    return SimpleNamespace(
        messages=messages
        if messages is not None
        else [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ],
        cfg=SimpleNamespace(
            context_window=8192,
            tail_protection_ratio=0.25,
            tool_output_prune_tokens=500,
            summary_budget_ratio=0.1,
            summary_budget_cap_tokens=2000,
            user_model=SimpleNamespace(
                ingest_on_compact=ingest_on_compact,
                backend=user_model_backend,
            ),
        ),
        provider=SimpleNamespace(stream_chat=lambda **k: iter([])),
        model="test-model",
        session_id="sess-1",
        _persist_message=lambda m: None,
    )


# ---- early-return paths --------------------------------------------


def test_short_transcript_does_nothing() -> None:
    """≤ 2 messages means nothing to compact — early-return with
    an info message, no compress() call."""
    agent = _agent(
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "only one user msg"},
        ]
    )
    with patch("athena.commands.compact.compress") as cmpr:
        out = _run(agent)
    cmpr.assert_not_called()
    assert "nothing to compact" in out.lower()


def test_no_middle_to_compact_message() -> None:
    """When compress() returns middle_message_count=0 (already
    fits in head+tail), surface a friendly message and don't
    mutate agent.messages."""
    agent = _agent()
    original_messages = list(agent.messages)
    result = SimpleNamespace(
        new_messages=agent.messages,
        tokens_before=1000,
        tokens_after=1000,
        tokens_compressed=0,
        compression_ratio=1.0,
        middle_message_count=0,
        summary_tokens=0,
    )
    with patch("athena.commands.compact.compress", return_value=result):
        out = _run(agent)
    assert "nothing to compact" in out.lower()
    assert agent.messages == original_messages


# ---- happy path -----------------------------------------------------


def test_successful_compaction_replaces_messages_and_reports() -> None:
    """compress() returned a real reduction — agent.messages updates,
    user sees before/after token counts + reduction %."""
    agent = _agent()
    new_msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "[summary] ..."},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
    ]
    result = SimpleNamespace(
        new_messages=new_msgs,
        tokens_before=5000,
        tokens_after=1200,
        tokens_compressed=3800,
        compression_ratio=0.24,  # 76% reduction
        middle_message_count=10,
        summary_tokens=300,
    )
    persisted: list = []
    agent._persist_message = lambda m: persisted.append(m)

    with patch("athena.commands.compact.compress", return_value=result):
        out = _run(agent)

    # Messages replaced
    assert agent.messages == new_msgs
    # New summary message persisted (index 1, after system at 0)
    assert persisted == [new_msgs[1]]
    # User-facing report mentions the numbers
    assert "5,000" in out  # tokens_before formatted with thousands sep
    assert "1,200" in out  # tokens_after
    assert "76%" in out  # reduction percentage
    assert "10 messages" in out
    assert "300" in out  # summary tokens


def test_compaction_with_one_new_message_skips_persist() -> None:
    """The persist call indexes [1] — when new_messages has length
    1 it must not IndexError."""
    agent = _agent()
    result = SimpleNamespace(
        new_messages=[{"role": "system", "content": "sys"}],
        tokens_before=5000,
        tokens_after=100,
        tokens_compressed=4900,
        compression_ratio=0.02,
        middle_message_count=5,
        summary_tokens=50,
    )
    persisted: list = []
    agent._persist_message = lambda m: persisted.append(m)
    with patch("athena.commands.compact.compress", return_value=result):
        _run(agent)
    # Guard prevents the index out-of-range
    assert persisted == []


# ---- user-model ingest gating --------------------------------------


def test_no_ingest_thread_when_ingest_on_compact_disabled() -> None:
    """Default config has ingest_on_compact=False — no worker thread
    should fire."""
    agent = _agent(ingest_on_compact=False, user_model_backend="local")
    result = SimpleNamespace(
        new_messages=agent.messages,
        tokens_before=1000,
        tokens_after=500,
        tokens_compressed=500,
        compression_ratio=0.5,
        middle_message_count=1,
        summary_tokens=100,
    )
    with (
        patch("athena.commands.compact.compress", return_value=result),
        patch("athena.commands.compact.threading.Thread") as thread_mock,
    ):
        _run(agent)
    thread_mock.assert_not_called()


def test_no_ingest_thread_when_backend_is_none() -> None:
    """ingest_on_compact=True but backend='none' — still no thread."""
    agent = _agent(ingest_on_compact=True, user_model_backend="none")
    result = SimpleNamespace(
        new_messages=agent.messages,
        tokens_before=1000,
        tokens_after=500,
        tokens_compressed=500,
        compression_ratio=0.5,
        middle_message_count=1,
        summary_tokens=100,
    )
    with (
        patch("athena.commands.compact.compress", return_value=result),
        patch("athena.commands.compact.threading.Thread") as thread_mock,
    ):
        _run(agent)
    thread_mock.assert_not_called()


def test_summarizer_failure_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/compact`` calls ``compress(messages, summarizer=...)``.
    If the summarizer's ``provider.stream_chat`` raises (a 404 on
    a misrouted model, a transport blip, an auth rejection), the
    exception used to propagate through ``cmd_compact`` into the
    REPL's slash-command dispatch, up to ``main()`` -- a fatal
    crash on what should be a no-op. Same bug class as commit
    6056381 surfaced for the automatic compressor; this is the
    manual-trigger sibling.

    Post-fix: ``cmd_compact`` catches and surfaces a friendly
    ``compaction failed: ...`` message via ``ui.error``, returns
    "", and the REPL stays alive."""

    def boom(*args, **kwargs):
        raise RuntimeError("simulated provider failure")

    agent = _agent()
    with patch("athena.commands.compact.compress", side_effect=boom):
        out = _run(agent)  # MUST NOT raise

    assert "compaction failed" in out.lower()
    assert "runtimeerror" in out.lower()
    # No mutation of messages.
    assert len(agent.messages) == 5


def test_ingest_thread_fires_when_enabled_and_backend_set() -> None:
    """When both conditions are true, a daemon thread starts."""
    agent = _agent(ingest_on_compact=True, user_model_backend="local")
    result = SimpleNamespace(
        new_messages=agent.messages,
        tokens_before=1000,
        tokens_after=500,
        tokens_compressed=500,
        compression_ratio=0.5,
        middle_message_count=1,
        summary_tokens=100,
    )
    fake_thread = MagicMock()
    with (
        patch("athena.commands.compact.compress", return_value=result),
        patch(
            "athena.commands.compact.threading.Thread",
            return_value=fake_thread,
        ) as thread_cls,
    ):
        _run(agent)
    thread_cls.assert_called_once()
    # Must be daemon — never block process exit on a stuck ingest
    _args, kwargs = thread_cls.call_args
    assert kwargs.get("daemon") is True
    fake_thread.start.assert_called_once()
