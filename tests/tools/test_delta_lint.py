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
