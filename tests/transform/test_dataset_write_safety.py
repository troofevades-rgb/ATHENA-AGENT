"""Write-safety tests for ``write_jsonl``.

The existing tests/transform/test_dataset.py covers shape correctness
(one-object-per-line, parent dir creation, overwrite semantics). What's
missing is the data-integrity story when training-data generation
overlaps with anything else touching the filesystem — large datasets,
mid-write interruption, and the JSON-encoding invariant for surprising
content (newlines inside fields, non-ASCII, large strings).

Why this matters: training datasets feed directly into the LoRA loop.
A single malformed line silently truncates the dataset (trl loaders
either bail or skip the rest of the file). And the loop runs unattended
overnight, so the first time anyone notices is the next morning when
the loss curve looks weird.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.transform.dataset import write_jsonl


def _read_jsonl(path: Path) -> list[dict]:
    """Strict parser: every line must be valid JSON or this raises."""
    out = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise AssertionError(
                    f"line {i} is not valid JSON: {e!s} — content={line!r}"
                ) from None
    return out


# ---------------------------------------------------------------------------
# Newline / unicode safety — encoder invariants
# ---------------------------------------------------------------------------


def test_newlines_in_content_are_escaped_not_inlined(tmp_path: Path) -> None:
    """Trajectory messages routinely contain multi-line content (tool
    outputs, code snippets, file contents). The JSONL writer MUST
    escape literal newlines into ``\\n`` so each example stays on
    one line — otherwise the file silently corrupts and trl reads
    half-examples."""
    examples = [
        {"messages": [{"role": "user", "content": "line one\nline two\nline three"}]},
        {"messages": [{"role": "assistant", "content": "a\n\nb\n\nc"}]},
    ]
    path = tmp_path / "out.jsonl"
    write_jsonl(path, examples)

    # File must have exactly 2 lines (one per example)
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 2, (
        f"expected 2 jsonl lines, got {len(lines)} — "
        f"newlines in content corrupted the file"
    )
    # Round-trip preserves the newlines
    loaded = _read_jsonl(path)
    assert loaded[0]["messages"][0]["content"] == "line one\nline two\nline three"
    assert loaded[1]["messages"][0]["content"] == "a\n\nb\n\nc"


def test_non_ascii_content_round_trips_via_utf8(tmp_path: Path) -> None:
    """Tool outputs contain emoji, CJK, accented chars. Must serialize
    as UTF-8 and read back byte-identical."""
    examples = [
        {"messages": [{"role": "user", "content": "owl 🦉 / 中文 / café / ñ"}]},
    ]
    path = tmp_path / "out.jsonl"
    write_jsonl(path, examples)
    loaded = _read_jsonl(path)
    assert loaded[0]["messages"][0]["content"] == "owl 🦉 / 中文 / café / ñ"
    # Defensive: the on-disk bytes are UTF-8, not escaped \uXXXX (the
    # latter would balloon a unicode-heavy dataset). json.dumps defaults
    # to ensure_ascii=True, so this assertion documents the actual
    # behavior in case anyone tunes the encoder.
    raw = path.read_bytes()
    # Either we use ensure_ascii (no raw 🦉) or we don't (raw 🦉 present)
    # — but the file MUST be valid UTF-8 regardless.
    raw.decode("utf-8")  # raises if not valid UTF-8


def test_large_example_does_not_truncate_or_split(tmp_path: Path) -> None:
    """A single trajectory turn can carry a huge tool result (e.g.,
    Read on a long file). One example must stay on one line, no
    matter how long that line is."""
    big_content = "x" * 100_000
    examples = [
        {"messages": [{"role": "tool", "content": big_content}]},
    ]
    path = tmp_path / "out.jsonl"
    write_jsonl(path, examples)
    loaded = _read_jsonl(path)
    assert len(loaded) == 1
    assert len(loaded[0]["messages"][0]["content"]) == 100_000


# ---------------------------------------------------------------------------
# Mid-write interruption — file integrity across crashes
# ---------------------------------------------------------------------------


def test_disk_full_during_write_leaves_target_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Atomic-rename contract: when write_jsonl fails mid-write, the
    TARGET path is unchanged (still has the prior content, or absent
    if there was nothing before). The half-written ``.tmp`` file is
    cleaned up.

    Prior writer was open("w") + per-line writes — a crash left a
    truncated file at the target. The atomic version writes to
    ``<path>.tmp`` then renames; mid-write failure cleans up tmp
    and leaves the target untouched."""
    # Seed the target with previous content so we can verify it
    # survives a failed second write
    examples = [{"id": i, "content": "row-" + str(i)} for i in range(20)]
    path = tmp_path / "out.jsonl"
    write_jsonl(path, [{"prev": True}])
    assert path.exists()
    prior_content = path.read_text(encoding="utf-8")

    # Wrap open() so write() fails after the 5th call. The new
    # writer opens ``path.tmp``, not ``path`` — match both.
    real_open = open
    write_count = [0]
    target_paths = (str(path), str(path.with_name(path.name + ".tmp")))

    class _FailingFile:
        def __init__(self, f):
            self._f = f

        def write(self, s):
            write_count[0] += 1
            if write_count[0] > 5:
                raise OSError(28, "No space left on device")
            return self._f.write(s)

        def flush(self):
            return self._f.flush()

        def fileno(self):
            return self._f.fileno()

        def __enter__(self):
            self._f.__enter__()
            return self

        def __exit__(self, *a):
            return self._f.__exit__(*a)

    def _wrapped(p, *a, **kw):
        f = real_open(p, *a, **kw)
        if str(p) in target_paths:
            return _FailingFile(f)
        return f

    import builtins as _bi
    monkeypatch.setattr(_bi, "open", _wrapped)

    with pytest.raises(OSError):
        write_jsonl(path, examples)

    monkeypatch.undo()

    # Atomic contract:
    # 1. Target path UNCHANGED (still has prior content)
    assert path.read_text(encoding="utf-8") == prior_content, (
        "target file was modified despite failed write — "
        "atomic-rename contract violated; previous data lost"
    )
    # 2. No leftover .tmp turd
    tmp_path_str = path.with_name(path.name + ".tmp")
    assert not tmp_path_str.exists(), (
        f"leftover {tmp_path_str.name} after failed write — "
        f"tmp cleanup didn't run"
    )


def test_overwrite_truncates_previous_content(tmp_path: Path) -> None:
    """Re-running the dataset builder must NOT leave stale tail from
    the previous run. ``open("w")`` truncates, so this is the
    expected behavior — pinning it explicitly because if anyone
    flips to ``"a"`` to add atomicity, this regresses silently."""
    path = tmp_path / "out.jsonl"
    # First write: 10 examples
    write_jsonl(path, [{"i": i} for i in range(10)])
    initial_size = path.stat().st_size

    # Second write: 2 examples — must REPLACE, not append
    write_jsonl(path, [{"i": 99}, {"i": 100}])
    final_size = path.stat().st_size

    assert final_size < initial_size, (
        "second write did not truncate — file is appending, "
        "which would silently mix old and new examples in the dataset"
    )
    loaded = _read_jsonl(path)
    assert len(loaded) == 2
    assert {ex["i"] for ex in loaded} == {99, 100}


def test_empty_input_writes_empty_file(tmp_path: Path) -> None:
    """A zero-example write must still produce an empty file (not skip
    the write). Caller code may depend on the file existing — for
    example, the deploy script checking for the dataset path before
    invoking the trainer."""
    path = tmp_path / "empty.jsonl"
    write_jsonl(path, [])
    assert path.exists()
    assert path.stat().st_size == 0
