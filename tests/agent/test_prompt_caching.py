"""Tests for athena.agent.prompt_caching (T2-01.2)."""

from __future__ import annotations

import copy

from athena.agent.prompt_caching import apply_cache_markers, strip_cache_markers

# ---------------------------------------------------------------------------
# Pure-function invariants
# ---------------------------------------------------------------------------


def test_strategy_none_returns_unchanged_copy() -> None:
    msgs = [
        {"role": "system", "content": "You are athena."},
        {"role": "user", "content": "hi"},
    ]
    result = apply_cache_markers(msgs, strategy="none")
    assert result == msgs
    assert result is not msgs
    assert result[0] is not msgs[0]


def test_empty_input_returns_empty() -> None:
    assert apply_cache_markers([], strategy="system_and_3") == []


def test_does_not_mutate_input() -> None:
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]
    before = copy.deepcopy(msgs)
    apply_cache_markers(msgs, strategy="system_and_3")
    assert msgs == before


# ---------------------------------------------------------------------------
# Marker placement
# ---------------------------------------------------------------------------


def test_marker_on_last_system_message() -> None:
    msgs = [
        {"role": "system", "content": "sys1"},
        {"role": "user", "content": "hi"},
    ]
    result = apply_cache_markers(msgs)
    system_content = result[0]["content"]
    assert isinstance(system_content, list)
    assert system_content[0]["cache_control"] == {"type": "ephemeral"}


def test_marker_on_last_three_non_system_messages() -> None:
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "5"},
    ]
    result = apply_cache_markers(msgs)
    # Last 3 non-system are indices 3, 4, 5.
    for i in (3, 4, 5):
        assert isinstance(result[i]["content"], list)
        assert result[i]["content"][0]["cache_control"] == {"type": "ephemeral"}
    # First non-system message (index 1) must NOT carry a marker.
    assert "cache_control" not in result[1]
    if isinstance(result[1]["content"], list):
        assert not any("cache_control" in b for b in result[1]["content"])


def test_fewer_than_three_non_system_messages() -> None:
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "only one"},
    ]
    result = apply_cache_markers(msgs)
    assert result[1]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_picks_last_system_when_multiple() -> None:
    """When more than one system message exists, only the LAST one
    carries the marker — the prefix cache extends past whichever
    system message ended last."""
    msgs = [
        {"role": "system", "content": "sys1"},
        {"role": "system", "content": "sys2"},
        {"role": "user", "content": "hi"},
    ]
    result = apply_cache_markers(msgs)
    # First system: no marker.
    if isinstance(result[0]["content"], list):
        assert not any("cache_control" in b for b in result[0]["content"])
    else:
        assert "cache_control" not in result[0]
    # Last system: marker present.
    assert result[1]["content"][0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# TTL handling
# ---------------------------------------------------------------------------


def test_ttl_5m_default() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    result = apply_cache_markers(msgs, ttl="5m")
    assert result[0]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_ttl_1h() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    result = apply_cache_markers(msgs, ttl="1h")
    assert result[0]["content"][0]["cache_control"] == {
        "type": "ephemeral",
        "ttl": "1h",
    }


# ---------------------------------------------------------------------------
# Content-shape edge cases
# ---------------------------------------------------------------------------


def test_empty_string_content() -> None:
    msgs = [{"role": "user", "content": ""}]
    result = apply_cache_markers(msgs)
    assert result[0].get("cache_control") == {"type": "ephemeral"}


def test_list_content_marker_on_last_block() -> None:
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "text", "text": "world"},
            ],
        }
    ]
    result = apply_cache_markers(msgs)
    blocks = result[0]["content"]
    assert "cache_control" not in blocks[0]
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}


def test_tool_role_message_native_anthropic() -> None:
    msgs = [
        {"role": "user", "content": "run shell"},
        {"role": "assistant", "content": "ok"},
        {"role": "tool", "content": "output", "tool_call_id": "1"},
    ]
    result = apply_cache_markers(msgs, native_anthropic=True)
    assert result[2].get("cache_control") == {"type": "ephemeral"}


def test_tool_role_message_openai_compat_no_marker() -> None:
    msgs = [{"role": "tool", "content": "output", "tool_call_id": "1"}]
    result = apply_cache_markers(msgs, native_anthropic=False)
    assert "cache_control" not in result[0]


def test_none_content() -> None:
    """Some assistant messages have content=None alongside tool_calls."""
    msgs = [
        {"role": "assistant", "content": None, "tool_calls": []},
    ]
    result = apply_cache_markers(msgs)
    assert result[0].get("cache_control") == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# strip_cache_markers
# ---------------------------------------------------------------------------


def test_strip_removes_markers_from_message_and_blocks() -> None:
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "tool", "content": "x", "tool_call_id": "1"},
    ]
    marked = apply_cache_markers(msgs, ttl="5m")
    stripped = strip_cache_markers(marked)
    for msg in stripped:
        assert "cache_control" not in msg
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                assert "cache_control" not in block
