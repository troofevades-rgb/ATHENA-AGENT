#!/usr/bin/env python3
"""Fail when pyproject.toml's version disagrees with athena.__version__.

Runs in CI (lint workflow) so any release-bump that only touches one
of the two surfaces is caught before it ships. PyPI does not allow
re-uploads of the same version, so silently shipping a wheel where the
distribution version disagrees with what the running CLI reports would
be unrecoverable without a fresh patch release.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore[no-redef]

    repo_root = Path(__file__).resolve().parent.parent
    pyproject = tomllib.loads(
        (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    pyproject_version = pyproject["project"]["version"]

    sys.path.insert(0, str(repo_root))
    import athena  # noqa: E402  (sys.path manipulation must precede the import)

    if athena.__version__ != pyproject_version:
        print(
            f"FAIL: pyproject.toml version {pyproject_version!r} != "
            f"athena.__version__ {athena.__version__!r}",
            file=sys.stderr,
        )
        return 1
    print(f"OK: athena-coder {pyproject_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
