"""``Diagnose`` tool — model-callable LSP wrapper (T5-03R.2).

Thin tool over :func:`athena.lsp.client.diagnose`. The agent gets
a single text-mode summary; the same underlying function is what
the T5-04 verified-execution gate uses to decide whether a change
is safe to keep.

Output shape: errors first, then warnings, then info / hint.
Each diagnostic gets one line with ``path:line:col [severity]
code: message``. A clean run reports ``"ok"`` so the model can
distinguish "no issues" from "tool errored / no server" (both of
which return ``[]`` from the client but get different summary
text).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from ..config import load_config
from ..lsp.client import Diagnostic, Severity, diagnose
from .registry import tool

logger = logging.getLogger(__name__)


_MAX_LINES = 200
_TRUNCATED_MARKER = "[diagnose: truncated, +{} more]"


def _active_cfg_or_disk():
    """Live agent cfg when available; tests monkeypatch
    ``athena.tools.diagnose.load_config`` directly, so we route the
    disk fallback through the same module-level binding to preserve
    that seam."""
    from ._active_cfg import active_cfg as _active
    try:
        from ..agent.core import get_current_agent
    except ImportError:
        get_current_agent = lambda: None  # type: ignore[assignment]
    agent = get_current_agent()
    if agent is not None and getattr(agent, "cfg", None) is not None:
        return agent.cfg
    # Use the module-level ``load_config`` so existing tests that
    # monkeypatch it keep working.
    return load_config()


@tool(
    name="Diagnose",
    aliases=("diagnose",),
    toolset="code",
    description=(
        "Run a language server (pyright/pylsp by default for Python) "
        "over one or more files and return their diagnostics. Errors "
        "are listed first. A clean run reports 'ok'. When the language "
        "server isn't installed or lsp_enabled is false, the tool "
        "still succeeds and reports 'ok (no diagnostics — LSP not "
        "available)' rather than failing — so the agent can call "
        "Diagnose without knowing whether the host has a server."
    ),
    parameters={
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File paths to diagnose.",
            }
        },
        "required": ["paths"],
    },
)
def Diagnose(paths: list[str] | None = None, **_kwargs) -> str:
    paths = list(paths or [])
    if not paths:
        return "ERROR: paths required"
    diagnostics = _run(paths)
    return format_summary(paths, diagnostics)


# ---------------------------------------------------------------------------
# Public helpers (T5-04 verifier consumes the same shape)
# ---------------------------------------------------------------------------


def _run(paths: list[str]) -> list[Diagnostic]:
    """Load cfg from the live agent (or disk fallback) + call the
    client. Monkeypatchable via ``athena.tools.diagnose.load_config``
    for tests; the legacy disk lookup is preserved through that
    monkeypatch seam."""
    cfg = _active_cfg_or_disk()
    try:
        return diagnose(paths, cfg=cfg)
    except Exception as e:  # noqa: BLE001 — defensive; client is already
        # graceful but guard the tool-surface too.
        logger.debug("Diagnose: diagnose() raised: %s", e)
        return []


def format_summary(
    paths: list[str],
    diagnostics: Iterable[Diagnostic],
) -> str:
    """Render the diagnostic list as the tool's user-facing string.

    Public so the T5-04 verifier can reuse the same renderer when
    surfacing diagnostics in its revert message.
    """
    diagnostics = list(diagnostics)
    if not diagnostics:
        return _ok_line(paths)

    # Errors first, then warnings, then info, then hints. Within a
    # severity bucket, sort by (path, line, col) for stable output.
    severity_order = {
        Severity.ERROR: 0,
        Severity.WARNING: 1,
        Severity.INFORMATION: 2,
        Severity.HINT: 3,
    }
    diagnostics.sort(key=lambda d: (severity_order[d.severity], d.path, d.line, d.col))

    lines: list[str] = []
    error_count = sum(1 for d in diagnostics if d.is_error)
    warning_count = sum(1 for d in diagnostics if d.severity == Severity.WARNING)
    info_count = len(diagnostics) - error_count - warning_count

    header_bits: list[str] = []
    if error_count:
        header_bits.append(f"{error_count} error{'s' if error_count != 1 else ''}")
    if warning_count:
        header_bits.append(f"{warning_count} warning{'s' if warning_count != 1 else ''}")
    if info_count:
        header_bits.append(f"{info_count} info / hint")
    lines.append("diagnose: " + ", ".join(header_bits))

    body_lines: list[str] = []
    for d in diagnostics:
        sev = d.severity.name.lower()
        code = f"[{sev}] {d.code}" if d.code else f"[{sev}]"
        body_lines.append(f"  {d.path}:{d.line}:{d.col} {code}: {d.message}")
    if len(body_lines) > _MAX_LINES:
        extra = len(body_lines) - _MAX_LINES
        body_lines = body_lines[:_MAX_LINES]
        body_lines.append("  " + _TRUNCATED_MARKER.format(extra))
    lines.extend(body_lines)
    return "\n".join(lines)


def _ok_line(paths: list[str]) -> str:
    """The "no issues" case. Distinguishes "all clean" from "no
    server available" so the agent can tell whether the gate is
    actually firing."""
    cfg = _active_cfg_or_disk()
    if not getattr(cfg, "lsp_enabled", False):
        return "ok (no diagnostics — LSP disabled)"
    # When lsp_enabled but the server isn't on PATH we get [] too;
    # let the operator see that distinct case.
    from ..lsp.client import _language_for_path, _server_command

    languages = {_language_for_path(p) for p in paths}
    languages.discard(None)
    if not languages:
        return f"ok ({len(paths)} file(s); no language mapped)"
    unreachable = [lang for lang in languages if _server_command(lang, cfg) is None]
    if unreachable:
        joined = ", ".join(sorted(filter(None, unreachable)))
        return f"ok (no diagnostics — LSP server not installed for {joined})"
    return f"ok ({len(paths)} file(s) clean)"


# Convenient alias for the T5-04 verifier path: it imports the same
# name and expects the same signature.
diagnose_paths = _run
