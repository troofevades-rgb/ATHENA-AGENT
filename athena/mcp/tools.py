"""Curated MCP tool surface for athena (T3-02.2).

The 7 tools exposed to peer MCP clients are read-only and
snapshot-revert by design — no ``bash``, no ``Write``, no arbitrary
code execution. Athena's broader tool surface (file_ops.Write,
shell.Bash, etc.) is intentionally NOT advertised over MCP because
that would let any MCP client execute arbitrary code on the host.

Each tool descriptor follows the MCP spec shape: a ``name``,
``description``, and JSON-schema ``inputSchema``. The descriptor
list is exported via ``tools/list`` on handshake; each ``tools/call``
dispatches by name to a handler that returns the MCP-format result
``{"content": [{"type": "text", "text": "..."}]}`` (with optional
``"isError": true``).

The handlers are thin wrappers over existing athena modules:

- ``athena.safety.snapshots.SnapshotStore`` for snapshot + rollback
- ``athena.skills.discovery.discover_skills`` + ``loader.load_body``
- ``athena.memory.store.list_entries`` + ``read_entry``
- ``athena/audit/mutations-*.jsonl`` walked directly for queries
  (the existing audit module exposes only an appender; we read the
  JSONL files for the query side here)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool descriptors — sent to the client via tools/list
# ---------------------------------------------------------------------------


TOOL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "athena_snapshot_files",
        "description": (
            "Create a content-addressed snapshot of one or more files. "
            "Returns the snapshot_id; pass it to athena_rollback_files "
            "to restore."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute file paths to snapshot.",
                },
                "label": {
                    "type": "string",
                    "description": (
                        "Optional human-readable label stored alongside the snapshot sidecar."
                    ),
                },
            },
            "required": ["paths"],
        },
    },
    {
        "name": "athena_rollback_files",
        "description": (
            "Restore files to the state captured in a prior snapshot. "
            "Returns the list of paths restored."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "snapshot_id": {"type": "string"},
            },
            "required": ["snapshot_id"],
        },
    },
    {
        "name": "athena_list_skills",
        "description": ("List athena skills with name, description, state, and updated_at."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_archived": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include archived skills.",
                },
            },
        },
    },
    {
        "name": "athena_read_skill",
        "description": "Read the full body of a single skill by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "athena_list_memories",
        "description": (
            "List memory entries with name, description, and type. The "
            "profile argument defaults to athena's active profile."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string"},
            },
        },
    },
    {
        "name": "athena_read_memory",
        "description": "Read a single memory entry by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "profile": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "athena_audit_query",
        "description": (
            "Query athena's mutation audit log. Returns matching entries newest-first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": "ISO 8601 lower bound (inclusive).",
                },
                "until": {
                    "type": "string",
                    "description": "ISO 8601 upper bound (inclusive).",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Filter by tool_name field.",
                },
                "write_origin": {
                    "type": "string",
                    "description": (
                        "Filter by write_origin "
                        "(foreground/background_review/curator/migration/system)."
                    ),
                },
                "limit": {"type": "integer", "default": 100},
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------


@dataclass
class AthenaMCPTools:
    """Dispatch ``tools/call`` to athena modules.

    Construction parameters:
        workspace: anchor for skill discovery (defaults to cwd at
            server boot)
        memory_profile: profile name passed into memory.store helpers
        audit_dir: directory holding ``mutations-YYYY-MM.jsonl`` files
        snapshot_store: a configured
            :class:`athena.safety.snapshots.SnapshotStore`
        allow_write: reserved; no write tools advertised yet
    """

    workspace: Path
    memory_profile: str
    audit_dir: Path
    snapshot_store: Any  # SnapshotStore — Any to dodge the import cycle in __init__
    allow_write: bool = False

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch ``tools/call``. Returns the MCP-format result dict."""
        try:
            if name == "athena_snapshot_files":
                return self._snapshot_files(**arguments)
            if name == "athena_rollback_files":
                return self._rollback_files(**arguments)
            if name == "athena_list_skills":
                return self._list_skills(**arguments)
            if name == "athena_read_skill":
                return self._read_skill(**arguments)
            if name == "athena_list_memories":
                return self._list_memories(**arguments)
            if name == "athena_read_memory":
                return self._read_memory(**arguments)
            if name == "athena_audit_query":
                return self._audit_query(**arguments)
            return _error(f"unknown tool: {name}")
        except TypeError as e:
            # Missing/extra keyword argument from the client side. Surface
            # the issue rather than 500-ing on the wire.
            return _error(f"invalid arguments for {name}: {e}")
        except Exception as e:  # noqa: BLE001
            logger.exception("MCP tool %s failed", name)
            return _error(f"{name} failed: {e}")

    # ---- snapshot / rollback -----------------------------------------

    def _snapshot_files(self, paths: list[str], label: str = "") -> dict[str, Any]:
        if not paths:
            return _error("paths must be a non-empty array")
        resolved = [Path(p).expanduser().resolve() for p in paths]
        missing = [str(p) for p in resolved if not p.exists()]
        if missing:
            return _error(f"path(s) do not exist: {missing}")
        snap = self.snapshot_store._create_snapshot(
            tuple(resolved),
            session_id="mcp-server",
            tool_name=label or "athena_mcp_snapshot",
            tool_call_id=None,
            parent_session_id=None,
        )
        return _ok(
            f"snapshot_id: {snap.snapshot_id}\n"
            f"files: {len(resolved)}\n"
            f"label: {label or '(none)'}\n"
            f"tarball: {snap.tarball_path}"
        )

    def _rollback_files(self, snapshot_id: str) -> dict[str, Any]:
        if not snapshot_id:
            return _error("snapshot_id required")
        from ..safety.snapshots import SNAPSHOT_ROOT

        sidecars = list(
            Path(self.snapshot_store.root or SNAPSHOT_ROOT).rglob(f"{snapshot_id}.json")
        )
        if not sidecars:
            return _error(f"snapshot not found: {snapshot_id}")
        snap = self.snapshot_store._load_sidecar(sidecars[0])
        if snap is None:
            return _error(f"snapshot sidecar unreadable: {snapshot_id}")
        restored = self.snapshot_store.restore(snap)
        return _ok(
            f"restored {len(restored)} file(s) from snapshot {snapshot_id}:\n"
            + "\n".join(f"  {p}" for p in restored)
        )

    # ---- skills ------------------------------------------------------

    def _list_skills(self, include_archived: bool = False) -> dict[str, Any]:
        from ..skills.discovery import discover_skills

        found = discover_skills(self.workspace, include_archived=include_archived)
        if not found:
            return _ok("no skills found")
        lines = []
        for name in sorted(found):
            fm, _ = found[name]
            updated = fm.metadata.get("updated_at") if hasattr(fm, "metadata") else None
            lines.append(
                f"- {name}: {fm.description or ''}"
                f"  [state={fm.state}, pinned={fm.pinned}"
                + (f", updated={updated}" if updated else "")
                + "]"
            )
        return _ok(f"available skills ({len(lines)}):\n" + "\n".join(lines))

    def _read_skill(self, name: str) -> dict[str, Any]:
        if not name:
            return _error("name required")
        from ..skills.loader import load_body

        body = load_body(name, self.workspace)
        if body is None:
            return _error(f"skill not found: {name}")
        return _ok(body)

    # ---- memory ------------------------------------------------------

    def _list_memories(self, profile: str = "") -> dict[str, Any]:
        from ..memory.store import list_entries

        profile = profile or self.memory_profile
        entries = list_entries(profile)
        if not entries:
            return _ok(f"no memory entries for profile {profile!r}")
        lines = [f"- {e.name} ({e.type}): {e.description}" for e in entries]
        return _ok(f"memory entries for profile {profile!r} ({len(entries)}):\n" + "\n".join(lines))

    def _read_memory(self, name: str, profile: str = "") -> dict[str, Any]:
        if not name:
            return _error("name required")
        from ..memory.store import read_entry

        profile = profile or self.memory_profile
        entry = read_entry(profile, name)
        if entry is None:
            return _error(f"memory entry not found: {name} (profile={profile!r})")
        return _ok(entry.body)

    # ---- audit -------------------------------------------------------

    def _audit_query(
        self,
        since: str = "",
        until: str = "",
        tool_name: str = "",
        write_origin: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        if not self.audit_dir.exists():
            return _ok("no audit records")
        records = list(
            _iter_audit_records(
                self.audit_dir,
                since=since or None,
                until=until or None,
                tool_name=tool_name or None,
                write_origin=write_origin or None,
            )
        )
        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        records = records[: max(1, int(limit))]
        if not records:
            return _ok("no audit records match filters")
        lines = [
            f"{r.get('timestamp')} {r.get('write_origin', '?')} "
            f"{r.get('tool_name', '?')} {r.get('path', '')}"
            for r in records
        ]
        return _ok(f"audit records ({len(records)}):\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _error(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _iter_audit_records(
    audit_dir: Path,
    *,
    since: str | None,
    until: str | None,
    tool_name: str | None,
    write_origin: str | None,
) -> Iterable[dict[str, Any]]:
    """Walk every ``mutations-YYYY-MM.jsonl`` under ``audit_dir`` and
    yield records that pass the filters. Defensive against malformed
    JSON lines — bad lines are silently skipped, matching audit.py's
    write-only contract."""
    for log_path in sorted(audit_dir.glob("mutations-*.jsonl")):
        try:
            text = log_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            ts = record.get("timestamp", "")
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            if tool_name and record.get("tool_name") != tool_name:
                continue
            if write_origin and record.get("write_origin") != write_origin:
                continue
            yield record
