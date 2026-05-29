"""Tests for ``/computer`` — status read-out for computer-use.

The slash command is just a dispatcher to ``_print_status``, which
in turn calls into ``computer.detect``, ``computer.audit``, and
``config`` to compose a multi-line readout. We mock those modules
so the test doesn't depend on a real backend / config / audit
file.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.commands.computer import cmd_computer, main as computer_main


def _capture():
    lines: list[str] = []
    patches = []
    for fn in ("info", "warn", "error"):
        patches.append(
            patch(
                f"athena.commands.computer.ui.{fn}",
                side_effect=lambda msg, *a, _n=fn, **kw:
                    lines.append(f"{_n}: {msg}"),
            )
        )
    patches.append(
        patch(
            "athena.commands.computer.ui.console.print",
            side_effect=lambda *a, **kw:
                lines.append(" ".join(str(x) for x in a)),
        )
    )
    return lines, patches


def _fake_cfg(**overrides) -> SimpleNamespace:
    """Stub Config shaped like the post-R4 nested layout.

    R4 stage 3 promoted the ``computer_*`` flat fields into a nested
    ``computer`` dataclass. Test overrides can still pass the legacy
    flat names for convenience -- they get translated to the nested
    SimpleNamespace below.
    """
    legacy_to_nested = {
        "computer_use_enabled": "use_enabled",
        "computer_permission_mode": "permission_mode",
        "computer_app_allowlist": "app_allowlist",
        "computer_app_denylist": "app_denylist",
        "computer_kill_hotkey": "kill_hotkey",
        "computer_max_actions_per_task": "max_actions_per_task",
        "computer_max_actions_per_sec": "max_actions_per_sec",
        "computer_backend": "backend",
        "computer_dry_run": "dry_run",
        "computer_audit_path": "audit_path",
        "computer_screenshots_dir": "screenshots_dir",
        "computer_deny_during_goal_loop": "deny_during_goal_loop",
    }
    computer_defaults = dict(
        use_enabled=False,
        permission_mode="observe_only",
        app_allowlist=[],
        app_denylist=[],
        kill_hotkey="ctrl+alt+k",
        max_actions_per_task=40,
        max_actions_per_sec=2.0,
        backend="auto",
        dry_run=False,
        audit_path=None,
        screenshots_dir=None,
        deny_during_goal_loop=True,
    )
    top_defaults: dict = {"profile": "default"}
    for k, v in overrides.items():
        if k in legacy_to_nested:
            computer_defaults[legacy_to_nested[k]] = v
        elif k in computer_defaults:
            computer_defaults[k] = v
        else:
            top_defaults[k] = v
    return SimpleNamespace(
        computer=SimpleNamespace(**computer_defaults),
        **top_defaults,
    )


def _fake_backend(name: str = "stub", *, available: bool = True, supports=()):
    return SimpleNamespace(
        name=name,
        is_available=lambda: available,
        supports=lambda: list(supports),
    )


def _fake_audit(entries=()):
    return SimpleNamespace(tail=lambda *, limit: list(entries)[-limit:])


def _run_with_patches(
    arg: str,
    *,
    cfg=None,
    backend=None,
    available_backends=None,
    audit_entries=(),
):
    cfg = cfg or _fake_cfg()
    backend = backend or _fake_backend()
    available_backends = available_backends or [
        {"name": "stub", "available": True, "supports": ["screenshot"]},
    ]
    lines, ui_patches = _capture()

    patches = ui_patches + [
        patch("athena.commands.computer.load_config", return_value=cfg),
        patch("athena.commands.computer.select_backend", return_value=backend),
        patch(
            "athena.commands.computer.available_backends",
            return_value=available_backends,
        ),
        patch(
            "athena.commands.computer.default_audit_path",
            return_value=Path("/fake/audit.jsonl"),
        ),
        patch(
            "athena.commands.computer.profile_dir",
            return_value=Path("/fake/profile"),
        ),
        patch(
            "athena.commands.computer.ActionAuditLog",
            return_value=_fake_audit(audit_entries),
        ),
    ]
    for p in patches:
        p.start()
    try:
        cmd_computer(SimpleNamespace(), arg)
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


# ---- slash dispatch ------------------------------------------------


def test_no_arg_prints_status() -> None:
    out = _run_with_patches("")
    # Identifiable status sections
    assert "computer use" in out.lower()
    assert "disabled" in out.lower()  # default cfg has it off
    assert "mode" in out.lower()
    assert "observe_only" in out
    assert "kill hotkey" in out.lower()
    assert "audit log" in out.lower()


def test_status_explicit_equivalent_to_no_arg() -> None:
    out_no_arg = _run_with_patches("")
    out_explicit = _run_with_patches("status")
    # Same key sections show up either way.
    for needle in ("computer use", "mode", "audit log"):
        assert needle in out_no_arg.lower()
        assert needle in out_explicit.lower()


def test_unknown_subcommand_errors() -> None:
    out = _run_with_patches("teleport")
    assert "unknown" in out.lower()
    assert "teleport" in out
    assert "status" in out.lower()  # hint at valid option


# ---- status content ------------------------------------------------


def test_enabled_cfg_renders_as_enabled() -> None:
    cfg = _fake_cfg(computer_use_enabled=True, computer_permission_mode="auto")
    out = _run_with_patches("", cfg=cfg)
    assert "enabled" in out.lower()
    assert "auto" in out


def test_allowlist_and_denylist_rendered() -> None:
    cfg = _fake_cfg(
        computer_app_allowlist=["chrome", "vscode"],
        computer_app_denylist=["banking-app"],
    )
    out = _run_with_patches("", cfg=cfg)
    assert "chrome" in out
    assert "vscode" in out
    assert "banking-app" in out


def test_empty_allowlist_shows_warning_text() -> None:
    """An empty allowlist means NO app can be controlled — make
    that visible to the user as a warning, not an empty list."""
    out = _run_with_patches("")  # default cfg has empty allowlist
    assert "no app may be controlled" in out.lower() or "empty" in out.lower()


def test_unavailable_backend_marked() -> None:
    """An unavailable backend (e.g. Windows backend on Linux) must
    be visibly flagged."""
    backend = _fake_backend("xdotool", available=False, supports=["click"])
    out = _run_with_patches("", backend=backend)
    assert "xdotool" in out
    assert "unavailable" in out.lower()


def test_known_backends_listed_with_check_marker() -> None:
    out = _run_with_patches(
        "",
        available_backends=[
            {"name": "macos", "available": True, "supports": ["click", "type"]},
            {"name": "xdotool", "available": False, "supports": ["click"]},
        ],
    )
    assert "macos" in out
    assert "xdotool" in out
    # Available has ✓, unavailable has ✗
    macos_line = next(l for l in out.splitlines() if "macos" in l and "✓" in l or "macos" in l)
    assert "✓" in macos_line or "✗" in macos_line


def test_no_audit_entries_shows_placeholder() -> None:
    out = _run_with_patches("", audit_entries=[])
    assert "no entries yet" in out.lower()


def test_audit_tail_renders_entries() -> None:
    entries = [
        SimpleNamespace(
            ts="2026-05-23T12:00:00", type="click", tier="trusted",
            app="vscode", executed=True, result="ok",
        ),
        SimpleNamespace(
            ts="2026-05-23T12:01:00", type="type", tier="confirm_needed",
            app="terminal", executed=False, result="denied",
        ),
    ]
    out = _run_with_patches("", audit_entries=entries)
    assert "click" in out
    assert "vscode" in out
    assert "ok" in out
    assert "denied" in out


# ---- athena computer CLI entry --------------------------------------


def test_main_default_action_is_status() -> None:
    """Bare ``athena computer`` should default to status."""
    lines, ui_patches = _capture()
    patches = ui_patches + [
        patch("athena.commands.computer.load_config", return_value=_fake_cfg()),
        patch(
            "athena.commands.computer.select_backend",
            return_value=_fake_backend(),
        ),
        patch(
            "athena.commands.computer.available_backends",
            return_value=[],
        ),
        patch(
            "athena.commands.computer.default_audit_path",
            return_value=Path("/x"),
        ),
        patch(
            "athena.commands.computer.profile_dir",
            return_value=Path("/y"),
        ),
        patch(
            "athena.commands.computer.ActionAuditLog",
            return_value=_fake_audit(),
        ),
    ]
    for p in patches:
        p.start()
    try:
        rc = computer_main([])
    finally:
        for p in patches:
            p.stop()
    assert rc == 0
    out = "\n".join(lines)
    assert "computer use" in out.lower()


def test_main_status_tail_arg_honored() -> None:
    """``athena computer status --tail 2`` must pass limit=2 into
    the audit log tail."""
    entries = [
        SimpleNamespace(
            ts=f"t{i}", type="click", tier="auto", app="a",
            executed=True, result="ok",
        )
        for i in range(5)
    ]
    fake_audit = SimpleNamespace(tail=MagicMock(return_value=entries[-2:]))
    _lines, ui_patches = _capture()
    patches = ui_patches + [
        patch("athena.commands.computer.load_config", return_value=_fake_cfg()),
        patch(
            "athena.commands.computer.select_backend",
            return_value=_fake_backend(),
        ),
        patch(
            "athena.commands.computer.available_backends",
            return_value=[],
        ),
        patch(
            "athena.commands.computer.default_audit_path",
            return_value=Path("/x"),
        ),
        patch(
            "athena.commands.computer.profile_dir",
            return_value=Path("/y"),
        ),
        patch(
            "athena.commands.computer.ActionAuditLog",
            return_value=fake_audit,
        ),
    ]
    for p in patches:
        p.start()
    try:
        rc = computer_main(["status", "--tail", "2"])
    finally:
        for p in patches:
            p.stop()
    assert rc == 0
    fake_audit.tail.assert_called_once_with(limit=2)


# Need MagicMock at module scope.
from unittest.mock import MagicMock  # noqa: E402
