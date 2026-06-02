"""`athena skill lint` — runs the frontmatter validator against installed
skills so manual SKILL.md edits get checked without a re-import.
"""

from __future__ import annotations

from pathlib import Path

from athena.cli import skill as skill_cli


def _write_skill(base: Path, name: str, *, state: str = "active") -> Path:
    d = base / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: a test skill.\nstate: {state}\n---\nbody\n",
        encoding="utf-8",
    )
    return d


def _patch_discovery(monkeypatch, mapping: dict[str, Path]) -> None:
    monkeypatch.setattr(
        skill_cli,
        "discover_skills",
        lambda *a, **k: {name: (None, d) for name, d in mapping.items()},
    )


def test_lint_valid_skill_exits_zero(tmp_path, monkeypatch) -> None:
    good = _write_skill(tmp_path, "good-skill")
    _patch_discovery(monkeypatch, {"good-skill": good})
    assert skill_cli.main(["lint", "good-skill"]) == 0


def test_lint_invalid_skill_exits_one(tmp_path, monkeypatch, capsys) -> None:
    bad = _write_skill(tmp_path, "bad-skill", state="bogus")
    _patch_discovery(monkeypatch, {"bad-skill": bad})
    assert skill_cli.main(["lint", "bad-skill"]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "invalid state" in out


def test_lint_all_flags_any_bad(tmp_path, monkeypatch) -> None:
    good = _write_skill(tmp_path, "good-skill")
    bad = _write_skill(tmp_path, "bad-skill", state="nope")
    _patch_discovery(monkeypatch, {"good-skill": good, "bad-skill": bad})
    assert skill_cli.main(["lint", "--all"]) == 1


def test_lint_all_clean_exits_zero(tmp_path, monkeypatch) -> None:
    a = _write_skill(tmp_path, "skill-a")
    b = _write_skill(tmp_path, "skill-b")
    _patch_discovery(monkeypatch, {"skill-a": a, "skill-b": b})
    assert skill_cli.main(["lint", "--all"]) == 0


def test_lint_requires_name_or_all(tmp_path, monkeypatch) -> None:
    _patch_discovery(monkeypatch, {})
    assert skill_cli.main(["lint"]) == 2


def test_lint_unknown_name_exits_one(tmp_path, monkeypatch) -> None:
    good = _write_skill(tmp_path, "good-skill")
    _patch_discovery(monkeypatch, {"good-skill": good})
    assert skill_cli.main(["lint", "nonexistent"]) == 1
