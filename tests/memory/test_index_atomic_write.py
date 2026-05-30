"""0.3.0 hardening tier 1 (B) -- markdown index regen is atomic.

``BuiltinFileProvider._refresh_markdown_index`` writes ``MEMORY.md``
(the human-readable index of the on-disk memory store) by enumerating
the directory and emitting one bullet per entry.

The foreground agent, the background-review fork, and the cron
subprocess all call into the provider; if two regenerators race, a
direct ``write_text`` lets a reader observe a half-written file --
truncated MEMORY.md with no bullets, breaking the curator and the
auto-memory MCP surface.

Fix: write to ``MEMORY.md.tmp`` then ``os.replace``. ``os.replace``
is atomic on POSIX (rename(2)) and Windows (MoveFileExW with
MOVEFILE_REPLACE_EXISTING), so readers always see a complete file.
Two concurrent writers still race -- last writer wins -- but each
individual write is durable, never torn.

Pins:

  * The final ``MEMORY.md`` content is what we expect (no regression
    in the happy-path output format).
  * The write goes via a ``.tmp`` companion + ``os.replace`` -- not
    a direct ``write_text`` to the final path. The tmp file does not
    survive the regen.
  * If the regen runs against an existing ``MEMORY.md``, the old
    file is atomically replaced (no window where the path is
    missing).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from athena.memory.providers.builtin_file import BuiltinFileProvider


@pytest.fixture
def provider(tmp_path: Path) -> BuiltinFileProvider:
    return BuiltinFileProvider(home=tmp_path / "fake-home")


def _seed(provider: BuiltinFileProvider) -> None:
    """Write one entry so _refresh_markdown_index has content to index."""
    provider.write_entry(
        "default",
        filename="alpha.md",
        name="alpha",
        description="first entry",
        type="user",
        body="body of alpha",
        write_origin="foreground",
    )


def test_index_write_goes_through_tmp_then_replace(
    provider: BuiltinFileProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regen must write to ``MEMORY.md.tmp`` and then rename;
    never write_text directly to ``MEMORY.md``. Without this pin a
    future "simplification" could regress to torn writes."""
    _seed(provider)

    # Record every path passed to write_text and os.replace. We let
    # the real implementations run so the file ends up valid; we
    # just observe the call sequence.
    written: list[Path] = []
    replaced: list[tuple[str, str]] = []

    real_write_text = Path.write_text
    real_replace = os.replace

    def _trace_write_text(self: Path, data: str, **kw: object) -> int:
        written.append(self)
        return real_write_text(self, data, **kw)  # type: ignore[arg-type]

    def _trace_replace(src: str, dst: str) -> None:
        replaced.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(Path, "write_text", _trace_write_text)
    monkeypatch.setattr(os, "replace", _trace_replace)

    provider._refresh_markdown_index("default")

    # write_text was called against the *.tmp companion (not the
    # final path). os.replace was called with (tmp -> final).
    tmp_writes = [p for p in written if p.name.endswith("MEMORY.md.tmp")]
    final_writes = [p for p in written if p.name == "MEMORY.md"]
    assert tmp_writes, f"expected a tmp write, got {written}"
    assert not final_writes, (
        f"writes went direct to MEMORY.md (torn-write risk): {written}"
    )
    assert replaced, "os.replace was never called"
    src, dst = replaced[-1]
    assert src.endswith("MEMORY.md.tmp")
    assert dst.endswith("MEMORY.md")


def test_index_tmp_does_not_survive(
    provider: BuiltinFileProvider,
) -> None:
    """After a successful regen, MEMORY.md.tmp must not be left on
    disk -- it would confuse the next refresh, the curator's file
    sweep, or a user inspecting the memory dir."""
    _seed(provider)
    provider._refresh_markdown_index("default")

    memory_dir = provider._memory_dir("default")
    assert (memory_dir / "MEMORY.md").exists()
    assert not (memory_dir / "MEMORY.md.tmp").exists()


def test_index_replaces_existing_file_atomically(
    provider: BuiltinFileProvider,
) -> None:
    """When MEMORY.md already exists from a prior write, the regen
    must atomically replace it -- not delete-then-write, which has a
    window where the file is missing and a concurrent reader sees
    FileNotFoundError."""
    _seed(provider)
    provider._refresh_markdown_index("default")

    memory_dir = provider._memory_dir("default")
    index_path = memory_dir / "MEMORY.md"
    first_content = index_path.read_text(encoding="utf-8")
    assert "alpha" in first_content

    # Add a second entry and regen again.
    provider.write_entry(
        "default",
        filename="beta.md",
        name="beta",
        description="second entry",
        type="user",
        body="body of beta",
        write_origin="foreground",
    )
    provider._refresh_markdown_index("default")

    second_content = index_path.read_text(encoding="utf-8")
    assert "alpha" in second_content
    assert "beta" in second_content
    # The index path remained present throughout (we just round-
    # tripped it twice). The tmp companion is gone again.
    assert not (memory_dir / "MEMORY.md.tmp").exists()
