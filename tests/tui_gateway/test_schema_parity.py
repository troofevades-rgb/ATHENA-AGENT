"""Parity tests: schema vs Python dataclasses vs TS interfaces.

The v1 JSON schema at ``athena/tui_gateway/schema/v1/protocol.json``
is the authoritative description of the wire protocol. Both the
Python dataclasses in ``athena/tui_gateway/events.py`` and the
TypeScript interfaces in ``ui-tui/src/transport/protocol.ts`` must
mirror it. These tests assert that they do.

Coverage:
  - Every event/command schema has a matching Python dataclass
  - Every dataclass has a matching schema entry
  - Field names agree (ignoring the discriminator literal)
  - The ``type`` literal const agrees
  - The TS interface file mentions every schema type literal
    (smoke check via text search — full TS AST parsing is out
    of scope here)
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from athena.tui_gateway import events as events_mod
from athena.tui_gateway.schema import (
    command_schema,
    command_type_literals,
    event_schema,
    event_type_literals,
    load_protocol,
)


# ---- helpers -------------------------------------------------------------


def _dataclass_for_type_literal(literal, *, kind):
    """Find the @dataclass in events_mod whose ``type`` field
    default equals ``literal`` AND whose class name ends in the
    expected suffix.

    ``kind`` is ``"event"`` or ``"command"``. Both directions can
    share a wire type string (notably ``"hello"`` since v2), so
    name-suffix is the disambiguator.
    """
    suffix = "Event" if kind == "event" else "Command"
    for name in dir(events_mod):
        if not name.endswith(suffix):
            continue
        obj = getattr(events_mod, name)
        if not dataclasses.is_dataclass(obj):
            continue
        f = obj.__dataclass_fields__.get("type")
        if f is None:
            continue
        if f.default == literal:
            return obj
    return None


def _schema_field_names(schema):
    """Field names declared in a schema, dropping the
    discriminator."""
    return set(schema.get("properties", {}).keys()) - {"type"}


def _dataclass_field_names(cls):
    """Dataclass field names, dropping the discriminator."""
    return {f.name for f in dataclasses.fields(cls)} - {"type"}


# ---- structural sanity ---------------------------------------------------


def test_schema_loads_with_expected_shape():
    p = load_protocol()
    assert p["protocol_version"] == 2
    assert "event_index" in p
    assert "command_index" in p
    assert "$defs" in p


def test_event_and_command_counts_match_known_surface():
    """The protocol is small and stable; pin the counts so an
    accidental addition or deletion shows up loudly here."""
    assert len(event_type_literals()) == 17  # +1: ask_question.request
    assert len(command_type_literals()) == 8  # +1: ask_question.reply


# ---- python parity: events ----------------------------------------------


@pytest.mark.parametrize("type_literal", event_type_literals())
def test_event_has_matching_python_dataclass(type_literal):
    schema = event_schema(type_literal)
    cls = _dataclass_for_type_literal(type_literal, kind="event")
    assert cls is not None, (
        "no @dataclass in athena.tui_gateway.events with "
        "type=" + repr(type_literal)
    )
    schema_fields = _schema_field_names(schema)
    dc_fields = _dataclass_field_names(cls)
    assert schema_fields == dc_fields, (
        cls.__name__
        + " fields "
        + repr(dc_fields)
        + " != schema fields "
        + repr(schema_fields)
        + " for type="
        + repr(type_literal)
    )


# ---- python parity: commands --------------------------------------------


@pytest.mark.parametrize("type_literal", command_type_literals())
def test_command_has_matching_python_dataclass(type_literal):
    schema = command_schema(type_literal)
    cls = _dataclass_for_type_literal(type_literal, kind="command")
    assert cls is not None, (
        "no @dataclass in athena.tui_gateway.events with "
        "type=" + repr(type_literal)
    )
    schema_fields = _schema_field_names(schema)
    dc_fields = _dataclass_field_names(cls)
    assert schema_fields == dc_fields, (
        cls.__name__
        + " fields "
        + repr(dc_fields)
        + " != schema fields "
        + repr(schema_fields)
        + " for type="
        + repr(type_literal)
    )


# ---- no orphan dataclasses ----------------------------------------------


def test_no_dataclass_without_schema_entry():
    """If someone adds an @dataclass to events.py with a ``type``
    literal but forgets to add a schema entry, this catches it."""
    known = set(event_type_literals()) | set(command_type_literals())
    orphans = []
    for name in dir(events_mod):
        obj = getattr(events_mod, name)
        if not dataclasses.is_dataclass(obj):
            continue
        f = obj.__dataclass_fields__.get("type")
        if f is None:
            continue
        if isinstance(f.default, str) and f.default not in known:
            orphans.append((obj.__name__, f.default))
    assert not orphans, (
        "dataclasses with unknown type literals: " + repr(orphans)
    )


# ---- typescript surface check (text-only smoke) -------------------------


_TS_PATH = Path(__file__).resolve().parents[2] / (
    "ui-tui/src/transport/protocol.ts"
)


def _ts_source():
    if not _TS_PATH.exists():
        pytest.skip("TS protocol file not found at " + str(_TS_PATH))
    return _TS_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "type_literal",
    event_type_literals() + command_type_literals(),
)
def test_ts_interface_mentions_type_literal(type_literal):
    """Smoke: every schema type literal appears as a quoted
    string literal in protocol.ts. Catches the 'forgot to add
    the TS side' regression without a full TS parser."""
    src = _ts_source()
    quoted = chr(34) + type_literal + chr(34)
    assert quoted in src, (
        "protocol.ts does not contain type literal "
        + repr(type_literal)
    )
