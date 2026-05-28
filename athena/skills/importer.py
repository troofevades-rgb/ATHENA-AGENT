"""Skill ingestion: copy an external SKILL.md (or a skill dir) into
the user-global or workspace skills tree.

Surface:

    import_skill(source, *, base, on_conflict="abort") -> ImportResult

``source`` may be:

  - a directory containing a top-level ``SKILL.md`` (the canonical shape)
  - a bare ``SKILL.md`` file (wrapped automatically in a dir whose name
    comes from the frontmatter ``name``)
  - a directory that contains one SKILL.md one level down (e.g. an
    extracted bundle); the wrapper dir is collapsed away.

``base`` is either ``Path.home() / ".athena" / "skills"`` (user-global)
or ``<workspace> / ".athena" / "skills"`` (workspace). The caller picks.

Validation runs *before* anything lands on disk so a bad SKILL.md is
rejected without polluting the tree. Successful imports invalidate
the loader's body cache for the affected name so a subsequent
discovery sees the new content.

Foreign-bundle support (``.zip``, ``.tar.gz``) is layered on top
in :func:`import_archive`.
"""

from __future__ import annotations

import dataclasses
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Literal

from .frontmatter import FrontmatterError, parse_frontmatter
from .validation import validate_skill

ConflictPolicy = Literal["abort", "overwrite", "rename"]


@dataclasses.dataclass
class ImportResult:
    """Outcome of an import call.

    ``status`` is one of:
      - "installed" — fresh install at ``dest``
      - "overwritten" — existing skill replaced at ``dest``
      - "renamed" — collision detected, installed under a unique name
      - "rejected" — validation errors prevented install (``errors`` populated)
      - "skipped" — existing skill detected with conflict policy "abort"
    """

    status: str
    dest: Path | None
    name: str
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)


def _resolve_source_dir(source: Path) -> Path:
    """Normalise ``source`` to a directory containing SKILL.md.

    Accepts:
      - a directory with a top-level SKILL.md
      - a bare SKILL.md file (its parent becomes the source dir)
      - a directory containing exactly one ``*/SKILL.md`` one level
        down (common with extracted tarballs that have a wrapper dir)

    Raises ValueError when none of the above shapes match.
    """
    if source.is_file() and source.name == "SKILL.md":
        return source.parent
    if not source.is_dir():
        raise ValueError(f"source is not a directory or SKILL.md: {source}")
    if (source / "SKILL.md").is_file():
        return source
    # Look one level down for a wrapper dir.
    candidates = [p for p in source.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == 0:
        raise ValueError(f"no SKILL.md found in {source} or any immediate subdir")
    raise ValueError(
        f"{source} contains multiple skill subdirs ({len(candidates)}); "
        "extract them individually"
    )


def _unique_name(base: Path, name: str) -> str:
    """Pick a free name under ``base`` by appending ``-N``."""
    if not (base / name).exists():
        return name
    n = 2
    while (base / f"{name}-{n}").exists():
        n += 1
    return f"{name}-{n}"


def import_skill(
    source: Path,
    *,
    base: Path,
    on_conflict: ConflictPolicy = "abort",
) -> ImportResult:
    """Copy a skill into ``base`` after validating it.

    Doesn't fire any side effects beyond the disk write — callers
    that want the live Agent to pick the change up immediately should
    follow with ``loader.invalidate`` and ``Agent.reload_skills``.
    """
    try:
        src_dir = _resolve_source_dir(source)
    except ValueError as e:
        return ImportResult(status="rejected", dest=None, name="", errors=[str(e)])

    # Validate first so a malformed frontmatter surfaces with the
    # validator's actionable error messages rather than a raw
    # FrontmatterError on the ``name`` read below.
    errors = validate_skill(src_dir)
    if errors:
        return ImportResult(status="rejected", dest=None, name="", errors=errors)

    # Read the canonical name from the frontmatter — the source dir's
    # name on disk is irrelevant; the frontmatter ``name`` is the
    # identifier the agent uses. validate_skill above guarantees this
    # parse succeeds.
    try:
        parsed = parse_frontmatter(src_dir / "SKILL.md")
    except FrontmatterError as e:
        return ImportResult(
            status="rejected", dest=None, name="",
            errors=[f"frontmatter: {e}"],
        )
    if parsed is None:
        return ImportResult(
            status="rejected", dest=None, name="",
            errors=[f"could not parse frontmatter at {src_dir / 'SKILL.md'}"],
        )
    fm, _ = parsed
    name = fm.name

    base.mkdir(parents=True, exist_ok=True)
    dest = base / name
    status = "installed"
    if dest.exists():
        if on_conflict == "abort":
            return ImportResult(
                status="skipped", dest=dest, name=name,
                warnings=[f"skill {name!r} already exists at {dest}; aborting"],
            )
        if on_conflict == "overwrite":
            shutil.rmtree(dest)
            status = "overwritten"
        elif on_conflict == "rename":
            new_name = _unique_name(base, name)
            dest = base / new_name
            name = new_name
            status = "renamed"

    # copytree refuses to overwrite, so the rmtree above is required
    # for the overwrite path. dirs_exist_ok=False keeps us honest if
    # a subsequent edit ever drops the rmtree.
    shutil.copytree(src_dir, dest, dirs_exist_ok=False)

    # Drop any cached body for this name so the next discovery /
    # skill_view sees the freshly imported content. Workspace key may
    # not match (we don't know what workspace context the caller will
    # later use), so invalidate broadly by clearing all matching
    # entries.
    from . import loader as _loader
    for key in list(_loader._BODY_CACHE):
        if key[1] == name:
            _loader._BODY_CACHE.pop(key, None)

    return ImportResult(status=status, dest=dest, name=name)


def import_archive(
    archive: Path,
    *,
    base: Path,
    on_conflict: ConflictPolicy = "abort",
) -> ImportResult:
    """Extract ``archive`` (``.zip`` or ``.tar.gz`` / ``.tgz``) into a
    temp dir and delegate to :func:`import_skill`.

    The temp dir is removed regardless of outcome. Archive members
    with absolute paths or ``..`` segments are rejected up front so
    a malicious bundle can't write outside the extraction root.
    """
    suffixes = "".join(archive.suffixes[-2:]).lower()
    is_tar = suffixes.endswith(".tar.gz") or archive.suffix.lower() in {".tgz", ".tar"}
    is_zip = archive.suffix.lower() == ".zip"
    if not (is_tar or is_zip):
        return ImportResult(
            status="rejected", dest=None, name="",
            errors=[f"unsupported archive type: {archive.name}"],
        )

    with tempfile.TemporaryDirectory(prefix="athena-skill-import-") as td:
        extract_root = Path(td)
        try:
            if is_zip:
                with zipfile.ZipFile(archive) as zf:
                    for info in zf.infolist():
                        if Path(info.filename).is_absolute() or ".." in Path(info.filename).parts:
                            return ImportResult(
                                status="rejected", dest=None, name="",
                                errors=[f"archive contains unsafe member: {info.filename}"],
                            )
                    zf.extractall(extract_root)
            else:
                with tarfile.open(archive, mode="r:*") as tf:
                    for m in tf.getmembers():
                        if Path(m.name).is_absolute() or ".." in Path(m.name).parts:
                            return ImportResult(
                                status="rejected", dest=None, name="",
                                errors=[f"archive contains unsafe member: {m.name}"],
                            )
                    # Python 3.12+: filter="data" hardens extraction.
                    if hasattr(tarfile, "data_filter"):
                        tf.extractall(extract_root, filter="data")
                    else:
                        tf.extractall(extract_root)
        except (zipfile.BadZipFile, tarfile.TarError, OSError) as e:
            return ImportResult(
                status="rejected", dest=None, name="",
                errors=[f"failed to extract {archive.name}: {e}"],
            )

        return import_skill(extract_root, base=base, on_conflict=on_conflict)
