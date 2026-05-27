"""Per-tool approval preview construction.

``_interactive_approval`` calls ``_build_preview(tool_name, args)``
to produce a (preview_text, preview_kind) tuple shown to the user
before they answer Yes/No. The user should never have to guess
WHAT they're approving — these tests pin that the preview surfaces
the critical detail per tool:

  * Bash → the command string (kind="command")
  * Edit → -/+ diff of old → new with file header (kind="diff")
  * Write → file path + content preview (kind="file")
  * Anything else → JSON args dump (kind="text")
"""

from __future__ import annotations

from athena.safety.approval_callback import _build_preview


# ---------------------------------------------------------------------------
# Bash
# ---------------------------------------------------------------------------


def test_bash_preview_is_the_command() -> None:
    preview, kind = _build_preview("Bash", {"command": "ls -la /tmp"})
    assert preview == "ls -la /tmp"
    assert kind == "command"


def test_bash_accepts_lowercase_alias() -> None:
    preview, kind = _build_preview("bash", {"command": "ls"})
    assert kind == "command"


def test_bash_accepts_run_shell_command_name() -> None:
    """Some MCP-shaped tools use snake_case; handle the common ones."""
    preview, kind = _build_preview("run_shell_command", {"command": "ls"})
    assert kind == "command"


def test_bash_missing_command_falls_through_to_text() -> None:
    """If for some reason there's no `command` field, don't crash —
    fall back to the generic JSON dump."""
    preview, kind = _build_preview("Bash", {})
    assert kind == "text"
    assert preview is not None


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def test_write_preview_shows_path_then_content() -> None:
    preview, kind = _build_preview(
        "Write",
        {"file_path": "/tmp/foo.py", "content": "x = 1\ny = 2"},
    )
    assert kind == "file"
    assert preview is not None
    lines = preview.splitlines()
    assert lines[0] == "/tmp/foo.py"
    assert "x = 1" in preview
    assert "y = 2" in preview


def test_write_preview_truncates_long_content() -> None:
    big_body = "\n".join(f"line {i}" for i in range(50))
    preview, kind = _build_preview(
        "Write", {"file_path": "/tmp/big.txt", "content": big_body},
    )
    assert kind == "file"
    assert "more lines" in preview
    assert "line 49" not in preview  # truncated before


def test_write_handles_missing_path() -> None:
    preview, kind = _build_preview("Write", {"content": "x"})
    assert kind == "file"
    assert "<unknown>" in preview


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------


def test_edit_preview_renders_as_diff_with_file_headers() -> None:
    preview, kind = _build_preview(
        "Edit",
        {
            "file_path": "athena/foo.py",
            "old_string": "return 1",
            "new_string": "return 2",
        },
    )
    assert kind == "diff"
    assert "--- a/athena/foo.py" in preview
    assert "+++ b/athena/foo.py" in preview
    assert "-return 1" in preview
    assert "+return 2" in preview


def test_edit_multiline_old_and_new() -> None:
    preview, kind = _build_preview(
        "Edit",
        {
            "file_path": "x.py",
            "old_string": "def foo():\n    return 1",
            "new_string": "def foo():\n    return 2",
        },
    )
    assert kind == "diff"
    # Both lines of old marked with -, both of new marked with +
    minus_count = preview.count("\n-") + (1 if preview.startswith("-") else 0)
    plus_count = preview.count("\n+") + (1 if preview.startswith("+") else 0)
    # Account for the +++ header (1 of the + count is the file header)
    assert plus_count >= 2  # +++ + 2 new lines
    assert minus_count >= 2  # --- + 2 old lines


# ---------------------------------------------------------------------------
# Unknown / fallback
# ---------------------------------------------------------------------------


def test_unknown_tool_falls_back_to_json_args() -> None:
    preview, kind = _build_preview("MysteryTool", {"foo": "bar", "n": 42})
    assert kind == "text"
    assert "foo" in preview
    assert "bar" in preview
    assert "42" in preview


def test_unknown_tool_with_non_json_args_does_not_crash() -> None:
    """Args containing unserializable types (e.g. open file handles)
    must not raise — fall back to repr()."""
    class _NotJsonable:
        pass

    preview, kind = _build_preview("X", {"handle": _NotJsonable()})
    assert kind == "text"
    assert preview is not None


def test_empty_args_does_not_crash() -> None:
    preview, kind = _build_preview("Bash", {})
    assert preview is not None  # JSON fallback {}


def test_none_tool_name_does_not_crash() -> None:
    """Defensive — if the caller passes None as tool_name (shouldn't
    happen but easy to guard), fall back to text without raising."""
    preview, kind = _build_preview(None, {"x": 1})  # type: ignore[arg-type]
    assert kind == "text"
