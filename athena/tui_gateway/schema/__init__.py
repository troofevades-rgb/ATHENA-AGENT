"""Authoritative protocol schema for the TUI gateway.

The JSON Schema at ``v1/protocol.json`` is the single source of truth
for the wire format between the Python ``tui_gateway`` and the Ink
TUI. Both sides — ``athena/tui_gateway/events.py`` (dataclasses) and
``ui-tui/src/transport/protocol.ts`` (interfaces) — must mirror it.
Drift between any two of {schema, Python, TS} is caught by
``tests/tui_gateway/test_schema_parity.py``.

Authored in TUI sprint foundation step 2. Codegen for one or both
sides is a deferred follow-up (see TUI_SPRINT.md). For now, both
type files are hand-maintained; the parity test is the safety net.

Why no codegen yet: the protocol surface is small (21 types, 13
events, 5 commands), the bundle build is already a multi-step
pipeline, and a parity test catches drift just as effectively as
codegen would. When a third consumer appears (web dashboard, ACP
sharing the same types), revisit and add codegen for both sides.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_SCHEMA_DIR = Path(__file__).resolve().parent
_PROTOCOL_PATH = _SCHEMA_DIR / "v1" / "protocol.json"


@lru_cache(maxsize=1)
def load_protocol() -> dict[str, Any]:
    """Load and cache the protocol schema. Returns the raw dict.

    Cached for the process lifetime — the file is built into the
    package and never mutates at runtime.
    """
    with open(_PROTOCOL_PATH, encoding="utf-8") as f:
        return json.load(f)


def event_schema(type_literal: str) -> dict[str, Any]:
    """Return the schema fragment for a given event type literal.

    Raises ``KeyError`` if the type is not in the index.
    """
    proto = load_protocol()
    ref = proto["event_index"][type_literal]["$ref"]
    return _resolve_ref(proto, ref)


def command_schema(type_literal: str) -> dict[str, Any]:
    """Return the schema fragment for a given command type literal."""
    proto = load_protocol()
    ref = proto["command_index"][type_literal]["$ref"]
    return _resolve_ref(proto, ref)


def event_type_literals() -> list[str]:
    """All event ``type`` literals declared by the schema."""
    return list(load_protocol()["event_index"].keys())


def command_type_literals() -> list[str]:
    """All command ``type`` literals declared by the schema."""
    return list(load_protocol()["command_index"].keys())


def _resolve_ref(proto: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a ``#/$defs/Name`` reference within the loaded schema.

    Only supports the internal-fragment refs we use in protocol.json;
    we deliberately don't pull in a full JSON-Pointer library.
    """
    if not ref.startswith("#/$defs/"):
        raise ValueError(f"unsupported $ref shape: {ref!r}")
    name = ref[len("#/$defs/") :]
    return proto["$defs"][name]


__all__ = [
    "load_protocol",
    "event_schema",
    "command_schema",
    "event_type_literals",
    "command_type_literals",
]
