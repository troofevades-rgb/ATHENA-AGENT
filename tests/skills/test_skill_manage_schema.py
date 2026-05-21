"""skill_manage schema-discoverability tests (follow-up).

Before this fix, a model trying to call skill_manage would
typically spend several attempts probing the schema because:

  1. The `frontmatter` parameter description didn't mention
     that `description` is required INSIDE the dict (the
     underlying skill_create validation requires it, but the
     tool schema didn't surface that).
  2. The model would pass `description='...'` as a top-level
     kwarg — silently dropped (the function signature has
     no `description` param) → FrontmatterError on the
     missing dict key.
  3. `write_file` requires both file_path AND file_content;
     passing only file_path gave a terse error without a
     fix hint.

These tests pin the new behaviour: per-action requirements
are explicit in the schema description, and a malformed
create / write_file call gets a structured error message
that names the fix.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.tools.skill_tools import skill_manage
from athena.tools.registry import get_tool


# ---------------------------------------------------------------------------
# Schema discoverability — required keys are documented
# ---------------------------------------------------------------------------


def test_tool_description_lists_per_action_requirements():
    """The top-level tool description spells out the per-action
    required-args checklist so the model can read it once and
    construct the right call shape on the first try."""
    spec = get_tool("skill_manage")
    desc = spec.description
    # Every action's name appears in the per-action section.
    for action in (
        "create", "patch", "delete", "unarchive", "pin", "unpin", "write_file"
    ):
        assert action in desc
    # create's requirement is explicit.
    assert "frontmatter" in desc
    assert "description" in desc
    # write_file's both-required is explicit.
    assert "file_path AND file_content" in desc
    # And the don't-use-write_file-for-SKILL.md warning is
    # explicit (this was a separate model confusion in the
    # original transcript).
    assert "SKILL.md" in desc
    assert "patch" in desc.lower()  # "use action='patch'" is mentioned


def test_frontmatter_parameter_description_calls_out_required_keys():
    """The frontmatter parameter's own description tells the
    model that `description` MUST be inside it for action='create'.
    This is the load-bearing schema fix — previously the
    parameter type was just `{"type": "object"}` with no
    documentation of required keys."""
    spec = get_tool("skill_manage")
    fm_desc = spec.parameters["properties"]["frontmatter"]["description"]
    assert "description" in fm_desc
    # The patch semantics (partial updates) are also explicit.
    assert "partial" in fm_desc.lower() or "patch" in fm_desc.lower()


def test_frontmatter_schema_validates_description_shape():
    """The frontmatter parameter's JSONSchema has a typed
    `properties.description` entry so a model planner can
    catch a non-string / empty `description` at construction
    time, not just at tool-call time."""
    spec = get_tool("skill_manage")
    fm_schema = spec.parameters["properties"]["frontmatter"]
    props = fm_schema.get("properties", {})
    # description is documented + constrained.
    assert "description" in props
    desc_schema = props["description"]
    assert desc_schema["type"] == "string"
    assert desc_schema["minLength"] == 1
    # name is documented as optional-inside-frontmatter.
    assert "name" in props
    # Additional keys are allowed (frontmatter is open-ended).
    assert fm_schema.get("additionalProperties") is True


def test_tool_description_includes_copy_modify_examples():
    """The description includes concrete example tool calls
    a model can copy + modify — most models recover faster
    from a worked example than from a prose schema."""
    spec = get_tool("skill_manage")
    desc = spec.description
    # Three examples: create, patch, write_file.
    assert desc.count("skill_manage(") >= 3
    # Each example shows the right shape for its action.
    assert 'action="create"' in desc
    assert 'action="patch"' in desc
    assert 'action="write_file"' in desc
    # The create example actually puts description inside
    # frontmatter — the load-bearing model lesson.
    assert '"description":' in desc


def test_file_path_and_file_content_descriptions_mention_each_other():
    """The file_path and file_content parameter descriptions
    each call out that both are required together — so a
    model reading either schema entry sees the pair."""
    spec = get_tool("skill_manage")
    props = spec.parameters["properties"]
    assert "file_content" in props["file_path"]["description"]
    assert "file_path" in props["file_content"]["description"]


def test_name_description_clarifies_top_level_not_in_frontmatter():
    """`name` is a top-level kwarg, NOT a frontmatter key —
    the description says so to head off the model trying
    `frontmatter={"name": "..."}` and omitting the top-level
    name."""
    spec = get_tool("skill_manage")
    name_desc = spec.parameters["properties"]["name"]["description"]
    assert "top-level" in name_desc.lower() or "not inside" in name_desc.lower()


# ---------------------------------------------------------------------------
# Pre-flight error messages name the fix
# ---------------------------------------------------------------------------


def test_create_without_description_in_frontmatter_explains_fix(tmp_path: Path, monkeypatch):
    """Calling create with no `description` in frontmatter
    returns a structured error that NAMES the fix — "pass
    description INSIDE frontmatter, not as a top-level kwarg".
    Previously this was a generic FrontmatterError."""
    from athena.tools import file_ops

    file_ops._WORKSPACE = tmp_path  # avoid hitting the real workspace
    result = skill_manage(action="create", name="my-skill")
    payload = json.loads(result)
    assert payload["success"] is False
    assert "frontmatter" in payload["message"]
    assert "description" in payload["message"]
    # The fix is explicit — "INSIDE frontmatter, not as a
    # top-level kwarg".
    msg_lower = payload["message"].lower()
    assert "inside" in msg_lower
    assert "top-level" in msg_lower


def test_create_with_empty_description_string_explains_fix(tmp_path: Path):
    """frontmatter={"description": ""} also fails — the
    pre-flight catches whitespace-only too."""
    from athena.tools import file_ops

    file_ops._WORKSPACE = tmp_path
    result = skill_manage(
        action="create", name="my-skill", frontmatter={"description": "  "}
    )
    payload = json.loads(result)
    assert payload["success"] is False
    assert "description" in payload["message"]


def test_create_with_proper_frontmatter_succeeds(tmp_path: Path, monkeypatch):
    """Sanity: the new pre-flight doesn't break the happy
    path. With frontmatter['description'] set, create still
    works."""
    from athena.tools import file_ops
    from athena.skills import manager as skill_manager_module

    file_ops._WORKSPACE = tmp_path

    create_calls: list = []

    def _stub_create(name, fm, body, workspace):
        create_calls.append((name, fm, body, workspace))

    monkeypatch.setattr(skill_manager_module, "skill_create", _stub_create)
    result = skill_manage(
        action="create",
        name="my-skill",
        frontmatter={"description": "a real description"},
    )
    payload = json.loads(result)
    assert payload["success"] is True
    assert len(create_calls) == 1


def test_write_file_without_content_explains_fix(tmp_path: Path):
    """write_file with only file_path returns an error that
    names BOTH required args + steers toward action='patch' for
    SKILL.md body writes (the other common confusion)."""
    from athena.tools import file_ops

    file_ops._WORKSPACE = tmp_path
    result = skill_manage(
        action="write_file", name="my-skill", file_path="SKILL.md"
    )
    payload = json.loads(result)
    assert payload["success"] is False
    assert "file_path" in payload["message"]
    assert "file_content" in payload["message"]
    # The "use action='patch' for SKILL.md" hint is in the message.
    assert "patch" in payload["message"].lower()
    assert "skill.md" in payload["message"].lower()


def test_write_file_without_file_path_explains_fix(tmp_path: Path):
    """And the inverse — file_content alone without file_path
    is the same pair-requirement error."""
    from athena.tools import file_ops

    file_ops._WORKSPACE = tmp_path
    result = skill_manage(
        action="write_file", name="my-skill", file_content="hello"
    )
    payload = json.loads(result)
    assert payload["success"] is False
    assert "file_path" in payload["message"]
    assert "file_content" in payload["message"]


def test_write_file_with_both_works(tmp_path: Path, monkeypatch):
    """Sanity: with both args, write_file proceeds to the
    underlying manager."""
    from athena.tools import file_ops
    from athena.skills import manager as skill_manager_module

    file_ops._WORKSPACE = tmp_path

    wrote: list = []

    def _stub_write_file(name, file_path, file_content, workspace):
        wrote.append((name, file_path, file_content))

    monkeypatch.setattr(skill_manager_module, "skill_write_file", _stub_write_file)
    result = skill_manage(
        action="write_file",
        name="my-skill",
        file_path="references/foo.md",
        file_content="# Foo",
    )
    payload = json.loads(result)
    assert payload["success"] is True
    assert wrote == [("my-skill", "references/foo.md", "# Foo")]
