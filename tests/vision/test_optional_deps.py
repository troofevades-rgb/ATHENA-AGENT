"""Guard: a base/headless install (no ``[vision]`` extra) must still launch.

`athena/tools/__init__.py` imports the vision tool registration at startup;
the vision module must therefore be importable WITHOUT Pillow/imagehash.
This reproduces the real crash a fresh `pip install -e .` hit
(`ModuleNotFoundError: No module named 'imagehash'` at import of
`athena.tools`) and pins it fixed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def test_tools_import_without_imagehash() -> None:
    """Importing athena.tools must not require the optional imagehash dep.

    Run in a subprocess so we can block the dep before any athena import —
    the parent test process has already imported these modules.
    """
    code = textwrap.dedent(
        """
        import sys
        # Simulate a base install where the [vision] extra isn't present.
        sys.modules["imagehash"] = None  # makes `import imagehash` raise ImportError
        import athena.tools  # this is the import that crashed on the user's machine
        from athena.vision import imageops, analyze  # noqa: F401
        assert imageops._HAVE_IMAGE_DEPS is False, "guard flag should be False"
        print("LAUNCH-OK")
        """
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, f"athena.tools failed to import without imagehash:\n{r.stderr}"
    assert "LAUNCH-OK" in r.stdout


def test_vision_tool_reports_missing_deps_cleanly(monkeypatch) -> None:
    """With the deps absent, vision_analyze returns a structured 'install
    the extra' message instead of raising."""
    import types

    from athena.vision import analyze

    monkeypatch.setattr(analyze, "_HAVE_IMAGE_DEPS", False)
    out = analyze._run(
        mode="phash",
        path="does-not-matter.png",
        _cfg=types.SimpleNamespace(vision_enabled=True),
    )
    assert "athena-coder[vision]" in out
