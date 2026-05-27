"""Tests for the /video slash command — inspect + switch backends."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.commands.video import cmd_video


def _agent(video_backend=None):
    cfg = SimpleNamespace(video_backend=video_backend)
    return SimpleNamespace(cfg=cfg)


def _capture_ui():
    """Capture every ui.{info,warn,error,console.print} call so tests
    can assert on what the operator sees without coupling to rich
    routing."""
    lines: list[str] = []
    patches = []
    for fn_name in ("info", "warn", "error"):
        patches.append(
            patch(
                f"athena.commands.video.ui.{fn_name}",
                side_effect=lambda msg, *a, _name=fn_name, **kw:
                    lines.append(f"{_name}: {msg}"),
            )
        )
    patches.append(
        patch(
            "athena.commands.video.ui.console.print",
            side_effect=lambda *a, **kw:
                lines.append(" ".join(str(x) for x in a)),
        )
    )
    return lines, patches


def _run_with_capture(fn, *args, **kwargs):
    lines, patches = _capture_ui()
    for p in patches:
        p.start()
    try:
        result = fn(*args, **kwargs)
    finally:
        for p in patches:
            p.stop()
    return result, lines


# ----------------------------------------------------------------------
# /video (bare) — status display
# ----------------------------------------------------------------------


def test_video_status_shows_selector_none(monkeypatch):
    """With cfg.video_backend=None, status displays the auto hint."""
    monkeypatch.setattr(
        "athena.commands.video._video_backends",
        lambda: [("stub_video_local", False)],
    )
    _, lines = _run_with_capture(cmd_video, _agent(None), "")
    joined = "\n".join(lines)
    assert "video selector" in joined.lower()
    assert "auto" in joined.lower() or "broker picks" in joined.lower()
    assert "stub_video_local" in joined


def test_video_status_marks_current_selector(monkeypatch):
    monkeypatch.setattr(
        "athena.commands.video._video_backends",
        lambda: [("stub_video_local", False), ("xai_video", True)],
    )
    _, lines = _run_with_capture(cmd_video, _agent("xai_video"), "")
    # The * marker should appear next to xai_video in the LIST entry,
    # not in the heading line that echoes the selector value.
    list_lines = [l for l in lines if "selector:" not in l.lower()]
    xai_line = next(l for l in list_lines if "xai_video" in l)
    stub_line = next(l for l in list_lines if "stub_video_local" in l)
    assert "*" in xai_line
    assert "*" not in stub_line


def test_video_status_warns_when_no_backends(monkeypatch):
    monkeypatch.setattr("athena.commands.video._video_backends", lambda: [])
    _, lines = _run_with_capture(cmd_video, _agent(None), "")
    joined = "\n".join(lines)
    assert "no providers" in joined.lower()


# ----------------------------------------------------------------------
# /video list — name-only listing
# ----------------------------------------------------------------------


def test_video_list_prints_names_only(monkeypatch):
    monkeypatch.setattr(
        "athena.commands.video._video_backends",
        lambda: [("alpha", False), ("beta", True)],
    )
    _, lines = _run_with_capture(cmd_video, _agent(None), "list")
    # /video list emits each name on its own line, no decoration.
    assert "alpha" in lines
    assert "beta" in lines


# ----------------------------------------------------------------------
# /video set <name> — switch backend
# ----------------------------------------------------------------------


def test_video_set_updates_cfg(monkeypatch):
    monkeypatch.setattr(
        "athena.commands.video._video_backends",
        lambda: [("stub_video_local", False), ("xai_video", True)],
    )
    agent = _agent(None)
    _, lines = _run_with_capture(cmd_video, agent, "set xai_video")
    assert agent.cfg.video_backend == "xai_video"
    assert any("xai_video" in l for l in lines)


def test_video_set_rejects_unknown_backend(monkeypatch):
    monkeypatch.setattr(
        "athena.commands.video._video_backends",
        lambda: [("stub_video_local", False)],
    )
    agent = _agent(None)
    _, lines = _run_with_capture(cmd_video, agent, "set bogus_backend")
    assert agent.cfg.video_backend is None  # unchanged
    joined = "\n".join(lines)
    assert "unknown" in joined.lower()
    assert "stub_video_local" in joined  # offered as available


def test_video_set_with_no_arg_errors():
    agent = _agent(None)
    _, lines = _run_with_capture(cmd_video, agent, "set")
    joined = "\n".join(lines)
    assert "usage" in joined.lower()


# ----------------------------------------------------------------------
# /video clear — unset selector
# ----------------------------------------------------------------------


def test_video_clear_resets_to_none():
    agent = _agent("xai_video")
    _, lines = _run_with_capture(cmd_video, agent, "clear")
    assert agent.cfg.video_backend is None
    joined = "\n".join(lines)
    assert "cleared" in joined.lower()


# ----------------------------------------------------------------------
# Unknown subcommand
# ----------------------------------------------------------------------


def test_video_unknown_subcommand_errors():
    _, lines = _run_with_capture(cmd_video, _agent(None), "frobnicate")
    joined = "\n".join(lines)
    assert "unknown" in joined.lower()
    assert "/video" in joined


# ----------------------------------------------------------------------
# Auth status helper
# ----------------------------------------------------------------------


def test_auth_status_uses_backend_declared_env_vars(monkeypatch, tmp_path):
    """The auth-status check must match what the BACKEND's own
    resolver looks for, not a heuristic guess. xai_video declares
    ``ATHENA_XAI_API_KEY`` — the status display reads the declaration
    rather than guessing ``ATHENA_XAI_VIDEO_API_KEY``."""
    import athena.providers  # noqa: F401 — populates registry
    from athena import env as env_mod

    fake_env = tmp_path / ".env"
    fake_env.write_text("ATHENA_XAI_API_KEY=xai-12345\n", encoding="utf-8")
    monkeypatch.setattr(env_mod, "_path", lambda: fake_env)
    env_mod.reset_cache()

    from athena.commands.video import _auth_status

    out = _auth_status("xai_video")
    assert "auth ok" in out.lower()
    assert "ATHENA_XAI_API_KEY" in out


def test_auth_status_falls_back_to_heuristic_for_undeclared_backend(
    monkeypatch, tmp_path,
):
    """A backend without ``credential_env_vars`` falls back to the
    ATHENA_<NAME>_API_KEY heuristic."""
    from athena import env as env_mod

    fake_env = tmp_path / ".env"
    fake_env.write_text("ATHENA_CUSTOM_API_KEY=k-99\n", encoding="utf-8")
    monkeypatch.setattr(env_mod, "_path", lambda: fake_env)
    env_mod.reset_cache()

    from athena.commands.video import _auth_status

    out = _auth_status("custom")
    assert "auth ok" in out.lower()
    assert "ATHENA_CUSTOM_API_KEY" in out


def test_auth_status_missing_credential(monkeypatch, tmp_path):
    from athena import env as env_mod

    fake_env = tmp_path / ".env"
    monkeypatch.setattr(env_mod, "_path", lambda: fake_env)
    env_mod.reset_cache()

    from athena.commands.video import _auth_status

    out = _auth_status("xai_video")
    assert "no credential found" in out.lower()
