"""Persistent memory subsystem.

The public surface lives in :mod:`athena.memory.store` (the
profile-keyed provider façade) and :mod:`athena.memory.providers`
(the :class:`~athena.memory.providers.base.MemoryProvider` ABC plus
the built-in :class:`~athena.memory.providers.builtin_file.BuiltinFileProvider`).

The workspace-keyed legacy API that used to live at this module's
top level (``load_memory_index`` / ``write_memory`` / ``list_memories``
/ ``delete_memory`` / ``memory_dir`` / ``_slugify`` / ``MemoryFile``)
was retired at R2 stage 5. Callers should now go through
``athena.memory.store`` with the ``workspace=`` kwarg added in stage 1.
The stage-4 :func:`athena.profiles.migration.migrate_workspace_memory`
helper handles the one-shot disk migration from the old
``~/.athena/projects/<slug>/memory/`` layout.
"""

from __future__ import annotations
