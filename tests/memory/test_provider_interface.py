"""MemoryProvider is an ABC; ensures subclasses must implement the contract."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from athena.memory.providers.base import MemoryEntry, MemoryProvider


def test_abc_cannot_be_instantiated():
    """MemoryProvider has abstractmethods; direct instantiation must fail."""
    with pytest.raises(TypeError):
        MemoryProvider()  # type: ignore[abstract]


def test_subclass_missing_abstract_method_fails():
    class Incomplete(MemoryProvider):
        def load_index(self, profile):
            return None

        # Missing the rest.

    with pytest.raises(TypeError, match="abstract"):
        Incomplete()  # type: ignore[abstract]


def test_subclass_with_all_abstract_methods_works():
    class Complete(MemoryProvider):
        def load_index(self, profile):
            return None

        def write_entry(self, profile, *, filename, name, description, type, body, write_origin):
            return Path("/dev/null")

        def list_entries(self, profile):
            return []

        def read_entry(self, profile, name):
            return None

        def delete_entry(self, profile, name):
            return False

        def query(self, profile, *, query, k=5):
            return []

    Complete()  # no exception


def test_lifecycle_hooks_default_to_noops():
    class Minimal(MemoryProvider):
        def load_index(self, profile):
            return None

        def write_entry(self, profile, **kwargs):
            return Path("/dev/null")

        def list_entries(self, profile):
            return []

        def read_entry(self, profile, name):
            return None

        def delete_entry(self, profile, name):
            return False

        def query(self, profile, *, query, k=5):
            return []

    p = Minimal()
    # No exception when calling either lifecycle hook.
    p.on_session_start("session-1")
    p.on_session_end("session-1")


def test_memory_entry_required_fields():
    """MemoryEntry can be constructed with required fields; defaults the rest."""
    now = datetime.now()
    e = MemoryEntry(
        name="x",
        description="d",
        type="user",
        body="b",
        write_origin="foreground",
        created_at=now,
        last_activity_at=now,
    )
    assert e.use_count == 0
    assert e.path is None
