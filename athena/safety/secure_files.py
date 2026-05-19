"""Atomic writes for files containing secret material.

Every credential, OAuth token, API key, or any other file that must
never be world-readable goes through this module. The contract:

- File is created via os.open(O_EXCL, mode=0o600). There is no
  window where the file exists at a wider mode.
- Atomic replace: writes go to <path>.tmp.<pid>.<random> first, then
  os.replace swaps. A crash mid-write does not truncate the
  destination.
- fsync of the file AND the parent directory before replace.
  Survives power loss.

Public surface:
    secure_write_text(path, text, *, mode=0o600) -> None
    secure_write_json(path, obj, *, mode=0o600) -> None
    secure_read_text(path) -> str
    secure_read_json(path) -> Any
    ensure_secure_dir(path, *, mode=0o700) -> None
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import stat
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def ensure_secure_dir(path: Path | str, *, mode: int = 0o700) -> None:
    """Create ``path`` (and parents) at ``mode``.

    Existing dirs are not re-chmodded; if the directory exists at a
    wider mode, emit a warning so the user can audit and ``chmod``
    themselves rather than us silently mutating filesystem state.
    """
    path = Path(path)
    if path.exists():
        actual = stat.S_IMODE(path.stat().st_mode)
        if actual & 0o077:
            logger.warning(
                "Directory %s has mode 0o%o; recommend chmod 0o%o for credential storage",
                path,
                actual,
                mode,
            )
        return
    path.mkdir(parents=True, mode=mode, exist_ok=True)


def secure_write_text(path: Path | str, text: str, *, mode: int = 0o600) -> None:
    """Write ``text`` to ``path`` atomically at ``mode``.

    Steps:
      1. Open <path>.tmp.<pid>.<random> with O_CREAT|O_WRONLY|O_EXCL at ``mode``
      2. Write text, flush, fsync the fd
      3. fsync the parent directory (durability)
      4. os.replace tmp -> path (atomic on POSIX and Windows 10+)
      5. fsync the parent directory again
    """
    path = Path(path)
    ensure_secure_dir(path.parent)
    parent = path.parent
    suffix = f".tmp.{os.getpid()}.{secrets.token_hex(4)}"
    tmp_path = parent / (path.name + suffix)

    flags = os.O_CREAT | os.O_WRONLY | os.O_EXCL
    fd = os.open(tmp_path, flags, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
        raise

    dir_fd: int | None = None
    o_directory = getattr(os, "O_DIRECTORY", None)
    try:
        if o_directory is not None:
            try:
                dir_fd = os.open(parent, o_directory)
            except OSError:
                dir_fd = None
        if dir_fd is not None:
            os.fsync(dir_fd)
        os.replace(tmp_path, path)
        if dir_fd is not None:
            os.fsync(dir_fd)
    finally:
        if dir_fd is not None:
            os.close(dir_fd)


def secure_write_json(path: Path | str, obj: Any, *, mode: int = 0o600) -> None:
    text = json.dumps(obj, separators=(",", ":"), sort_keys=True)
    secure_write_text(path, text, mode=mode)


def secure_read_text(path: Path | str) -> str:
    path = Path(path)
    if path.exists():
        actual = stat.S_IMODE(path.stat().st_mode)
        if actual & 0o077:
            logger.warning(
                "File %s has mode 0o%o; recommend chmod 0o600 (contains secret material)",
                path,
                actual,
            )
    return path.read_text(encoding="utf-8")


def secure_read_json(path: Path | str) -> Any:
    return json.loads(secure_read_text(path))
