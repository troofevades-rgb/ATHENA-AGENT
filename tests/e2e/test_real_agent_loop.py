"""End-to-end tests that exercise the REAL agent loop against the
configured Ollama provider — no FakeClient.

Why these exist: ``test_self_improvement_loop.py`` and friends use
scripted FakeClients so they're fast and deterministic but they
don't catch real-runtime bugs (streaming filter races, tool-result
feedback shape mismatches, message-history accumulation errors,
provider parser drift). These tests use a real model to surface
those.

Skipped automatically when:
  - Ollama is not reachable
  - the target model isn't loaded

So they're safe to run in CI / on fresh checkouts even when no
local LLM is configured.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Skip-when-no-LLM gating
# ---------------------------------------------------------------------------


def _ollama_host() -> str:
    """Read OLLAMA_HOST and normalize to a full URL. The env var is
    commonly set to bare ``host:port`` (which curl tolerates but
    urllib rejects with ``unknown url type``). Also normalize
    ``0.0.0.0`` to ``127.0.0.1`` for client connection — 0.0.0.0
    is a bind address, not a connect address."""
    raw = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
    if "://" not in raw:
        raw = f"http://{raw}"
    return raw.replace("//0.0.0.0:", "//127.0.0.1:")


def _ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen(f"{_ollama_host()}/api/tags", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _target_model_loaded(model_substr: str) -> bool:
    try:
        with urllib.request.urlopen(
            f"{_ollama_host()}/api/tags", timeout=2,
        ) as r:
            body = json.loads(r.read().decode("utf-8"))
    except Exception:
        return False
    return any(model_substr in m.get("name", "") for m in body.get("models", []))


# NOTE: skipif is evaluated at module-import time, which can race
# with Ollama spinning up. Use a per-test fixture-level skip
# instead via _maybe_skip(); this decorator is just a marker.
REQUIRES_OLLAMA = pytest.mark.usefixtures()


def _maybe_skip_if_no_ollama() -> None:
    """Call at the START of each test that needs a live model.
    Evaluates lazily — survives transient startup races."""
    if not _ollama_reachable():
        pytest.skip("Ollama not reachable at OLLAMA_HOST")


@pytest.fixture
def real_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a real Agent against live Ollama.

    Uses a tmp_path workspace so file ops can't escape. Picks a
    small fast model from what's installed; skips the test if no
    suitable model is loaded.
    """
    _maybe_skip_if_no_ollama()

    # Prefer FAST small models for sanity tests — we're verifying
    # the LOOP works, not measuring response quality. 3B models
    # finish a 50-token sanity reply in seconds; 14B+ models can
    # take minutes with our 45KB system prompt.
    # Candidate order: tool-tuned models FIRST, then size-graded
    # fallbacks. The tool-call test exercises structured tool
    # emission, which 7-8B non-tool-tuned models often miss
    # (emitting tool-call JSON as text rather than using the
    # structured tool_calls field). mistral:latest and
    # llama3.1:8b are reliably bad at it; coder-tuned tags and
    # the user's own athena tag are reliably good.
    candidates = [
        "qwen2.5-coder:14b",    # 14B — coder-tuned, reliable tools
        "troofevades-q35:athena",  # user's tuned 30B-MoE
        "qwen3-coder:30b",       # 30B coder
        "llama3.2:3b",           # 3B — fast but tool-flaky; last resort
        "llama3.1:8b",           # 8B — same flakiness; last resort
    ]
    chosen = next((m for m in candidates if _target_model_loaded(m)), None)
    if chosen is None:
        pytest.skip(f"None of {candidates} loaded in Ollama")

    # Silence ui output during tests. The Agent uses
    # ``ui.console.status()`` (for spinners) and ``ui.console.print()``
    # so we need a Console-shaped object — not a bare stub. Use
    # Rich's Console writing to devnull.
    import io
    from rich.console import Console
    import athena.ui as _ui

    silent = Console(
        file=io.StringIO(), force_terminal=False, no_color=True, quiet=True,
    )
    monkeypatch.setattr(_ui, "console", silent)
    monkeypatch.setattr(_ui, "info", lambda *a, **k: None)
    monkeypatch.setattr(_ui, "warn", lambda *a, **k: None)
    monkeypatch.setattr(_ui, "error", lambda *a, **k: None)

    from athena.agent.core import Agent
    from athena.config import Config

    workspace = tmp_path / "ws"
    workspace.mkdir()
    # Disable EVERY background subsystem we can. The default config
    # fires per-turn review forks every 10 tool calls + may run the
    # curator + spawns the progress-ticker thread. For sanity tests
    # we want a single foreground turn with no parallel work
    # competing for the GPU (otherwise the test takes minutes and
    # may timeout). Also reset module-level nudge counters in case
    # a prior test leaked state.
    from athena.review import nudge as _nudge
    _nudge.reset_all()

    cfg = Config()
    cfg.model = chosen
    cfg.profile = "default"
    cfg.review.nudge_interval = 0  # disable background review
    # NOTE: the background curator spawn is gated by the session-wide
    # ``ATHENA_DISABLE_BACKGROUND_CURATOR=1`` fixture in tests/conftest.py.
    # No per-test patch needed here.

    # Approval callback: tests run with stdin captured, so any
    # ``ui.confirm()`` call would OSError on input(). Some small
    # models call write-like tools speculatively even when told not
    # to ("Reply with exactly: HELLO_OK" sometimes drives a 7B model
    # to Write the response to a file). AUTO_DENY responds "deny"
    # without prompting — model gets a denied result, can continue.
    from athena.safety.approval_callback import (
        AUTO_DENY,
        set_approval_callback,
        reset_approval_callback,
    )
    _approval_token = set_approval_callback(AUTO_DENY)

    agent = Agent(cfg=cfg, workspace=workspace)
    # The default system prompt loads ATHENA.md + skills catalog +
    # memory + base rules → ~45KB. The model has to ingest that on
    # EVERY turn, which makes even a "say hi" sanity test take
    # minutes. We're testing the LOOP wiring, not the system-prompt
    # assembly — replace messages[0] with a minimal system prompt
    # so the model responds in seconds.
    agent.messages = [
        {
            "role": "system",
            "content": (
                "You are an integration-test assistant. Reply briefly. "
                "Do not use any tools unless explicitly asked to."
            ),
        },
    ]
    yield agent
    # IMPORTANT: reset the approval callback BEFORE closing the agent.
    # The ContextVar lives at module-process scope; without reset, every
    # subsequent test sees AUTO_DENY as the "default" and the four
    # ``test_*_approval_callback*`` tests fail with stale-state asserts.
    try:
        reset_approval_callback(_approval_token)
    except Exception:
        pass
    try:
        agent.close()
    except Exception:
        pass
    # Clean up any leaked review counter
    _nudge.reset_all()


# ---------------------------------------------------------------------------
# E2E #1 — basic single + multi-turn
# ---------------------------------------------------------------------------


@pytest.mark.timeout(180)
def test_single_turn_completes_and_records_assistant_message(real_agent) -> None:
    """The most basic check: a single turn against a real model
    finishes, produces an assistant message, and updates stats."""
    before_count = len(real_agent.messages)
    before_eval = real_agent.stats.eval_tokens

    real_agent.run_turn("Reply with exactly: HELLO_OK")

    # At least one new message — the assistant response
    after_count = len(real_agent.messages)
    assert after_count > before_count, "no new messages after run_turn"

    # The last message should be assistant role
    assert real_agent.messages[-1]["role"] == "assistant", \
        f"last message is {real_agent.messages[-1]['role']!r}, expected 'assistant'"

    # Stats should have updated
    assert real_agent.stats.eval_tokens > before_eval, \
        "eval_tokens didn't increment; provider may not be reporting usage"


@pytest.mark.timeout(300)
def test_multi_turn_context_accumulates(real_agent) -> None:
    """The model must SEE prior turns. Turn 1 plants a fact, turn 2
    asks for it back — if context isn't accumulating the model
    can't recall."""
    real_agent.run_turn(
        "Remember this secret: the magic word is BANANA42. "
        "Just acknowledge briefly."
    )
    # The assistant message should be present in history
    assert any(
        m["role"] == "assistant" for m in real_agent.messages
    )

    real_agent.run_turn(
        "What was the magic word I told you? Reply with just the word."
    )
    last = real_agent.messages[-1]
    assert last["role"] == "assistant"
    content = (last.get("content") or "").upper()
    # The model should produce BANANA42 somewhere in the response.
    assert "BANANA42" in content, (
        f"model did not recall planted fact across turns. "
        f"Got: {content!r}"
    )


@pytest.mark.timeout(180)
def test_user_message_appears_in_history(real_agent) -> None:
    """After run_turn, the USER message must be in history too —
    not just the assistant response. Otherwise /save would miss the
    user side and /resume would replay assistant-only."""
    real_agent.run_turn("Say OK and stop")
    user_msgs = [m for m in real_agent.messages if m["role"] == "user"]
    assert len(user_msgs) >= 1
    # The last user message should be what we sent
    assert "Say OK and stop" in (user_msgs[-1]["content"] or "")


# ---------------------------------------------------------------------------
# E2E #2 — tool dispatch + result feedback
# ---------------------------------------------------------------------------


@pytest.mark.timeout(300)
def test_model_can_call_read_tool_and_use_result(
    real_agent, tmp_path: Path
) -> None:
    """End-to-end tool round-trip: model is asked about a file,
    must call Read, get the bytes back, and reference what it saw
    in the response. Catches bugs in:
      - tool schema serialization (model can't pick the right tool)
      - tool dispatch (the call fires)
      - result feedback (the model sees what came back)
      - response continuation after tool result
    """
    # Set up a file with distinctive content the model must reference
    target = real_agent.workspace / "secret.md"
    target.write_text(
        "# Secret\n\nThe answer is PINEAPPLE.\n",
        encoding="utf-8",
    )

    real_agent.run_turn(
        f"Read the file {target.name} in the workspace and tell me "
        f"the single word that appears after 'The answer is'. "
        f"Reply with just that word."
    )

    # Verify a tool call happened
    tool_messages = [
        m for m in real_agent.messages
        if m.get("role") == "tool" or m.get("tool_calls")
    ]
    assert len(tool_messages) > 0, (
        "model never called any tool — either schema is wrong or "
        "the model interpreted the request differently"
    )

    # Verify the assistant referenced the secret content
    assistant_msgs = [
        m for m in real_agent.messages if m.get("role") == "assistant"
    ]
    final = (assistant_msgs[-1].get("content") or "").upper()
    assert "PINEAPPLE" in final, (
        f"model called tool but didn't surface result. "
        f"Final assistant message: {final!r}"
    )


# ---------------------------------------------------------------------------
# E2E #3 — save/resume round-trip (no LLM dependency for the round-trip;
# just verifies the storage format is symmetric)
# ---------------------------------------------------------------------------


def test_save_resume_preserves_messages_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The /save command writes JSON, /resume reads it. The two
    must round-trip. No LLM needed — this is a storage test."""
    import athena.ui as _ui
    class _S:
        def print(self, *a, **k): pass
    monkeypatch.setattr(_ui, "console", _S())
    monkeypatch.setattr(_ui, "info", lambda *a, **k: None)
    monkeypatch.setattr(_ui, "warn", lambda *a, **k: None)
    monkeypatch.setattr(_ui, "error", lambda *a, **k: None)

    from athena.commands.save_cmd import cmd_save
    from athena.commands.resume import cmd_resume
    from types import SimpleNamespace

    save_target = tmp_path / "sess.json"

    # Source agent with a multi-message history
    src_messages = [
        {"role": "system", "content": "You are athena"},
        {"role": "user", "content": "what is 2+2"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "and 3+3"},
        {"role": "assistant", "content": "6"},
    ]
    src_agent = SimpleNamespace(messages=list(src_messages))
    cmd_save(src_agent, str(save_target))

    # Fresh agent — only system message initially
    dst_agent = SimpleNamespace(
        messages=[{"role": "system", "content": "FRESH SYS"}],
    )
    cmd_resume(dst_agent, str(save_target))

    # Resume preserves the destination's system prompt, then appends
    # the source's non-system messages.
    assert dst_agent.messages[0] == {"role": "system", "content": "FRESH SYS"}
    # All non-system source messages should be present
    non_sys = [m for m in src_messages if m["role"] != "system"]
    assert dst_agent.messages[1:] == non_sys


# ---------------------------------------------------------------------------
# E2E #4 — /compact actually reduces tokens
# ---------------------------------------------------------------------------


@pytest.mark.timeout(300)
def test_compact_reduces_token_count_on_long_history(real_agent) -> None:
    """Manually inflate the message history with a bunch of long
    placeholder turns, then run /compact and verify token count
    drops. Uses the real summarizer (model call) so this catches
    regressions in the summary prompt + provider stream interaction."""
    from athena.agent.context_compressor import total_tokens
    from athena.commands.compact import cmd_compact

    # Build a long synthetic transcript: head + many filler turns
    real_agent.messages = [real_agent.messages[0]]  # keep system
    for i in range(20):
        real_agent.messages.append({
            "role": "user",
            "content": f"Turn {i}: " + ("placeholder text " * 80),
        })
        real_agent.messages.append({
            "role": "assistant",
            "content": f"Reply {i}: " + ("padded response text " * 80),
        })

    tokens_before = total_tokens(real_agent.messages)
    msg_count_before = len(real_agent.messages)

    cmd_compact(real_agent, "")

    tokens_after = total_tokens(real_agent.messages)
    msg_count_after = len(real_agent.messages)

    # Compaction should reduce token count substantially
    assert tokens_after < tokens_before, (
        f"compact did not reduce tokens "
        f"({tokens_before} → {tokens_after})"
    )
    # Should compress to fewer messages (head + summary + tail)
    assert msg_count_after < msg_count_before, (
        f"message count did not drop ({msg_count_before} → {msg_count_after})"
    )


# ---------------------------------------------------------------------------
# E2E #5 — goal continuation
# ---------------------------------------------------------------------------


def test_goal_sentinel_achievement_detected() -> None:
    """scan_sentinels must catch GOAL ACHIEVED on its own line."""
    from athena.goal.loop import scan_sentinels

    achieved, reason = scan_sentinels("All done.\nGOAL ACHIEVED")
    assert achieved is True
    assert reason is None


def test_goal_sentinel_blocked_extracts_reason() -> None:
    from athena.goal.loop import scan_sentinels

    achieved, reason = scan_sentinels(
        "I can't proceed.\nGOAL BLOCKED: missing API credentials"
    )
    assert achieved is False
    assert reason == "missing API credentials"


def test_goal_sentinel_no_match_returns_pair_of_nones() -> None:
    from athena.goal.loop import scan_sentinels

    achieved, reason = scan_sentinels("Just a regular reply with no sentinel")
    assert achieved is False
    assert reason is None


def test_goal_sentinel_empty_input_is_safe() -> None:
    """Streaming turns can produce empty text — must not crash."""
    from athena.goal.loop import scan_sentinels

    assert scan_sentinels("") == (False, None)
    assert scan_sentinels(None) == (False, None)  # type: ignore[arg-type]


def test_goal_achievement_wins_over_blocked_when_both_present() -> None:
    """Per the contract: ACHIEVED takes precedence over BLOCKED.
    The model committed to done, honour it."""
    from athena.goal.loop import scan_sentinels

    achieved, reason = scan_sentinels(
        "Tried hard.\nGOAL BLOCKED: had trouble\nActually wait\nGOAL ACHIEVED"
    )
    assert achieved is True
    assert reason is None
