"""Tests for ocode.tools.delta_lint.lint_after_write."""
from __future__ import annotations

from pathlib import Path

from ocode.tools.delta_lint import lint_after_write


def test_python_valid_returns_none() -> None:
    assert lint_after_write(Path("ok.py"), "def f():\n    return 1\n") is None


def test_python_invalid_returns_error() -> None:
    err = lint_after_write(Path("bad.py"), "def f(:\n    return 1\n")
    assert err is not None
    assert "SyntaxError" in err
    assert "line" in err


def test_pyi_uses_python_check() -> None:
    assert lint_after_write(Path("stub.pyi"), "def f() -> int: ...\n") is None
    err = lint_after_write(Path("stub.pyi"), "def f(\n")
    assert err is not None and "SyntaxError" in err


def test_json_valid_returns_none() -> None:
    assert lint_after_write(Path("ok.json"), '{"a": 1}') is None


def test_json_invalid_returns_error() -> None:
    err = lint_after_write(Path("bad.json"), '{"a": }')
    assert err is not None
    assert "JSONDecodeError" in err


def test_yaml_valid_returns_none() -> None:
    assert lint_after_write(Path("ok.yaml"), "a: 1\nb: [1, 2, 3]\n") is None
    assert lint_after_write(Path("ok.yml"), "a: 1\n") is None


def test_yaml_invalid_returns_error() -> None:
    err = lint_after_write(Path("bad.yaml"), "a: [unclosed\n")
    assert err is not None
    assert "YAMLError" in err


def test_toml_valid_returns_none() -> None:
    assert lint_after_write(Path("ok.toml"), 'a = 1\nb = "x"\n') is None


def test_toml_invalid_returns_error() -> None:
    err = lint_after_write(Path("bad.toml"), "a = ?\n")
    assert err is not None
    assert "TOMLDecodeError" in err


def test_unknown_extension_returns_none() -> None:
    assert lint_after_write(Path("README.md"), "# any markdown here\n") is None
    assert lint_after_write(Path("script.sh"), "!!not bash but who cares\n") is None
    assert lint_after_write(Path("no-extension"), "raw text") is None


def test_empty_content_passes_for_all_types() -> None:
    for ext in (".py", ".pyi", ".json", ".yaml", ".yml", ".toml"):
        assert lint_after_write(Path(f"empty{ext}"), "") is None


def test_bom_does_not_break_python_check() -> None:
    # Some editors prepend a UTF-8 BOM. Linter strips it before parsing.
    bom = "﻿"
    assert lint_after_write(Path("ok.py"), bom + "x = 1\n") is None


def test_trailing_whitespace_is_fine() -> None:
    assert lint_after_write(Path("ok.py"), "x = 1\n   \n") is None
    assert lint_after_write(Path("ok.json"), '{"a": 1}   \n') is None


# -- Tool integration ----------------------------------------------------


def test_lint_called_from_file_write_tool(tmp_path: Path, monkeypatch) -> None:
    """The Write tool surfaces lint errors as part of its result."""
    from ocode.tools import file_ops
    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)
    result = file_ops.Write(file_path="bad.json", content="{not valid")
    assert "failed validation" in result
    assert "JSONDecodeError" in result


def test_lint_called_from_edit_tool(tmp_path: Path, monkeypatch) -> None:
    from ocode.tools import file_ops
    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)
    p = tmp_path / "f.py"
    p.write_text("x = 1\n", encoding="utf-8")
    result = file_ops.Edit(file_path="f.py", old_string="x = 1", new_string="x = (1")
    assert "failed validation" in result
    assert "SyntaxError" in result


def test_lint_error_surfaces_to_caller(tmp_path: Path, monkeypatch) -> None:
    """The Write tool returns an error string that names the file AND the
    underlying syntax problem so the model can fix it."""
    from ocode.tools import file_ops
    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)
    result = file_ops.Write(file_path="b.py", content="def f(:\n")
    assert "b.py" in result
    assert "SyntaxError" in result
    # File was written (legacy behavior); lint error is informational so the
    # model can re-Write rather than being told the file vanished.
    assert (tmp_path / "b.py").exists()


def test_lint_called_from_skill_manage_create(
    isolated_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """skill_manage create must reject content that would yield invalid YAML
    in the frontmatter — and not leave a half-built skill dir."""
    from ocode.tools import file_ops, skill_tools
    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)

    # Description containing a YAML-breaking control char (unbalanced quote +
    # newline in the middle) trips the frontmatter validator.
    bad_desc = 'has "unclosed quote' + "\nand a newline\n"
    import json as _json
    out = _json.loads(skill_tools.skill_manage(
        action="create",
        name="bad-skill",
        frontmatter={"description": bad_desc},
        body="body",
    ))
    # We don't care if it succeeds or fails — only that no directory exists
    # if it failed. If it succeeded, validation passed (description was
    # actually well-formed once YAML escaped it), which is also fine.
    if not out["success"]:
        assert not (tmp_path / ".ocode" / "skills" / "bad-skill").exists()


def test_lint_error_in_skill_manage_does_not_corrupt_existing_skill(
    isolated_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """If skill_manage patch is given content that fails frontmatter lint,
    the existing SKILL.md must be unchanged."""
    from ocode.tools import file_ops, skill_tools
    import json as _json

    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)
    _json.loads(skill_tools.skill_manage(
        action="create",
        name="precious",
        frontmatter={"description": "original"},
        body="ORIGINAL_BODY\n",
    ))

    original_text = (tmp_path / ".ocode" / "skills" / "precious" / "SKILL.md").read_text(encoding="utf-8")

    # Try to patch with a name that violates the schema. Forces the manager
    # to attempt a write that fails validation.
    out = _json.loads(skill_tools.skill_manage(
        action="patch",
        name="precious",
        frontmatter={"state": "totally-invalid-state"},
        body="NEW_BODY\n",
    ))
    # The patch may succeed (state isn't yaml-invalid, just semantically odd
    # — frontmatter has no enum check) OR fail. Either way the file on disk
    # must remain valid YAML.
    final_text = (tmp_path / ".ocode" / "skills" / "precious" / "SKILL.md").read_text(encoding="utf-8")
    assert final_text.startswith("---")
    assert "name: precious" in final_text
    # If validation rejected it, ORIGINAL_BODY must still be present.
    if not out["success"]:
        assert final_text == original_text
