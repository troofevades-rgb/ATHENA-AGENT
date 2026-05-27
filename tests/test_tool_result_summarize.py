"""Per-tool intelligent compression in athena.ui._summarize_tool_result.

Pins the behavior for the three high-frequency tools whose raw output
was hard to scan in the transcript:

  * skill_view / skill_manage view — collapse YAML frontmatter to a
    single ``name · description`` header
  * TaskCreate — strip the ``(thought)-<uuid>`` bookkeeping prefix
  * TaskUpdate — same treatment for updated / completed transitions

Unknown tools must pass through unchanged so we don't accidentally
clip real output."""

from __future__ import annotations

from athena.ui import _summarize_tool_result


# ---------------------------------------------------------------------------
# skill_view / skill_manage(view)
# ---------------------------------------------------------------------------


def test_skill_view_collapses_frontmatter_to_one_line() -> None:
    output = """\
---
name: python-typing-style
description: When writing Python use PEP 604 syntax — `str | None`, not `Optional[str]`.
state: active
use_count: 0
write_origin: foreground
---

# Python typing conventions

The athena codebase commits to Python 3.11+ and uses the modern
annotation syntax throughout.
"""
    result = _summarize_tool_result("skill_view", output)
    lines = result.splitlines()
    # First line: condensed header
    assert "python-typing-style" in lines[0]
    assert "PEP 604" in lines[0]
    # Frontmatter lines ARE gone
    assert "state:" not in result
    assert "use_count:" not in result
    assert "write_origin:" not in result
    # Body content is preserved
    assert any("Python typing conventions" in ln for ln in lines)


def test_skill_view_truncates_long_descriptions() -> None:
    """A 500-char description shouldn't blow up the header line."""
    long_desc = "x" * 500
    output = f"---\nname: big\ndescription: {long_desc}\n---\n\nbody\n"
    result = _summarize_tool_result("skill_view", output)
    header = result.splitlines()[0]
    # Capped at ~120 chars
    assert len(header) < 150


def test_skill_view_caps_body_lines() -> None:
    output = "---\nname: x\ndescription: y\n---\n\n" + "\n".join(
        f"line {i}" for i in range(20)
    )
    result = _summarize_tool_result("skill_view", output)
    # 5 body lines + "more lines" marker + header = ~7
    assert "more body lines" in result


def test_skill_manage_view_gets_same_treatment() -> None:
    """``skill_manage(action='view')`` produces the same shape as
    ``skill_view``; the summarizer recognizes both names."""
    output = "---\nname: alpha\ndescription: a\n---\n\nbody\n"
    result = _summarize_tool_result("skill_manage", output)
    assert "alpha" in result.splitlines()[0]


def test_skill_view_passes_through_non_frontmatter_output() -> None:
    """If the output doesn't START with ``---``, leave it alone —
    must be an error message or unusual format."""
    err = "ERROR: skill not found: nonexistent"
    assert _summarize_tool_result("skill_view", err) == err


def test_skill_view_malformed_frontmatter_falls_through() -> None:
    """Opening --- without a closing --- → leave the output alone."""
    bad = "---\nname: x\n# never closes\nbody body body"
    result = _summarize_tool_result("skill_view", bad)
    assert result == bad


# ---------------------------------------------------------------------------
# TaskCreate / TaskUpdate
# ---------------------------------------------------------------------------


def test_task_create_strips_uuid_bookkeeping() -> None:
    """``(thought)-eb9ef126d6c4 created: Build comprehensive skills``
    → ``created: Build comprehensive skills``. The UUID is internal
    bookkeeping the user never references."""
    out = "(thought)-eb9ef126d6c4 created: Build comprehensive skills inventory"
    result = _summarize_tool_result("TaskCreate", out)
    assert result == "created: Build comprehensive skills inventory"


def test_task_create_passes_through_unrecognized_format() -> None:
    """If the format differs (different prefix, no UUID), pass through."""
    out = "task added (id=42): something"
    assert _summarize_tool_result("TaskCreate", out) == out


def test_task_update_strips_uuid_and_preserves_verb() -> None:
    out = "(thought)-eb9ef126d6c4 updated: status=in_progress, owner=me"
    result = _summarize_tool_result("TaskUpdate", out)
    assert result == "updated: status=in_progress, owner=me"


def test_task_update_handles_completed() -> None:
    out = "(thought)-abc123-def completed: status=completed"
    result = _summarize_tool_result("TaskUpdate", out)
    assert result == "completed: status=completed"


# ---------------------------------------------------------------------------
# Pass-through for unknown tools
# ---------------------------------------------------------------------------


def test_unknown_tool_passes_through_unchanged() -> None:
    """Tools the summarizer doesn't recognize must return the EXACT
    input. Otherwise we'd silently mangle tool output."""
    for tool in ("Read", "Bash", "Grep", "WebFetch", "my_custom_tool"):
        for sample in ("hello", "multi\nline\noutput", "", "{\"json\": true}"):
            assert _summarize_tool_result(tool, sample) == sample, (
                f"summarizer modified {tool}'s output unexpectedly"
            )


def test_empty_output_returns_empty() -> None:
    """Even for tools we DO have summarizers for, empty input must
    return empty (no crash, no synthesized content)."""
    for tool in ("skill_view", "TaskCreate", "TaskUpdate"):
        assert _summarize_tool_result(tool, "") == ""
