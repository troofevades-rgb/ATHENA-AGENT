"""Real-shape session round-trip tests.

Existing ``test_store.py`` exercises ``append_turn`` / ``load`` with
simple {role, content} messages. What's missing is the message
shape the agent actually produces — assistant messages carrying
``tool_calls`` arrays, tool-result messages with ``tool_call_id``
correlations, and the consequent multi-turn replay where the model
on resume must see the same shapes it saw on save.

If any of this round-tripping is lossy (drops ``tool_calls``,
re-orders, splits, etc.) the resumed model sees malformed history
and can hallucinate / refuse / loop. So these tests pin the
structural invariants the agent loop depends on.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from athena.sessions.store import SessionMeta, SessionStore, new_session_id


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    """Fresh SessionStore against a tmp profile dir."""
    profile = tmp_path / "profile"
    profile.mkdir()
    return SessionStore(profile)


def _open_session(store: SessionStore, *, model: str = "test-model") -> str:
    """Create a session and return its ID."""
    sid = new_session_id()
    meta = SessionMeta(
        session_id=sid,
        profile="default",
        model=model,
        provider="ollama",
        workspace="/tmp/test-ws",
        started_at=datetime.now(timezone.utc),
    )
    store.open_session(meta)
    return sid


# ---------------------------------------------------------------------------
# Realistic agent message shapes
# ---------------------------------------------------------------------------


def test_assistant_message_with_tool_calls_round_trips(store: SessionStore) -> None:
    """The shape the agent actually appends after the model calls a tool:
    ``{role: 'assistant', content: '...', tool_calls: [{id, function: {name, arguments}}]}``.
    All fields must be preserved through JSONL serialization."""
    sid = _open_session(store)
    store.append_turn(sid, {"role": "user", "content": "list the workspace"})
    asst = {
        "role": "assistant",
        "content": "",  # often empty when the turn is purely a tool call
        "tool_calls": [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "list_dir",
                    "arguments": '{"path": "."}',
                },
            },
        ],
    }
    store.append_turn(sid, asst)
    store.append_turn(sid, {
        "role": "tool",
        "tool_call_id": "call_abc123",
        "content": "ATHENA.md\nREADME.md\nathena/\ntests/",
    })

    # Round-trip
    loaded = list(store.load(sid))
    assert len(loaded) == 3
    assert loaded[1]["role"] == "assistant"
    assert loaded[1]["tool_calls"] == asst["tool_calls"]
    assert loaded[1]["tool_calls"][0]["id"] == "call_abc123"
    assert loaded[1]["tool_calls"][0]["function"]["name"] == "list_dir"
    # Tool result message preserves the correlation ID
    assert loaded[2]["role"] == "tool"
    assert loaded[2]["tool_call_id"] == "call_abc123"


def test_multi_tool_call_assistant_message_preserves_array(
    store: SessionStore,
) -> None:
    """Some providers (Anthropic / OpenAI parallel-tools) emit MULTIPLE
    tool_calls in a single assistant message. Each must survive
    round-trip including order."""
    sid = _open_session(store)
    asst = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "Read", "arguments": '{"file_path": "a.md"}'},
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "Read", "arguments": '{"file_path": "b.md"}'},
            },
            {
                "id": "call_3",
                "type": "function",
                "function": {"name": "Glob", "arguments": '{"pattern": "*.py"}'},
            },
        ],
    }
    store.append_turn(sid, asst)
    loaded = list(store.load(sid))
    assert len(loaded[0]["tool_calls"]) == 3
    # Order preserved
    ids = [tc["id"] for tc in loaded[0]["tool_calls"]]
    assert ids == ["call_1", "call_2", "call_3"]
    # Each tool name preserved
    names = [tc["function"]["name"] for tc in loaded[0]["tool_calls"]]
    assert names == ["Read", "Read", "Glob"]


def test_unicode_in_content_survives_round_trip(store: SessionStore) -> None:
    """Tool output and user prompts routinely contain non-ASCII
    (emoji, CJK, accented chars). Must round-trip byte-for-byte
    without escape mangling — otherwise re-feeding to the model
    confuses it."""
    sid = _open_session(store)
    msgs = [
        {"role": "user", "content": "owl 🦉 / 中文 / café / ñ"},
        {"role": "assistant", "content": "got it: 👍 中"},
        {"role": "tool", "tool_call_id": "x", "content": "result with 🎉"},
    ]
    for m in msgs:
        store.append_turn(sid, m)
    loaded = list(store.load(sid))
    assert loaded[0]["content"] == "owl 🦉 / 中文 / café / ñ"
    assert loaded[1]["content"] == "got it: 👍 中"
    assert loaded[2]["content"] == "result with 🎉"


def test_large_tool_result_round_trips(store: SessionStore) -> None:
    """Tool results can be huge (Read on a large file, search results
    with many hits). Must round-trip without truncation at the
    storage layer."""
    sid = _open_session(store)
    big = "x" * 50_000  # 50KB tool result
    store.append_turn(sid, {
        "role": "tool",
        "tool_call_id": "call_big",
        "content": big,
    })
    loaded = list(store.load(sid))
    assert len(loaded[0]["content"]) == 50_000
    assert loaded[0]["content"] == big


def test_content_with_newlines_does_not_split_into_multiple_turns(
    store: SessionStore,
) -> None:
    """JSONL is line-delimited. If content has literal newlines and
    they're not escaped, the message would split across multiple
    JSONL lines — silent corruption."""
    sid = _open_session(store)
    msg = {
        "role": "assistant",
        "content": "line one\nline two\nline three\n\nparagraph two",
    }
    store.append_turn(sid, msg)
    loaded = list(store.load(sid))
    assert len(loaded) == 1
    assert loaded[0]["content"] == msg["content"]
    assert loaded[0]["content"].count("\n") == 4


def test_message_with_list_content_round_trips(store: SessionStore) -> None:
    """Anthropic / Claude messages can have ``content`` as a list of
    blocks: ``[{type: 'text', text: '...'}, {type: 'image', ...}]``.
    Must round-trip the structure."""
    sid = _open_session(store)
    msg = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Here's the file:"},
            {"type": "text", "text": "(continuation)"},
        ],
    }
    store.append_turn(sid, msg)
    loaded = list(store.load(sid))
    assert isinstance(loaded[0]["content"], list)
    assert len(loaded[0]["content"]) == 2
    assert loaded[0]["content"][0]["type"] == "text"


# ---------------------------------------------------------------------------
# Cross-restart: save → close → reopen → load
# ---------------------------------------------------------------------------


def test_full_session_loads_after_close_and_reopen(tmp_path: Path) -> None:
    """The actual user flow: athena writes turns as they happen,
    user exits (close_session), later restarts athena (fresh
    SessionStore over the same profile dir), and /resumes. The
    second store instance must read what the first wrote."""
    profile = tmp_path / "profile"
    profile.mkdir()

    # Session 1
    store_a = SessionStore(profile)
    sid = _open_session(store_a, model="qwen2.5")
    store_a.append_turn(sid, {"role": "user", "content": "remember alpha"})
    store_a.append_turn(sid, {"role": "assistant", "content": "got it"})
    store_a.append_turn(sid, {"role": "user", "content": "remember beta"})
    store_a.append_turn(sid, {"role": "assistant", "content": "alpha + beta noted"})
    store_a.close_session(sid)
    store_a.close()

    # Fresh store over the same profile
    store_b = SessionStore(profile)
    loaded = list(store_b.load(sid))
    assert len(loaded) == 4
    contents = [m["content"] for m in loaded]
    assert contents == [
        "remember alpha", "got it", "remember beta", "alpha + beta noted",
    ]
    # The session shows up in list_sessions on the new instance
    sessions = list(store_b.list_sessions())
    assert any(s.session_id == sid for s in sessions), (
        "session written by store_a is missing from store_b's list — "
        "either the JSONL didn't flush or the index didn't rebuild"
    )


def test_concurrent_append_during_load_does_not_split_turn(
    tmp_path: Path,
) -> None:
    """The agent loop appends turns continuously while the user might
    /resume. Reading while writing must not return a half-line."""
    import threading
    import time
    profile = tmp_path / "profile"
    profile.mkdir()
    store = SessionStore(profile)
    sid = _open_session(store)

    stop = threading.Event()
    write_count = [0]

    def _writer() -> None:
        while not stop.is_set():
            store.append_turn(sid, {
                "role": "user", "content": f"msg-{write_count[0]}",
            })
            write_count[0] += 1
            time.sleep(0.001)

    t = threading.Thread(target=_writer, daemon=True)
    t.start()
    time.sleep(0.05)  # let some writes accumulate

    # Multiple concurrent loads — each must parse fully
    for _ in range(5):
        loaded = list(store.load(sid))
        # Every message must parse cleanly with the expected shape
        for m in loaded:
            assert isinstance(m, dict)
            assert "role" in m
            assert "content" in m
        time.sleep(0.005)

    stop.set()
    t.join(timeout=2.0)


# ---------------------------------------------------------------------------
# /save and /resume slash commands — slash-level integration
# ---------------------------------------------------------------------------


def test_save_resume_preserves_tool_call_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The /save command writes JSON, /resume reads it back. Must
    preserve tool_calls + tool_call_id correlations exactly."""
    import athena.ui as _ui

    monkeypatch.setattr(_ui, "info", lambda *a, **k: None)
    monkeypatch.setattr(_ui, "warn", lambda *a, **k: None)
    monkeypatch.setattr(_ui, "error", lambda *a, **k: None)

    from athena.commands.resume import cmd_resume
    from athena.commands.save_cmd import cmd_save
    from types import SimpleNamespace

    target = tmp_path / "session.json"

    # A realistic transcript with a tool round
    src_messages = [
        {"role": "system", "content": "You are athena"},
        {"role": "user", "content": "show me ATHENA.md"},
        {
            "role": "assistant", "content": "",
            "tool_calls": [{
                "id": "call_aa", "type": "function",
                "function": {"name": "Read", "arguments": '{"file_path": "ATHENA.md"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "call_aa", "content": "# athena\n..."},
        {"role": "assistant", "content": "It's the project doc."},
    ]
    src_agent = SimpleNamespace(messages=list(src_messages))
    cmd_save(src_agent, str(target))

    # Fresh agent — only a system message
    dst_agent = SimpleNamespace(
        messages=[{"role": "system", "content": "FRESH SYS"}],
    )
    cmd_resume(dst_agent, str(target))

    # System prompt preserved on the destination
    assert dst_agent.messages[0] == {"role": "system", "content": "FRESH SYS"}
    # Everything else carried over
    non_sys = [m for m in src_messages if m["role"] != "system"]
    assert dst_agent.messages[1:] == non_sys
    # Specifically the tool_calls structure survived
    asst_with_calls = dst_agent.messages[2]
    assert asst_with_calls["tool_calls"][0]["id"] == "call_aa"
    assert asst_with_calls["tool_calls"][0]["function"]["name"] == "Read"
    # Tool-result correlation preserved
    assert dst_agent.messages[3]["tool_call_id"] == "call_aa"
