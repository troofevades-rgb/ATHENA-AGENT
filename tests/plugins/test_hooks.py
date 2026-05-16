"""Hook dispatcher: error containment, veto semantics, message chaining."""
from __future__ import annotations

import logging
from typing import Any

import pytest

from ocode.plugins.base import Plugin
from ocode.plugins.hooks import HookDispatcher


class _Probe(Plugin):
    """Test plugin that records every hook invocation and can be configured
    to raise, veto, or modify."""

    def __init__(
        self,
        *,
        raises: str | None = None,
        veto: bool = False,
        rewrite: str | None = None,
        prefix: str | None = None,
    ):
        super().__init__()
        self.raises = raises
        self.veto = veto
        self.rewrite = rewrite
        self.prefix = prefix
        self.events: list[tuple[str, tuple[Any, ...]]] = []

    def _maybe_raise(self, hook: str) -> None:
        if self.raises == hook:
            raise RuntimeError(f"{self.name}: deliberate raise in {hook}")

    def on_session_start(self, session_id, profile):
        self.events.append(("session_start", (session_id, profile)))
        self._maybe_raise("on_session_start")

    def on_session_end(self, session_id, completed, interrupted):
        self.events.append(("session_end", (session_id, completed, interrupted)))
        self._maybe_raise("on_session_end")

    def pre_tool_call(self, tool_name, tool_args):
        self.events.append(("pre", (tool_name, dict(tool_args))))
        self._maybe_raise("pre_tool_call")
        return False if self.veto else None

    def post_tool_call(self, tool_name, tool_args, result):
        self.events.append(("post", (tool_name, result)))
        self._maybe_raise("post_tool_call")

    def on_user_message(self, prompt: str) -> str | None:
        self.events.append(("user", (prompt,)))
        self._maybe_raise("on_user_message")
        if self.rewrite is not None:
            return self.rewrite
        if self.prefix is not None:
            return self.prefix + prompt
        return None

    def on_assistant_message(self, content: str) -> None:
        self.events.append(("assistant", (content,)))
        self._maybe_raise("on_assistant_message")


def _named(name: str, **kwargs) -> _Probe:
    p = _Probe(**kwargs)
    p.name = name
    return p


def test_dispatcher_calls_all_plugins():
    a = _named("a")
    b = _named("b")
    d = HookDispatcher([a, b])
    d.on_session_start("s1", "default")
    assert a.events == [("session_start", ("s1", "default"))]
    assert b.events == [("session_start", ("s1", "default"))]


def test_exception_in_plugin_caught_and_logged(caplog):
    raiser = _named("raiser", raises="on_session_start")
    quiet = _named("quiet")
    d = HookDispatcher([raiser, quiet])
    with caplog.at_level(logging.ERROR):
        d.on_session_start("s1", "default")
    # The later plugin still runs.
    assert quiet.events == [("session_start", ("s1", "default"))]
    # Error was logged with plugin name.
    assert any("raiser" in r.message for r in caplog.records)


def test_pre_tool_call_false_blocks():
    veto = _named("veto", veto=True)
    d = HookDispatcher([veto])
    allow, who = d.pre_tool_call("Bash", {"command": "rm -rf /"})
    assert allow is False
    assert who == "veto"


def test_pre_tool_call_none_or_true_allows():
    quiet = _named("quiet")
    d = HookDispatcher([quiet])
    allow, who = d.pre_tool_call("Read", {"path": "/tmp/x"})
    assert allow is True
    assert who is None


def test_pre_tool_call_first_false_wins():
    """All plugins see the call (observability), but the first veto is what
    surfaces as the blocker."""
    a = _named("a")
    b = _named("b", veto=True)
    c = _named("c", veto=True)
    d = HookDispatcher([a, b, c])
    allow, who = d.pre_tool_call("Edit", {})
    assert allow is False
    assert who == "b"
    # Every plugin saw the call.
    assert ("pre", ("Edit", {})) in a.events
    assert ("pre", ("Edit", {})) in b.events
    assert ("pre", ("Edit", {})) in c.events


def test_pre_tool_call_exception_does_not_block(caplog):
    """A plugin that raises in pre_tool_call must NOT be treated as a veto."""
    raiser = _named("raiser", raises="pre_tool_call")
    d = HookDispatcher([raiser])
    with caplog.at_level(logging.ERROR):
        allow, who = d.pre_tool_call("Bash", {})
    assert allow is True
    assert who is None
    assert any("raiser" in r.message for r in caplog.records)


def test_on_user_message_chains_modifications():
    a = _named("a", prefix="[A] ")
    b = _named("b", prefix="[B] ")
    d = HookDispatcher([a, b])
    out = d.on_user_message("hello")
    # a runs first → "[A] hello"; b runs second on that → "[B] [A] hello"
    assert out == "[B] [A] hello"


def test_on_user_message_none_passes_through():
    a = _named("a")  # returns None
    b = _named("b", prefix="[B] ")
    d = HookDispatcher([a, b])
    assert d.on_user_message("hi") == "[B] hi"


def test_on_user_message_exception_keeps_prior(caplog):
    """If plugin A raises, plugin B should see the prior prompt, not None."""
    a = _named("a", raises="on_user_message")
    b = _named("b", prefix="[B] ")
    d = HookDispatcher([a, b])
    with caplog.at_level(logging.ERROR):
        out = d.on_user_message("base")
    assert out == "[B] base"
    assert any("a" in r.message for r in caplog.records)


def test_post_tool_call_observes_all():
    a = _named("a")
    b = _named("b")
    d = HookDispatcher([a, b])
    d.post_tool_call("Read", {"path": "/x"}, "file contents")
    assert ("post", ("Read", "file contents")) in a.events
    assert ("post", ("Read", "file contents")) in b.events


def test_post_tool_call_exception_does_not_break_others(caplog):
    raiser = _named("raiser", raises="post_tool_call")
    quiet = _named("quiet")
    d = HookDispatcher([raiser, quiet])
    with caplog.at_level(logging.ERROR):
        d.post_tool_call("Edit", {}, "ok")
    assert ("post", ("Edit", "ok")) in quiet.events


def test_on_assistant_message_observes_all():
    a = _named("a")
    b = _named("b")
    d = HookDispatcher([a, b])
    d.on_assistant_message("hello world")
    assert ("assistant", ("hello world",)) in a.events
    assert ("assistant", ("hello world",)) in b.events


def test_empty_dispatcher_is_safe():
    """All operations on a dispatcher with no plugins are no-ops / pass-throughs."""
    d = HookDispatcher([])
    d.on_session_start("s", "p")
    d.on_session_end("s", True, False)
    allow, who = d.pre_tool_call("X", {})
    assert (allow, who) == (True, None)
    d.post_tool_call("X", {}, "")
    assert d.on_user_message("kept") == "kept"
    d.on_assistant_message("kept")


def test_on_session_end_exception_caught(caplog):
    """A plugin that raises in on_session_end must not break the dispatcher."""
    raiser = _named("raiser", raises="on_session_end")
    quiet = _named("quiet")
    d = HookDispatcher([raiser, quiet])
    with caplog.at_level(logging.ERROR):
        d.on_session_end("s1", completed=True, interrupted=False)
    # The later plugin still observes the end.
    assert ("session_end", ("s1", True, False)) in quiet.events
    assert any("raiser" in r.message for r in caplog.records)


def test_on_assistant_message_exception_caught(caplog):
    """A plugin that raises in on_assistant_message must not break later ones."""
    raiser = _named("raiser", raises="on_assistant_message")
    quiet = _named("quiet")
    d = HookDispatcher([raiser, quiet])
    with caplog.at_level(logging.ERROR):
        d.on_assistant_message("hello")
    assert ("assistant", ("hello",)) in quiet.events
    assert any("raiser" in r.message for r in caplog.records)


def test_tool_args_passed_to_plugins_are_copies():
    """A plugin must not be able to mutate the agent's tool_args dict."""
    class Mutator(Plugin):
        def pre_tool_call(self, tool_name, tool_args):
            tool_args["INJECTED"] = "x"
            return None

    m = Mutator()
    m.name = "mutator"
    d = HookDispatcher([m])
    original = {"command": "ls"}
    d.pre_tool_call("Bash", original)
    assert "INJECTED" not in original
