"""``cfg.agent_prefill_messages_file`` -- ephemeral prefill injection.

Phase 1B of the hermes-agent parity work. Operators set
``cfg.agent_prefill_messages_file`` to a JSON file of
``{role, content}`` entries; on every API call, the entries are
spliced between the system message and the user history. They are
EPHEMERAL -- the agent's persisted state (``self.messages``, the
session JSONL, the ``/save`` transcript) shows only real turns.

These pins lock the contract:

  * File resolution honors absolute paths, ``~`` expansion, and
    relative-to-``~/.athena/`` (parity with hermes's bare-filename
    convention).
  * Schema validation accepts role in {user, assistant, system}
    and string content; invalid entries are skipped with a warn.
  * Loader caches the result on ``_prefill_cache``; explicit
    invalidation via :meth:`reload_prefill_messages` re-reads from
    disk.
  * Injection point: ``_messages_for_api`` returns
    ``[system, *prefill, *history]`` when prefill is non-empty;
    just ``[system, *history]`` (i.e. unchanged) when empty.
  * The prefill messages NEVER appear in ``self.messages`` or the
    session JSONL -- only in the per-call ``msgs_to_send`` list
    passed to ``provider.stream_chat``.

These invariants are what distinguish prefill from a steer push
(which lands in ``self.messages``) and from a system-prompt
mutation (which lands in ``messages[0]``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from athena.agent.core import Agent
from athena.config import Config

if TYPE_CHECKING:
    from .conftest import FakeProvider


def _make_agent(
    fake_provider: FakeProvider,
    workspace: Path,
    *,
    prefill_file: str | None = None,
) -> Agent:
    cfg = Config(model="fake-model")
    if prefill_file is not None:
        cfg.agent_prefill_messages_file = prefill_file
    return Agent(cfg, workspace, provider=fake_provider)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Loader: file resolution + schema validation
# ---------------------------------------------------------------------------


def test_no_file_configured_returns_empty(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """Default state (no file configured) means no prefill, no
    warnings, no errors."""
    agent = _make_agent(fake_provider, workspace)
    assert agent._load_prefill_messages() == []


def test_absolute_path_resolves_directly(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    target = tmp_path / "prefill.json"
    _write_json(
        target,
        [
            {"role": "user", "content": "ping"},
            {"role": "assistant", "content": "pong"},
        ],
    )
    agent = _make_agent(fake_provider, workspace, prefill_file=str(target))
    assert agent._load_prefill_messages() == [
        {"role": "user", "content": "ping"},
        {"role": "assistant", "content": "pong"},
    ]


def test_relative_path_resolves_against_dot_athena(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """Bare-filename / relative paths resolve against
    ``~/.athena/`` -- matches the hermes convention where
    ``prefill_messages_file: "prefill.json"`` means
    ``~/.hermes/prefill.json``. ``isolated_home`` redirects
    ``Path.home()`` for the test so we're not touching the
    user's real ``~/.athena``."""
    target = isolated_home / ".athena" / "myprefill.json"
    _write_json(target, [{"role": "user", "content": "rel"}])
    agent = _make_agent(fake_provider, workspace, prefill_file="myprefill.json")
    msgs = agent._load_prefill_messages()
    assert msgs == [{"role": "user", "content": "rel"}]


def test_missing_file_returns_empty_with_warn(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    agent = _make_agent(
        fake_provider, workspace, prefill_file=str(tmp_path / "missing.json")
    )
    assert agent._load_prefill_messages() == []


def test_invalid_json_returns_empty(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    agent = _make_agent(fake_provider, workspace, prefill_file=str(bad))
    assert agent._load_prefill_messages() == []


def test_non_list_payload_rejected(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    """JSON must be a list of messages -- a top-level dict (like
    ``{"messages": [...]}``) is rejected because callers might
    expect that shape but it's not the contract."""
    not_list = tmp_path / "not_list.json"
    not_list.write_text(
        json.dumps({"messages": [{"role": "user", "content": "x"}]}),
        encoding="utf-8",
    )
    agent = _make_agent(fake_provider, workspace, prefill_file=str(not_list))
    assert agent._load_prefill_messages() == []


def test_invalid_role_skipped(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    """An entry with an unsupported role is skipped (warn); valid
    siblings still load. This way a single malformed entry doesn't
    nuke the whole prefill."""
    mixed = tmp_path / "mixed.json"
    _write_json(
        mixed,
        [
            {"role": "user", "content": "good1"},
            {"role": "tool", "content": "bad"},
            {"role": "assistant", "content": "good2"},
        ],
    )
    agent = _make_agent(fake_provider, workspace, prefill_file=str(mixed))
    msgs = agent._load_prefill_messages()
    assert msgs == [
        {"role": "user", "content": "good1"},
        {"role": "assistant", "content": "good2"},
    ]


def test_system_role_accepted_in_prefill(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    """The bundled aggressive template (``templates/prefill.json``)
    leads with a ``"role": "system"`` entry. The loader must accept
    system so that template works as shipped, even though some
    providers don't accept multiple system messages."""
    with_system = tmp_path / "with_system.json"
    _write_json(
        with_system,
        [
            {"role": "system", "content": "GODMODE: ENABLED"},
            {"role": "user", "content": "ping"},
        ],
    )
    agent = _make_agent(fake_provider, workspace, prefill_file=str(with_system))
    msgs = agent._load_prefill_messages()
    assert msgs == [
        {"role": "system", "content": "GODMODE: ENABLED"},
        {"role": "user", "content": "ping"},
    ]


def test_non_string_content_skipped(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    bad_content = tmp_path / "bad_content.json"
    _write_json(
        bad_content,
        [
            {"role": "user", "content": ["array", "instead"]},
            {"role": "user", "content": "ok"},
        ],
    )
    agent = _make_agent(fake_provider, workspace, prefill_file=str(bad_content))
    assert agent._load_prefill_messages() == [{"role": "user", "content": "ok"}]


# ---------------------------------------------------------------------------
# Cache + reload_prefill_messages
# ---------------------------------------------------------------------------


def test_loader_caches_after_first_read(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    """The result is cached on ``_prefill_cache``; a second call
    returns the same list without re-reading the file. This is
    what keeps a hot path from hitting disk on every turn."""
    target = tmp_path / "cached.json"
    _write_json(target, [{"role": "user", "content": "v1"}])
    agent = _make_agent(fake_provider, workspace, prefill_file=str(target))

    first = agent._load_prefill_messages()
    # Now mutate the file -- cache must NOT see the change.
    _write_json(target, [{"role": "user", "content": "v2"}])
    second = agent._load_prefill_messages()
    assert first == second == [{"role": "user", "content": "v1"}]


def test_reload_picks_up_file_change(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    """``reload_prefill_messages`` invalidates the cache so a
    subsequent ``_load`` re-reads from disk. This is the entry
    point ``/godmode prefill set`` uses to pick up the new file."""
    target = tmp_path / "reload.json"
    _write_json(target, [{"role": "user", "content": "v1"}])
    agent = _make_agent(fake_provider, workspace, prefill_file=str(target))
    assert agent._load_prefill_messages() == [{"role": "user", "content": "v1"}]

    _write_json(target, [{"role": "user", "content": "v2"}])
    agent.reload_prefill_messages()
    assert agent._load_prefill_messages() == [{"role": "user", "content": "v2"}]


# ---------------------------------------------------------------------------
# Injection in _messages_for_api
# ---------------------------------------------------------------------------


def test_no_prefill_returns_messages_unchanged(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """No prefill configured -> ``_messages_for_api`` returns the
    same thing ``_messages_with_cache_markers`` would (system +
    history). Verifies the feature is OFF by default."""
    agent = _make_agent(fake_provider, workspace)
    agent.messages.append({"role": "user", "content": "hi"})

    api_msgs = agent._messages_for_api()
    plain = agent._messages_with_cache_markers()
    assert api_msgs == plain


def test_prefill_inserted_between_system_and_history(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    """Splice order: ``[system, *prefill, *history]``. The system
    message at index 0 stays put; prefill slots in at index 1+; the
    user's real turns follow."""
    target = tmp_path / "splice.json"
    _write_json(
        target,
        [
            {"role": "user", "content": "PREFILL_USER"},
            {"role": "assistant", "content": "PREFILL_ASSISTANT"},
        ],
    )
    agent = _make_agent(fake_provider, workspace, prefill_file=str(target))
    agent.messages.append({"role": "user", "content": "REAL_TURN"})

    api_msgs = agent._messages_for_api()

    # Order is system, prefill user, prefill assistant, real user turn.
    assert len(api_msgs) == 4
    assert api_msgs[0]["role"] == "system"
    assert api_msgs[1] == {"role": "user", "content": "PREFILL_USER"}
    assert api_msgs[2] == {"role": "assistant", "content": "PREFILL_ASSISTANT"}
    assert api_msgs[3] == {"role": "user", "content": "REAL_TURN"}


def test_prefill_never_appears_in_self_messages(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    """The ephemeral invariant: building the API message list
    must NOT mutate ``self.messages``. ``/save``, the session
    JSONL, and any other consumer of ``self.messages`` see only
    real turns."""
    target = tmp_path / "ephem.json"
    _write_json(target, [{"role": "user", "content": "PREFILL_LEAK_CHECK"}])
    agent = _make_agent(fake_provider, workspace, prefill_file=str(target))
    agent.messages.append({"role": "user", "content": "real"})

    snapshot_before = list(agent.messages)
    _ = agent._messages_for_api()
    assert agent.messages == snapshot_before
    # And the prefill content is not in self.messages.
    serialized = json.dumps(agent.messages)
    assert "PREFILL_LEAK_CHECK" not in serialized


def test_prefill_does_not_get_persisted_to_jsonl(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    tmp_path: Path,
) -> None:
    """Belt-and-suspenders pin: prefill never lands in the session
    JSONL. ``_persist_message`` is called per ``self.messages``
    append; since prefill doesn't append, no JSONL write happens."""
    target = tmp_path / "no_persist.json"
    _write_json(target, [{"role": "user", "content": "PREFILL_PERSIST_CHECK"}])
    agent = _make_agent(fake_provider, workspace, prefill_file=str(target))

    # Trigger _messages_for_api a few times -- exactly what every
    # turn does on its way into stream_chat.
    for _ in range(3):
        _ = agent._messages_for_api()

    # Inspect the session JSONL: if one exists, it must not
    # contain the prefill needle. The path follows the store's
    # ``sessions_dir / "{session_id}.jsonl"`` convention.
    if agent.session_store is not None and agent.session_id is not None:
        jsonl = agent.session_store.sessions_dir / f"{agent.session_id}.jsonl"
        if jsonl.exists():
            assert "PREFILL_PERSIST_CHECK" not in jsonl.read_text(encoding="utf-8")
