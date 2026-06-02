"""Regression pin: the legacy ``athena.hooks`` deprecation shim is
gone.

The shim landed in Phase 0 as a back-compat surface for external
code that imported ``athena.hooks.load_hooks`` /
``athena.hooks.fire`` before the settings.json hooks block was
migrated to ``ShellHookPlugin`` (``athena/plugins/bundled/
shell_hook/``). It emitted a ``DeprecationWarning`` on import and
delegated to the plugin internally; the deletion plan was "the
release after we cut next."

Removed in the 0.3.0 dogfood sweep. This pin enforces:

  * ``from athena import hooks`` raises ``ImportError``. Without
    this, a sleepy refactor could re-introduce the shim
    accidentally.
  * The error message Python produces names ``athena.hooks``, so
    any external caller hitting it sees a clear migration signal.

If a real external user files an issue about needing the shim
back, the right answer is "import from athena.plugins.bundled.
shell_hook directly", not "restore the shim". That's what these
pins document.
"""

from __future__ import annotations

import pytest


def test_athena_hooks_module_is_gone() -> None:
    """``import athena.hooks`` must fail. The shim has been removed;
    callers route through the plugin layer."""
    with pytest.raises(ImportError):
        import athena.hooks  # noqa: F401


def test_from_athena_import_hooks_fails() -> None:
    """The ``from athena import hooks`` form also fails (different
    import machinery path; pin both to catch a re-introduction in
    either shape)."""
    with pytest.raises(ImportError):
        from athena import hooks  # noqa: F401


def test_shell_hook_plugin_is_the_replacement() -> None:
    """The plugin module that owns settings.json hooks now is
    importable -- so the documented replacement path actually
    works. If this fails, the migration left external callers
    nowhere to go."""
    from athena.plugins.bundled.shell_hook import plugin

    assert hasattr(plugin, "ShellHookPlugin")
