"""Bundled plugin: per-session shell audit log.

For every tool call to ``Bash`` / ``bash`` / ``shell`` / ``execute``, append
a JSONL row to ``~/.ocode/logs/shell_audit/<session_id>.jsonl`` with the
tool name, args, and a truncated result.

Useful for after-the-fact audits of what the agent ran. Disabled by default;
enable with ``ocode plugins enable shell_audit``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ocode.plugins.base import Plugin


_SHELL_TOOLS = {"Bash", "bash", "shell", "execute"}
_RESULT_TRUNC = 500


class ShellAuditPlugin(Plugin):
    """Append every shell tool call to ``~/.ocode/logs/shell_audit/<session>.jsonl``."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._log_path: Path | None = None
        self._log_root: Path = (
            Path(self.config.get("log_root"))
            if self.config.get("log_root")
            else Path.home() / ".ocode" / "logs" / "shell_audit"
        )

    def on_session_start(self, session_id: str, profile: str) -> None:
        self._log_path = self._log_root / f"{session_id}.jsonl"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def post_tool_call(
        self, tool_name: str, tool_args: dict[str, Any], result: str
    ) -> None:
        if tool_name not in _SHELL_TOOLS:
            return
        if self._log_path is None:
            return  # session_start never fired; nothing to audit
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool_name,
            "args": tool_args,
            "result_truncated": result[:_RESULT_TRUNC],
        }
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
