"""Verify the Ink TUI bundle is correctly shipped alongside the
Python package.

If this test fails, ``pip install athena-coder`` will install a
broken interactive REPL — ``athena`` will start, fail to spawn
the TUI, and exit. Catches:

  - The bundle wasn't built / copied into ``athena/_tui_bundle/``.
  - ``pyproject.toml`` doesn't list it as package_data.
  - The bundle is unexpectedly small (build failure that
    produced an empty file).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_tui_bundle_ships_with_package():
    """``athena/_tui_bundle/main.js`` must exist and be a real
    JS bundle (not a stub). Built via ``cd ui-tui && bun run
    build`` — the build target auto-copies into this location."""
    bundle = Path(__file__).resolve().parents[2] / "athena" / "_tui_bundle" / "main.js"
    assert bundle.exists(), f"missing TUI bundle at {bundle}. Run: cd ui-tui && bun run build"
    size = bundle.stat().st_size
    # The minified bundle is ~360 KB. Anything under 10 KB is
    # almost certainly a build failure (empty / stub output).
    assert size > 10_000, (
        f"TUI bundle suspiciously small ({size} bytes). Likely a "
        "build failure — rebuild via: cd ui-tui && bun run build"
    )


def test_pyproject_includes_bundle_in_package_data():
    """The bundle is listed under ``[tool.setuptools.package-data]``
    so ``pip install`` ships it in the wheel."""
    try:
        import tomllib  # 3.11+ stdlib
    except ImportError:
        import tomli as tomllib  # 3.10 back-port; pyproject.toml lists it

    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    package_data = (
        data.get("tool", {}).get("setuptools", {}).get("package-data", {}).get("athena", [])
    )
    assert "_tui_bundle/main.js" in package_data, (
        "pyproject.toml does not include _tui_bundle/main.js under "
        "[tool.setuptools.package-data]. The wheel won't ship the "
        "TUI bundle without this entry."
    )


def test_bundle_starts_with_js_shebang_or_minified_js():
    """Sanity — first few bytes look like JavaScript, not (e.g.)
    a stray ELF binary or HTML error page from a bad copy."""
    bundle = Path(__file__).resolve().parents[2] / "athena" / "_tui_bundle" / "main.js"
    if not bundle.exists():
        pytest.skip("bundle missing — covered by test_tui_bundle_ships_with_package")
    head = bundle.read_bytes()[:200].decode("utf-8", errors="replace")
    # Bun's minified output typically starts with a `var` decl or
    # an immediately-invoked function expression. We just want to
    # rule out gross corruption — a brittle exact-prefix match
    # would fail on bundler version bumps.
    assert any(token in head for token in ("var ", "function", "import ", "const ", "let ")), (
        f"bundle head doesn't look like JS: {head[:80]!r}"
    )
