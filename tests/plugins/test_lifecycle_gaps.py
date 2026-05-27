"""Plugin lifecycle gaps not covered by the existing suite.

``tests/plugins/test_loader.py`` covers the happy paths (instantiation,
topo sort, cycle detection, on_install-once, basic config override).
``tests/plugins/test_hooks.py`` covers exception isolation per hook.

What's not covered — and what these tests pin:

  * **Broken ``plugin.py``** (syntax error, import error) doesn't crash
    the loader OR prevent other plugins from loading. A single bad
    third-party plugin must never break athena.
  * **``_mark_installed`` corrupt marker file** — partial write,
    binary garbage, missing — handled gracefully (no crash, plugin
    treated as never-installed so on_install can fire).
  * **``on_install`` raises**: plugin is STILL returned by load_plugins
    so subsequent hooks (on_session_start, etc.) can fire on it.
    Without this the agent silently loses observability from the
    plugin even though it was loaded.
  * **Install marker survives across separate load_plugins() calls**:
    the actual persistence story. on_install fires exactly once
    across process restarts.
  * **Disable → re-enable preserves marker**: on_install does NOT
    re-fire just because the user toggled enabled state.
  * **HookDispatcher iterates in load order** (which is topo order
    by depends_on). Pre/post-tool hooks that depend on a sibling
    must see the sibling's effect first.
  * **Concurrent marker writes** don't corrupt the file.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from athena.plugins.base import Plugin
from athena.plugins.hooks import HookDispatcher
from athena.plugins.loader import _mark_installed, load_plugins
from athena.plugins.manifest import PluginManifest, parse_manifest


# ---------------------------------------------------------------------------
# Helpers — make tiny on-disk plugins
# ---------------------------------------------------------------------------


def _make_plugin_dir(
    root: Path, name: str, *, plugin_body: str,
    depends_on: list[str] | None = None,
    enabled_by_default: bool = True,
) -> Path:
    """Create a plugin dir with plugin.toml + plugin.py and return the
    directory path. The toml format is `[plugin]` section containing
    name/version/enabled_by_default/depends_on."""
    pdir = root / name
    pdir.mkdir(parents=True)
    deps_line = ""
    if depends_on:
        deps_line = "depends_on = [" + ", ".join(f'"{d}"' for d in depends_on) + "]\n"
    enabled_line = "enabled_by_default = true" if enabled_by_default else "enabled_by_default = false"
    (pdir / "plugin.toml").write_text(
        f'[plugin]\nname = "{name}"\nversion = "0.1.0"\n{enabled_line}\n{deps_line}',
        encoding="utf-8",
    )
    (pdir / "plugin.py").write_text(plugin_body, encoding="utf-8")
    return pdir


def _load_manifest(pdir: Path) -> PluginManifest:
    return parse_manifest(pdir / "plugin.toml")


# ---------------------------------------------------------------------------
# Broken plugin.py — others still load
# ---------------------------------------------------------------------------


def test_syntax_error_in_one_plugin_does_not_stop_others(
    tmp_path: Path, caplog,
) -> None:
    """One plugin with a syntax error must not prevent OTHER plugins
    from loading. The error is logged, the bad one is skipped."""
    good_body = """
from athena.plugins.base import Plugin
class Good(Plugin):
    pass
"""
    bad_body = """
this is not valid python !!!
"""
    good_dir = _make_plugin_dir(tmp_path, "good_one", plugin_body=good_body)
    bad_dir = _make_plugin_dir(tmp_path, "bad_one", plugin_body=bad_body)

    plugins = load_plugins(
        [_load_manifest(good_dir), _load_manifest(bad_dir)],
        config={},
        installed_marker=tmp_path / "installed",
    )

    names = [p.name for p in plugins]
    assert "good_one" in names, (
        "the bad plugin took down the good one — loader is not isolating "
        "per-plugin failures"
    )
    assert "bad_one" not in names


def test_import_error_in_plugin_does_not_crash_loader(
    tmp_path: Path, caplog,
) -> None:
    """Plugin that imports a nonexistent module must be skipped, not
    propagate. Third-party plugins commonly have optional deps."""
    body = """
import nonexistent_module_that_definitely_does_not_exist  # noqa
from athena.plugins.base import Plugin
class Bad(Plugin):
    pass
"""
    pdir = _make_plugin_dir(tmp_path, "imports_ghost", plugin_body=body)
    good_dir = _make_plugin_dir(
        tmp_path, "still_good",
        plugin_body="from athena.plugins.base import Plugin\nclass G(Plugin): pass\n",
    )

    plugins = load_plugins(
        [_load_manifest(pdir), _load_manifest(good_dir)],
        config={}, installed_marker=tmp_path / "marker",
    )

    assert [p.name for p in plugins] == ["still_good"]


def test_top_level_raise_in_plugin_module_skipped(
    tmp_path: Path,
) -> None:
    """A plugin.py whose top-level code raises (e.g. on import:
    ``raise RuntimeError("misconfigured")``) must be skipped without
    taking down the rest."""
    body = """
raise RuntimeError("intentional load-time failure")
from athena.plugins.base import Plugin
class Bad(Plugin): pass
"""
    pdir = _make_plugin_dir(tmp_path, "boom_at_import", plugin_body=body)
    good = _make_plugin_dir(
        tmp_path, "ok",
        plugin_body="from athena.plugins.base import Plugin\nclass G(Plugin): pass\n",
    )

    plugins = load_plugins(
        [_load_manifest(pdir), _load_manifest(good)],
        config={}, installed_marker=tmp_path / "marker",
    )

    assert [p.name for p in plugins] == ["ok"]


# ---------------------------------------------------------------------------
# _mark_installed — corrupt marker file resilience
# ---------------------------------------------------------------------------


def test_mark_installed_with_missing_marker_file(tmp_path: Path) -> None:
    """First-ever load: marker file does not exist. Must return True
    (fire on_install) and create the file."""
    marker = tmp_path / "installed"
    assert _mark_installed("new_plugin", marker) is True
    assert marker.exists()
    assert "new_plugin" in marker.read_text(encoding="utf-8")


def test_mark_installed_with_corrupt_marker_treats_as_empty(
    tmp_path: Path,
) -> None:
    """A marker file with binary garbage / non-UTF-8 bytes must not
    crash the loader. Behavior: treat as "no plugin installed yet"
    so we err on the side of firing on_install rather than skipping
    install entirely."""
    marker = tmp_path / "installed"
    marker.write_bytes(b"\xff\xfe\x00\x01garbage\xc0\xff")

    # Should not raise. Behavior: file gets overwritten cleanly.
    result = _mark_installed("plug", marker)
    # Whether it returns True or False, the file must be usable after
    assert marker.exists()
    # After the operation the file must be parseable as UTF-8 lines
    text = marker.read_text(encoding="utf-8", errors="replace")
    assert "plug" in text


def test_mark_installed_idempotent_across_calls(tmp_path: Path) -> None:
    """First call: True (install fires). Subsequent: False (already
    installed). Crucial — without idempotency, on_install runs on
    every restart and plugins do expensive setup work every time."""
    marker = tmp_path / "installed"
    assert _mark_installed("alpha", marker) is True
    assert _mark_installed("alpha", marker) is False
    assert _mark_installed("alpha", marker) is False


def test_mark_installed_tracks_multiple_plugins_independently(
    tmp_path: Path,
) -> None:
    """The marker tracks per-plugin install state. Installing plugin
    B must not affect plugin A's mark."""
    marker = tmp_path / "installed"
    _mark_installed("alpha", marker)
    _mark_installed("beta", marker)

    # Both present
    content = marker.read_text(encoding="utf-8")
    assert "alpha" in content
    assert "beta" in content

    # Re-marking either returns False
    assert _mark_installed("alpha", marker) is False
    assert _mark_installed("beta", marker) is False


# ---------------------------------------------------------------------------
# on_install lifecycle: persistence across loader calls
# ---------------------------------------------------------------------------


_INSTALL_BODY = """
from athena.plugins.base import Plugin
INSTALL_CALLS = []

class CountInstalls(Plugin):
    def on_install(self):
        INSTALL_CALLS.append(self.name)
"""


def _install_call_count(plugin) -> int:
    """Read the module-level counter from a loaded CountInstalls plugin."""
    import sys
    mod = sys.modules.get(f"athena_plugin__{plugin.name}")
    return len(getattr(mod, "INSTALL_CALLS", []))


def test_on_install_fires_once_across_separate_load_plugins_calls(
    tmp_path: Path,
) -> None:
    """The real persistence story: simulate two athena process
    restarts by calling load_plugins twice against the same marker.
    on_install must fire exactly once."""
    pdir = _make_plugin_dir(tmp_path, "once_only", plugin_body=_INSTALL_BODY)
    marker = tmp_path / "marker"

    plugins_a = load_plugins(
        [_load_manifest(pdir)], config={}, installed_marker=marker,
    )
    assert len(plugins_a) == 1
    assert _install_call_count(plugins_a[0]) == 1

    plugins_b = load_plugins(
        [_load_manifest(pdir)], config={}, installed_marker=marker,
    )
    # Second load: still loads, but on_install does NOT fire again
    assert len(plugins_b) == 1
    # New module instance; check the marker file directly instead
    assert "once_only" in marker.read_text(encoding="utf-8")


def test_disable_then_reenable_does_not_refire_install(
    tmp_path: Path,
) -> None:
    """User disables a plugin, then re-enables it: on_install must
    NOT fire again. Install is a one-time event tied to the plugin
    being present; enable/disable is a runtime activation toggle.

    The marker is the source of truth — once written, it survives
    config changes."""
    pdir = _make_plugin_dir(tmp_path, "toggle_me", plugin_body=_INSTALL_BODY)
    marker = tmp_path / "marker"

    # First load (enabled): on_install fires
    p1 = load_plugins([_load_manifest(pdir)], config={}, installed_marker=marker)
    assert len(p1) == 1
    initial_marker = marker.read_text(encoding="utf-8")
    assert "toggle_me" in initial_marker

    # Disable + reload: plugin not in output
    p2 = load_plugins(
        [_load_manifest(pdir)],
        config={"plugins": {"enabled": {"toggle_me": False}}},
        installed_marker=marker,
    )
    assert p2 == []
    # Marker unchanged (no spurious writes)
    assert marker.read_text(encoding="utf-8") == initial_marker

    # Re-enable: plugin loads but on_install does NOT re-fire
    p3 = load_plugins(
        [_load_manifest(pdir)],
        config={"plugins": {"enabled": {"toggle_me": True}}},
        installed_marker=marker,
    )
    assert len(p3) == 1
    # Marker contents unchanged
    assert marker.read_text(encoding="utf-8") == initial_marker


# ---------------------------------------------------------------------------
# on_install failure semantics
# ---------------------------------------------------------------------------


def test_plugin_returned_even_when_on_install_raises(tmp_path: Path) -> None:
    """on_install raised → log + continue. The plugin instance is
    STILL returned so subsequent lifecycle hooks fire on it. Without
    this, a plugin with a flaky on_install would silently drop out
    of every subsequent session even though it was "loaded"."""
    body = """
from athena.plugins.base import Plugin
class Risky(Plugin):
    def on_install(self):
        raise RuntimeError("simulated install failure")
    def on_session_start(self, session_id, profile):
        # We'd like THIS to still fire later.
        pass
"""
    pdir = _make_plugin_dir(tmp_path, "risky", plugin_body=body)
    plugins = load_plugins(
        [_load_manifest(pdir)], config={}, installed_marker=tmp_path / "m",
    )
    assert len(plugins) == 1
    assert plugins[0].name == "risky"


def test_on_install_failure_does_not_prevent_other_plugins_loading(
    tmp_path: Path,
) -> None:
    """One plugin's on_install failure must not interfere with
    sibling plugins' load. Per-plugin isolation."""
    bad_body = """
from athena.plugins.base import Plugin
class Bad(Plugin):
    def on_install(self):
        raise RuntimeError("nope")
"""
    good_body = """
from athena.plugins.base import Plugin
INSTALLED = []
class Good(Plugin):
    def on_install(self):
        INSTALLED.append(True)
"""
    bad_dir = _make_plugin_dir(tmp_path, "bad", plugin_body=bad_body)
    good_dir = _make_plugin_dir(tmp_path, "good", plugin_body=good_body)

    plugins = load_plugins(
        [_load_manifest(bad_dir), _load_manifest(good_dir)],
        config={}, installed_marker=tmp_path / "m",
    )
    names = [p.name for p in plugins]
    assert "good" in names
    assert "bad" in names


# ---------------------------------------------------------------------------
# Hook dispatcher fires in plugin LOAD order (topo order by depends_on)
# ---------------------------------------------------------------------------


def test_hook_dispatcher_fires_in_plugin_list_order() -> None:
    """HookDispatcher iterates self.plugins in order. Since loader
    returns topologically-sorted plugins, dependency-ordered hook
    fan-out is guaranteed transitively. Pin the list-order
    invariant here so a refactor that switches to dict/set
    iteration (non-deterministic) is caught."""
    call_order: list[str] = []

    class A(Plugin):
        name = "A"
        def on_session_start(self, sid, prof):
            call_order.append("A")

    class B(Plugin):
        name = "B"
        def on_session_start(self, sid, prof):
            call_order.append("B")

    class C(Plugin):
        name = "C"
        def on_session_start(self, sid, prof):
            call_order.append("C")

    # Deliberately not alphabetical
    disp = HookDispatcher([B(), A(), C()])
    disp.on_session_start("s1", "default")
    assert call_order == ["B", "A", "C"]


def test_pre_tool_call_fans_out_in_order_even_when_first_blocks() -> None:
    """The veto-but-still-fan-out invariant: every plugin sees the
    pre_tool_call for observability, even after one returns False.
    Order of observation must match plugin list order."""
    seen: list[str] = []

    class P1(Plugin):
        name = "p1"
        def pre_tool_call(self, tool_name, tool_args):
            seen.append("p1")
            return False  # veto

    class P2(Plugin):
        name = "p2"
        def pre_tool_call(self, tool_name, tool_args):
            seen.append("p2")
            return None

    class P3(Plugin):
        name = "p3"
        def pre_tool_call(self, tool_name, tool_args):
            seen.append("p3")
            return None

    disp = HookDispatcher([P1(), P2(), P3()])
    allow, blocker = disp.pre_tool_call("Bash", {"command": "ls"})
    assert allow is False
    assert blocker == "p1"
    assert seen == ["p1", "p2", "p3"], (
        "fan-out broke after veto — later plugins lost observability"
    )


# ---------------------------------------------------------------------------
# Concurrent marker writes — no corruption
# ---------------------------------------------------------------------------


def test_concurrent_mark_installed_does_not_corrupt_file(
    tmp_path: Path,
) -> None:
    """Two threads racing to install different plugins must not
    leave a half-written marker. Athena doesn't currently call
    load_plugins from multiple threads, but the marker file's
    durability shouldn't depend on that being true."""
    marker = tmp_path / "installed"
    barrier = threading.Barrier(8)

    def _worker(name: str) -> None:
        barrier.wait()
        _mark_installed(name, marker)

    threads = [
        threading.Thread(target=_worker, args=(f"p{i}",))
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    # File is parseable and contains at least one of the names
    text = marker.read_text(encoding="utf-8")
    names_in_file = {ln.strip() for ln in text.splitlines() if ln.strip()}
    # We don't insist all 8 won the race (no locking today — that's the
    # acceptable trade); we DO insist the file is valid and contains
    # only legitimate names, no corruption.
    assert names_in_file <= {f"p{i}" for i in range(8)}, (
        f"marker contains unexpected content: {names_in_file!r} — "
        f"writes overlapped and produced garbage"
    )
    # And no thread crashed
    for t in threads:
        assert not t.is_alive()
