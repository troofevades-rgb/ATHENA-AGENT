"""MCP resources surface for athena (T3-02.3).

Resources are passive read targets — the consuming client can
reference them by URI without calling a tool. Athena exposes three
roots:

- ``athena://skills/`` — skill catalogue index (markdown)
- ``athena://skills/<name>`` — full body of one skill
- ``athena://memories/`` — memory index for the active profile
- ``athena://memories/<name>`` — one memory entry's body
- ``athena://audit/<YYYY-MM>`` — audit log for a given month

The ``resources/list`` response advertises the three root URIs;
``resources/read`` dispatches based on the URI scheme + path. Bad
URIs return an error in the standard MCP shape.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


RESOURCE_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "uri": "athena://skills/",
        "name": "Athena skills index",
        "description": "List of all available skills with descriptions.",
        "mimeType": "text/markdown",
    },
    {
        "uri": "athena://memories/",
        "name": "Athena memory index",
        "description": "Memory entries for the active profile.",
        "mimeType": "text/markdown",
    },
    {
        "uri": "athena://audit/",
        "name": "Athena audit log",
        "description": (
            "Monthly mutation audit logs. Read athena://audit/<YYYY-MM> for "
            "one month's records as JSONL."
        ),
        "mimeType": "application/x-ndjson",
    },
]


@dataclass
class AthenaMCPResources:
    """Dispatch ``resources/read``.

    Construction parameters mirror :class:`AthenaMCPTools` — same
    workspace, memory profile, and audit_dir.
    """

    workspace: Path
    memory_profile: str
    audit_dir: Path

    def read_resource(self, uri: str) -> dict[str, Any]:
        """Return an MCP-format ``resources/read`` result."""
        if not uri:
            return _error(uri, "uri required")
        if uri.startswith("athena://skills/"):
            return self._read_skill_resource(uri)
        if uri.startswith("athena://memories/"):
            return self._read_memory_resource(uri)
        if uri.startswith("athena://audit/"):
            return self._read_audit_resource(uri)
        return _error(uri, f"unknown resource URI scheme: {uri}")

    # ---- skills ------------------------------------------------------

    def _read_skill_resource(self, uri: str) -> dict[str, Any]:
        from ..skills.discovery import discover_skills
        from ..skills.loader import load_body

        rest = uri.removeprefix("athena://skills/")
        if not rest:
            found = discover_skills(self.workspace)
            if not found:
                return _resource(uri, "# Athena skills\n\n(no skills)\n", "text/markdown")
            lines = ["# Athena skills\n"]
            for name in sorted(found):
                fm, _ = found[name]
                lines.append(f"- **{name}** — {fm.description or ''}")
            return _resource(uri, "\n".join(lines) + "\n", "text/markdown")
        body = load_body(rest, self.workspace)
        if body is None:
            return _error(uri, f"skill not found: {rest}")
        return _resource(uri, body, "text/markdown")

    # ---- memories ----------------------------------------------------

    def _read_memory_resource(self, uri: str) -> dict[str, Any]:
        from ..memory.store import list_entries, read_entry

        rest = uri.removeprefix("athena://memories/")
        if not rest:
            entries = list_entries(self.memory_profile)
            if not entries:
                return _resource(
                    uri,
                    f"# Memories ({self.memory_profile})\n\n(no entries)\n",
                    "text/markdown",
                )
            lines = [f"# Memories ({self.memory_profile})\n"]
            for entry in entries:
                lines.append(f"- **{entry.name}** ({entry.type}): {entry.description}")
            return _resource(uri, "\n".join(lines) + "\n", "text/markdown")
        matched = read_entry(self.memory_profile, rest)
        if matched is None:
            return _error(uri, f"memory entry not found: {rest}")
        return _resource(uri, matched.body, "text/markdown")

    # ---- audit -------------------------------------------------------

    def _read_audit_resource(self, uri: str) -> dict[str, Any]:
        rest = uri.removeprefix("athena://audit/")
        if not rest:
            # Index: list available months.
            if not self.audit_dir.exists():
                return _resource(uri, "(no audit logs)\n", "text/plain")
            months = sorted(
                p.stem.removeprefix("mutations-") for p in self.audit_dir.glob("mutations-*.jsonl")
            )
            if not months:
                return _resource(uri, "(no audit logs)\n", "text/plain")
            body = "Available audit months:\n" + "\n".join(f"- {m}" for m in months)
            return _resource(uri, body + "\n", "text/plain")
        # Specific month.
        log_path = self.audit_dir / f"mutations-{rest}.jsonl"
        if not log_path.exists():
            return _error(uri, f"audit log for {rest} not found")
        try:
            content = log_path.read_text(encoding="utf-8")
        except OSError as e:
            return _error(uri, f"could not read audit log: {e}")
        # Reframe to NDJSON-with-newline-at-end for MCP clients that
        # split on \n.
        if not content.endswith("\n"):
            content += "\n"
        return _resource(uri, content, "application/x-ndjson")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resource(uri: str, text: str, mime_type: str) -> dict[str, Any]:
    return {
        "contents": [
            {"uri": uri, "mimeType": mime_type, "text": text},
        ]
    }


def _error(uri: str, message: str) -> dict[str, Any]:
    # MCP resources/read doesn't have a spec'd error shape on the
    # result side; we return an empty contents list with a sentinel
    # body so the client surfaces the message rather than getting a
    # null result. The server core surfaces JSON-RPC errors for
    # protocol-level issues.
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": "text/plain",
                "text": f"ERROR: {message}",
            }
        ]
    }
