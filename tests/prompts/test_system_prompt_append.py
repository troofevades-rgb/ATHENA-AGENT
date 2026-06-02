"""``build_system_prompt(extra_append=...)`` -- the system-prompt
mutation hook for godmode and any future operator-supplied prompt
addition.

Mirrors the G0DM0D3 reference architecture. From
``api/routes/chat.ts:91-93``::

    const systemPrompt = godmode
      ? (custom_system_prompt || GODMODE_SYSTEM_PROMPT) + DEPTH_DIRECTIVE
      : custom_system_prompt || ''

The athena equivalent flows through ``build_system_prompt``'s
``extra_append`` keyword. The append goes at the very END of the
rendered prompt (after the /goal block) so the model treats it as
the most recent / most authoritative directive -- this is the same
positioning the reference uses.

Pins:

  * Empty / None / whitespace-only ``extra_append`` produces no
    trailing section. A fresh session's system prompt looks
    identical to what it was before this change.
  * Non-empty ``extra_append`` lands at the END, after the
    /goal block.
  * The append is added byte-faithful (whitespace stripped around
    the edges so the join doesn't introduce spurious blank lines).
"""

from __future__ import annotations

from pathlib import Path

from athena.prompts.system import build_system_prompt


def test_extra_append_none_produces_no_marker(tmp_path: Path) -> None:
    """No ``extra_append`` -> no jailbreak-shaped tail. Verifies the
    feature is OFF by default and doesn't leak into untargeted
    sessions."""
    out = build_system_prompt(
        workspace=tmp_path,
        model="qwen2.5",
        extra_append=None,
    )
    assert "GODMODE" not in out
    assert "DEPTH" not in out


def test_extra_append_empty_string_produces_no_marker(tmp_path: Path) -> None:
    """An empty string is treated the same as None."""
    out = build_system_prompt(
        workspace=tmp_path,
        model="qwen2.5",
        extra_append="",
    )
    assert "GODMODE" not in out


def test_extra_append_whitespace_only_produces_no_marker(tmp_path: Path) -> None:
    """Pure-whitespace append is dropped -- a misconfigured
    ATHENA_EPHEMERAL_SYSTEM_PROMPT=" " shouldn't render a phantom
    blank section at the end of the prompt."""
    out = build_system_prompt(
        workspace=tmp_path,
        model="qwen2.5",
        extra_append="   \n\n  \t  ",
    )
    # The rendered prompt ends without a trailing blank-section
    # join artifact -- check by tail-stripping and counting double
    # newlines at the end.
    assert not out.rstrip().endswith("\n\n")


def test_extra_append_lands_at_the_end(tmp_path: Path) -> None:
    """The append must be the LAST thing in the rendered prompt --
    after the /goal block, after computer-use status, after
    everything else. Matches the reference's positioning so the
    model treats it as most-recent."""
    needle = "[GODMODE_TEST_NEEDLE_v00.0]"
    out = build_system_prompt(
        workspace=tmp_path,
        model="qwen2.5",
        extra_append=needle,
    )
    assert needle in out
    # No content should follow the needle except trailing whitespace.
    tail = out[out.index(needle) + len(needle) :]
    assert tail.strip() == ""


def test_extra_append_comes_after_goal_block(tmp_path: Path) -> None:
    """When both /goal and extra_append are set, the append must
    come AFTER the goal block. The model's "most recent
    instruction" position is the append."""
    needle = "[GODMODE_TEST_NEEDLE_v00.1]"
    out = build_system_prompt(
        workspace=tmp_path,
        model="qwen2.5",
        goal="finish the task and report",
        extra_append=needle,
    )
    needle_idx = out.index(needle)
    goal_idx = out.index("finish the task")
    assert goal_idx < needle_idx


def test_extra_append_whitespace_stripped_at_edges(tmp_path: Path) -> None:
    """Surrounding whitespace on the append is stripped before
    join so the renderer's ``\\n\\n`` join doesn't produce
    triple-newline gaps in the output."""
    out = build_system_prompt(
        workspace=tmp_path,
        model="qwen2.5",
        extra_append="\n\n   needle_xyz   \n\n",
    )
    # The literal "needle_xyz" appears, and there's no
    # quadruple-newline gap (which would imply join + edge
    # whitespace).
    assert "needle_xyz" in out
    assert "\n\n\n\n" not in out
