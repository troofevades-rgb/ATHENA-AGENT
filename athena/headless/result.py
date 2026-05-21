"""Structured outcome of a headless run (T7-01.1).

The envelope every ``run_headless()`` call returns + the exit-
code mapping the CLI dispatcher uses to translate status to
POSIX exit code.

Exit codes follow standard UNIX conventions so common shell
plumbing works without translation:

  0    success — ``status="ok"``
  1    generic error — ``status="error"`` (agent crashed,
       model unreachable, etc.)
  2    invalid input — ``status="invalid"`` (missing required
       arg, bad workspace, malformed task file)
  124  timeout — ``status="timeout"`` (matches ``timeout(1)``)
  130  interrupted — ``status="interrupted"`` (matches
       ``128 + SIGINT(2)``)

The CLI dispatcher in ``athena/__main__.py`` calls
``result.exit_code()`` to get the right number; callers
parsing ``--json`` output get the structured status string.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Literal


Status = Literal["ok", "error", "timeout", "interrupted", "invalid"]


# Status → exit code. Stable across modes (with/without --json).
_EXIT_CODES: dict[str, int] = {
    "ok": 0,
    "error": 1,
    "invalid": 2,
    "timeout": 124,
    "interrupted": 130,
}


# Cap on the size of the assistant_text field in the JSON
# envelope. Full transcripts can be enormous; the envelope is
# for callers that want a quick result summary. The full text
# always lives in the session JSONL on disk under the run_id.
_ASSISTANT_TEXT_LIMIT = 8000


@dataclasses.dataclass
class RunResult:
    """One headless run's outcome.

    Every field is JSON-safe so ``to_json()`` round-trips
    cleanly. Optional fields are None or empty when they don't
    apply (no error → ``error=None``; no model output yet →
    ``assistant_text=""``).

    The envelope shape is the contract a batch_runner / cron
    job / eval harness reads. Don't drop fields; future
    additions go via new optional fields.
    """

    run_id: str
    status: Status
    started_at: str        # ISO-8601 UTC with 'Z' suffix
    finished_at: str
    duration_s: float
    task: str
    workspace: str
    model: str
    profile: str
    session_id: str | None = None
    tool_calls: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    # tokens: {"prompt", "completion", "cache_read", "cache_creation"}
    tokens: dict[str, int] = dataclasses.field(default_factory=dict)
    cost_est: float = 0.0
    assistant_text: str = ""
    error: str | None = None

    def exit_code(self) -> int:
        """POSIX exit code for the dispatcher. Stable mapping
        from ``status`` so shells / scripts / CI runners can
        branch reliably."""
        return _EXIT_CODES.get(self.status, 1)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict. ``assistant_text`` is capped at
        ``_ASSISTANT_TEXT_LIMIT`` chars (with a truncation
        marker) so the envelope stays a reasonable size; the
        full text lives in the session JSONL."""
        text = self.assistant_text or ""
        if len(text) > _ASSISTANT_TEXT_LIMIT:
            text = (
                text[:_ASSISTANT_TEXT_LIMIT]
                + f"\n…[truncated; full text in session {self.session_id!r}]"
            )
        return {
            "run_id": self.run_id,
            "status": self.status,
            "exit_code": self.exit_code(),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(float(self.duration_s), 3),
            "task": self.task,
            "workspace": self.workspace,
            "model": self.model,
            "profile": self.profile,
            "session_id": self.session_id,
            "tool_calls": list(self.tool_calls),
            "tokens": dict(self.tokens),
            "cost_est": round(float(self.cost_est), 6),
            "assistant_text": text,
            "error": self.error,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        """Serialise to a JSON string. ``indent=None`` (default)
        produces a single-line envelope — what the ``--json``
        mode of the CLI emits + what batch runners expect to
        parse. ``indent=2`` is for human inspection."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def mint_run_id() -> str:
    """Stable ID format for headless runs: ``r-<uuid12>``.
    Same shape as the task store's ``t-<uuid12>`` convention
    so an operator can tell them apart at a glance."""
    import uuid
    return f"r-{uuid.uuid4().hex[:12]}"
