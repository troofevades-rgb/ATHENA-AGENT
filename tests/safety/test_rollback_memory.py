"""Phase 17.6 — `athena memory diff|rollback` round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.cli import memory as memory_cli
from athena.cli.rollback import diff_target, rollback_target
from athena.memory.providers.builtin_file import BuiltinFileProvider
from athena.provenance import (
    CURATOR,
    FOREGROUND,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.safety import context as safety_context

PROFILE = "default"


@pytest.fixture(autouse=True)
def _isolate_safety_singletons():
    safety_context.reset_for_tests()
    yield
    safety_context.reset_for_tests()


@pytest.fixture
def provider(isolated_home: Path) -> BuiltinFileProvider:
    # ``home=`` overrides Path.home() so memory writes land in the
    # tmp-isolated profile dir instead of the real ~/.athena.
    return BuiltinFileProvider(home=isolated_home / ".athena")


def _write(
    provider: BuiltinFileProvider,
    name: str,
    body: str,
    *,
    write_origin: str = FOREGROUND,
) -> Path:
    return provider.write_entry(
        PROFILE,
        filename=name,
        name=name,
        description="testing",
        type="reference",
        body=body,
        write_origin=write_origin,
    )


def test_memory_rollback_restores_byte_for_byte(
    provider: BuiltinFileProvider,
    isolated_home: Path,
) -> None:
    target = _write(provider, "topic_a", "first version")
    original_bytes = target.read_bytes()

    # Curator-origin update simulates an autonomous mutation.
    token = set_current_write_origin(CURATOR)
    try:
        _write(provider, "topic_a", "second version", write_origin=CURATOR)
    finally:
        reset_current_write_origin(token)
    assert target.read_bytes() != original_bytes

    result = rollback_target(
        target,
        tool_name="memory_rollback",
        confirm=lambda _: True,
    )
    assert result["status"] == "restored"
    assert target.read_bytes() == original_bytes


def test_memory_diff_shows_change(
    provider: BuiltinFileProvider,
    isolated_home: Path,
) -> None:
    target = _write(provider, "topic_b", "alpha")
    token = set_current_write_origin(CURATOR)
    try:
        _write(provider, "topic_b", "beta", write_origin=CURATOR)
    finally:
        reset_current_write_origin(token)

    diff = diff_target(target)
    assert "alpha" in diff
    assert "beta" in diff


def test_memory_audit_records_write_then_rollback(
    provider: BuiltinFileProvider,
    isolated_home: Path,
) -> None:
    target = _write(provider, "topic_c", "first")
    token = set_current_write_origin(CURATOR)
    try:
        _write(provider, "topic_c", "second", write_origin=CURATOR)
    finally:
        reset_current_write_origin(token)
    rollback_target(
        target,
        tool_name="memory_rollback",
        confirm=lambda _: True,
    )

    log_path = safety_context.get_audit_log()._current_path()
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]
    tool_names = [r["tool_name"] for r in lines]
    assert "memory_write" in tool_names
    assert "memory_rollback" in tool_names
    # The first memory_write record's sha_after matches the
    # rollback record's sha_after (round-trip).
    first_write = next(r for r in lines if r["tool_name"] == "memory_write")
    rollback = next(r for r in lines if r["tool_name"] == "memory_rollback")
    assert first_write["sha_after"] == rollback["sha_after"]


def test_memory_cli_unknown_name_returns_error(
    provider: BuiltinFileProvider,
    isolated_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = memory_cli.main(["diff", "ghost"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "no memory" in captured.err.lower()


def test_memory_cli_rollback_with_yes_flag(
    provider: BuiltinFileProvider,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End-to-end via the CLI entrypoint. CONFIG_DIR is module-cached
    at import time, so monkeypatch it (and re-point the inner
    provider constructor) to the isolated home for this test."""
    from athena import config as cfg_mod

    fake_root = isolated_home / ".athena"
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", fake_root)

    target = _write(provider, "topic_d", "first")
    token = set_current_write_origin(CURATOR)
    try:
        _write(provider, "topic_d", "second", write_origin=CURATOR)
    finally:
        reset_current_write_origin(token)
    rc = memory_cli.main(["rollback", "topic_d", "-y", "--profile", PROFILE])
    assert rc == 0
    assert "first" in target.read_text(encoding="utf-8")
