"""Importer tests: ingest a SKILL.md or skill dir into the skill tree."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from athena.skills.importer import import_archive, import_skill


def _write_minimal_skill(dest: Path, name: str = "demo") -> Path:
    """Write a minimal-but-valid skill at ``dest/<name>/SKILL.md`` and
    return the path to the skill dir."""
    skill_dir = dest / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: a short description\n---\n\nbody\n",
        encoding="utf-8",
    )
    return skill_dir


def test_import_from_dir_installs(isolated_home: Path, tmp_path: Path) -> None:
    src = _write_minimal_skill(tmp_path / "src", "from-dir")
    base = isolated_home / ".athena" / "skills"
    result = import_skill(src, base=base)
    assert result.status == "installed"
    assert result.name == "from-dir"
    assert result.dest == base / "from-dir"
    assert (base / "from-dir" / "SKILL.md").exists()


def test_import_from_bare_skill_md(isolated_home: Path, tmp_path: Path) -> None:
    """A loose SKILL.md file (not in a parent dir) imports under the
    name in its frontmatter."""
    src_dir = tmp_path / "loose"
    src_dir.mkdir()
    skill_md = src_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: loose-one\ndescription: bare md\n---\n\nbody\n",
        encoding="utf-8",
    )
    base = isolated_home / ".athena" / "skills"
    result = import_skill(skill_md, base=base)
    assert result.status == "installed"
    assert result.name == "loose-one"
    assert (base / "loose-one" / "SKILL.md").exists()


def test_import_from_wrapper_dir(isolated_home: Path, tmp_path: Path) -> None:
    """A directory that contains exactly one ``*/SKILL.md`` one level
    down (typical extracted tarball) is unwrapped automatically."""
    wrapper = tmp_path / "wrapper"
    inner = wrapper / "real-name"
    inner.mkdir(parents=True)
    (inner / "SKILL.md").write_text(
        "---\nname: real-name\ndescription: through wrapper\n---\n\nbody\n",
        encoding="utf-8",
    )
    base = isolated_home / ".athena" / "skills"
    result = import_skill(wrapper, base=base)
    assert result.status == "installed"
    assert result.name == "real-name"


def test_import_validates_frontmatter(isolated_home: Path, tmp_path: Path) -> None:
    """A SKILL.md with required-field problems is rejected without
    landing on disk."""
    src = tmp_path / "src" / "broken"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text(
        "---\nname: \"NOT-LOWERCASE\"\ndescription: bad name\n---\n",
        encoding="utf-8",
    )
    base = isolated_home / ".athena" / "skills"
    result = import_skill(src, base=base)
    assert result.status == "rejected"
    assert result.errors  # non-empty
    assert not (base / "NOT-LOWERCASE").exists()


def test_import_abort_on_existing(isolated_home: Path, tmp_path: Path) -> None:
    base = isolated_home / ".athena" / "skills"
    base.mkdir(parents=True)
    _write_minimal_skill(base, "already-here")
    src = _write_minimal_skill(tmp_path / "src", "already-here")
    result = import_skill(src, base=base)
    assert result.status == "skipped"


def test_import_overwrite(isolated_home: Path, tmp_path: Path) -> None:
    base = isolated_home / ".athena" / "skills"
    base.mkdir(parents=True)
    _write_minimal_skill(base, "to-overwrite")
    (base / "to-overwrite" / "SKILL.md").write_text(
        "---\nname: to-overwrite\ndescription: OLD\n---\nold body\n",
        encoding="utf-8",
    )
    src = _write_minimal_skill(tmp_path / "src", "to-overwrite")
    (src / "SKILL.md").write_text(
        "---\nname: to-overwrite\ndescription: NEW\n---\nnew body\n",
        encoding="utf-8",
    )
    result = import_skill(src, base=base, on_conflict="overwrite")
    assert result.status == "overwritten"
    assert "NEW" in (base / "to-overwrite" / "SKILL.md").read_text()


def test_import_rename_on_collision(isolated_home: Path, tmp_path: Path) -> None:
    base = isolated_home / ".athena" / "skills"
    base.mkdir(parents=True)
    _write_minimal_skill(base, "collide")
    src = _write_minimal_skill(tmp_path / "src", "collide")
    result = import_skill(src, base=base, on_conflict="rename")
    assert result.status == "renamed"
    assert result.name == "collide-2"
    assert (base / "collide").exists()  # original preserved
    assert (base / "collide-2").exists()


def test_import_zip_archive(isolated_home: Path, tmp_path: Path) -> None:
    """A .zip containing a skill dir imports via the archive entry point."""
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "from-zip/SKILL.md",
            "---\nname: from-zip\ndescription: ziplet\n---\nzipped body\n",
        )
    base = isolated_home / ".athena" / "skills"
    result = import_archive(archive, base=base)
    assert result.status == "installed"
    assert result.name == "from-zip"
    assert (base / "from-zip" / "SKILL.md").exists()


def test_import_zip_rejects_path_traversal(
    isolated_home: Path, tmp_path: Path,
) -> None:
    """Archive members with ``..`` segments must not be extracted —
    otherwise a malicious bundle could write outside the temp dir."""
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.md", b"pwned")
    base = isolated_home / ".athena" / "skills"
    result = import_archive(archive, base=base)
    assert result.status == "rejected"
    assert any("unsafe" in e for e in result.errors)


def test_import_tar_gz_archive(isolated_home: Path, tmp_path: Path) -> None:
    archive = tmp_path / "demo.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        body = b"---\nname: from-tar\ndescription: tarred\n---\nbody\n"
        info = tarfile.TarInfo(name="from-tar/SKILL.md")
        info.size = len(body)
        tf.addfile(info, io.BytesIO(body))
    base = isolated_home / ".athena" / "skills"
    result = import_archive(archive, base=base)
    assert result.status == "installed"
    assert result.name == "from-tar"
