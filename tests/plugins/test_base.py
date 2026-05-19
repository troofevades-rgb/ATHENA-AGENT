"""Plugin ABC: defaults are no-ops; subclasses can override each hook."""

from __future__ import annotations

from athena.plugins.base import Plugin


def test_default_hooks_are_noops():
    """Every hook on a vanilla subclass must return None / not raise."""

    class Vanilla(Plugin):
        pass

    p = Vanilla()
    # Lifecycle no-ops:
    assert p.on_install() is None
    assert p.on_session_start("session-1", "default") is None
    assert p.on_session_end("session-1", completed=True, interrupted=False) is None
    # Tool dispatch defaults:
    assert p.pre_tool_call("bash", {"command": "ls"}) is None
    assert p.post_tool_call("bash", {"command": "ls"}, "result") is None
    # Message defaults:
    assert p.on_user_message("hello") is None
    assert p.on_assistant_message("hi") is None


def test_subclass_can_override_each_hook():
    """Every hook is independently overridable."""
    calls: list[str] = []

    class Tracker(Plugin):
        def on_install(self) -> None:
            calls.append("install")

        def on_session_start(self, session_id: str, profile: str) -> None:
            calls.append(f"start:{session_id}:{profile}")

        def on_session_end(self, session_id: str, completed: bool, interrupted: bool) -> None:
            calls.append(f"end:{session_id}:{completed}:{interrupted}")

        def pre_tool_call(self, tool_name, tool_args):
            calls.append(f"pre:{tool_name}")
            return False  # veto

        def post_tool_call(self, tool_name, tool_args, result):
            calls.append(f"post:{tool_name}:{result}")

        def on_user_message(self, prompt: str) -> str | None:
            return prompt.upper()

        def on_assistant_message(self, content: str) -> None:
            calls.append(f"assistant:{content}")

    p = Tracker()
    p.on_install()
    p.on_session_start("s1", "default")
    assert p.pre_tool_call("Read", {}) is False
    p.post_tool_call("Read", {}, "ok")
    assert p.on_user_message("hi") == "HI"
    p.on_assistant_message("hello back")
    p.on_session_end("s1", completed=True, interrupted=False)

    assert calls == [
        "install",
        "start:s1:default",
        "pre:Read",
        "post:Read:ok",
        "assistant:hello back",
        "end:s1:True:False",
    ]


def test_default_config_is_empty_dict():
    """Instantiating a plugin with no config gives an empty dict, never None."""

    class P(Plugin):
        pass

    assert P().config == {}
    assert P(config=None).config == {}
    assert P(config={"k": "v"}).config == {"k": "v"}


def test_name_and_version_are_class_attributes_with_defaults():
    """Subclasses inherit empty defaults; the loader rebinds them from manifest."""

    class P(Plugin):
        pass

    assert P.name == ""
    assert P.version == ""


def test_subclass_can_declare_name_and_version_directly():
    """Plugins that want literal defaults can set name/version at class scope."""

    class P(Plugin):
        name = "my-plugin"
        version = "1.2.3"

    p = P()
    assert p.name == "my-plugin"
    assert p.version == "1.2.3"
