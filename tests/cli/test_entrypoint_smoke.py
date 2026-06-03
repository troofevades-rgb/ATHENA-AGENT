"""Smoke tests for CLI entry points that the coverage census flagged at
0% (`athena audit/checkpoint/cleanup-blobs/image-demo/plugins/proxy/
recall/reindex/sessions/theme/wordmark`).

These are thin argparse drivers over well-tested modules, but being at 0%
means their import + parser wiring + early control flow had never been
exercised by a test — exactly where a never-run typo or bad import hides.
Each test invokes `<module>.main(argv)` directly (the same callable
`__main__` dispatches to) at the safest level that still runs real code:
a pure happy path where possible, a documented error path otherwise, and
an argparse-only check for `proxy` (whose serve path blocks on a socket).

Goal is breadth (every entry point loads and runs) over depth.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.cli import (
    audit,
    checkpoint,
    cleanup_blobs,
    image_demo,
    plugins,
    proxy,
    recall,
    reindex,
    sessions,
    theme,
    wordmark,
)

# ---- pure / read-only drivers (no temp dir, no mocking) -----------------


def test_theme_list_and_preview():
    assert theme.main(["list"]) == 0
    assert theme.main(["preview"]) == 0
    assert theme.main([]) == 0  # bare → defaults to preview
    # Unknown theme name is the documented error path.
    assert theme.main(["preview", "no-such-theme-xyz"]) == 1


def test_plugins_list_and_unknown():
    assert plugins.main(["list"]) == 0
    # Enable/disable/info on an unknown plugin → exit 2, no state write.
    assert plugins.main(["enable", "no-such-plugin-xyz"]) == 2
    assert plugins.main(["info", "no-such-plugin-xyz"]) == 2


def test_image_demo_diag():
    # --diag reports capabilities without emitting image bytes; safe with
    # no tty (detection returns "no protocol").
    assert image_demo.main(["--diag"]) == 0


def test_wordmark_list_fonts():
    # `list-fonts` is its own subcommand. Returns 0 when pyfiglet renders,
    # 1 when it's not installed — both are clean (no crash); the point is
    # the driver loads and dispatches.
    rc = wordmark.main(["list-fonts"])
    assert rc in (0, 1)


def test_proxy_help_is_argparse_only():
    # The serve path binds a socket and blocks, so we only smoke the
    # import + parser construction via --help (argparse exits 0).
    with pytest.raises(SystemExit) as ei:
        proxy.main(["--help"])
    assert ei.value.code == 0


def test_audit_rejects_bad_timestamp():
    # parse_timestamp on garbage → TimestampParseError → exit 2 (read-only
    # over the real audit log; never reached because parsing fails first).
    assert audit.main(["skill", "not-a-timestamp", "now"]) == 2


# ---- temp-home drivers (redirect storage to a tmp dir) ------------------


def test_reindex_missing_then_empty_profile(tmp_path: Path):
    # Nonexistent profile dir → exit 2.
    assert reindex.main(["--home", str(tmp_path), "--profile", "default"]) == 2
    # Existing but empty profile dir → reindexes 0 sessions → exit 0.
    (tmp_path / "profiles" / "default").mkdir(parents=True)
    assert reindex.main(["--home", str(tmp_path), "--profile", "default"]) == 0


def test_sessions_list_empty(tmp_path: Path, capsys):
    rc = sessions.main(["--home", str(tmp_path), "--profile", "default", "list"])
    assert rc == 0
    assert "(no sessions)" in capsys.readouterr().out


def test_cleanup_blobs_dry_run(tmp_path: Path):
    # Dry-run guarantees no deletion; the session walk targets the empty
    # temp home, so it reports a no-op and exits 0.
    assert cleanup_blobs.main(["--dry-run", "--home", str(tmp_path)]) == 0


def test_sessions_verify_json_empty(tmp_path: Path, capsys):
    rc = sessions.main(["--home", str(tmp_path), "--profile", "default", "verify", "--json"])
    assert rc == 0
    # --json must emit parseable JSON even with nothing to verify.
    json.loads(capsys.readouterr().out)


# ---- monkeypatched drivers (profile/session/index redirection) ----------


def test_checkpoint_list_no_sessions_exits(monkeypatch, tmp_path: Path):
    # Point the profile at an empty temp dir (no sessions/) → the session
    # resolver raises SystemExit rather than guessing.
    monkeypatch.setattr("athena.cli.checkpoint.profile_dir", lambda *a, **k: tmp_path)
    with pytest.raises(SystemExit):
        checkpoint.main(["list"])


def test_recall_backfill_without_backend(monkeypatch):
    # No embeddings backend configured → backfill reports and exits 1.
    monkeypatch.setattr("athena.cli.recall.build_vector_store", lambda **k: None)
    assert recall.main(["backfill"]) == 1
