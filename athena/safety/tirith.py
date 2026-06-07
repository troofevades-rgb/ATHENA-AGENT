"""Pre-Bash security scanner via external tirith binary (T-MIG).

Ported from NousResearch/hermes-agent (MIT) — tirith inspects
shell commands for **content-level** threats that the approval
gate can't catch by inspecting argv alone:

  - homograph URLs (Cyrillic 'а' / Latin 'a' in a domain)
  - pipe-to-interpreter (`curl evil | sh`)
  - terminal injection via ANSI escapes
  - hidden Unicode bidi controls

These look fine to a human approver but are actively malicious.
Tirith catches them; athena's existing approval gate doesn't.
Defense in depth.

Architecture mirrors athena's other capability-with-external-
binary patterns (ffmpeg for video, tesseract for OCR): wrap
the subprocess, return a structured verdict, fail open
gracefully when the binary isn't available so a missing tool
isn't a hard error.

The tirith binary itself is Linux + macOS only (per the
upstream releases). On Windows, ``is_available()`` returns
False and the wrapper returns the fail-open verdict
(``action="allow"``, ``summary="tirith unavailable on this
platform"``) so the rest of athena's flow keeps working.

Public surface:

  check_command_security(command) -> Verdict
  is_available()                 -> bool
  Verdict (NamedTuple)           shape returned to callers
"""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)


_SUPPORTED_SYSTEMS = frozenset({"linux", "darwin"})


class Verdict(NamedTuple):
    """Result of a tirith check on a shell command.

    ``action`` is the headline — callers (the Bash precheck
    hook in particular) branch on it:

      "allow"  command looks safe; proceed
      "warn"   suspicious patterns; operator/model should
               eyeball it before approving
      "block"  active attack patterns found; refuse

    ``findings`` is the JSON list tirith emitted (each entry
    has its own ``severity`` + ``message``); the Bash gate
    quotes the first few in a warning so the operator sees
    what tirith caught.

    ``summary`` is a one-line human-readable explanation —
    safe to include in logs / error messages.

    ``available`` distinguishes "tirith ran and decided"
    from "tirith couldn't run, falling open" — for the model
    consuming the verdict.
    """

    action: str
    findings: list[dict[str, Any]]
    summary: str
    available: bool


def is_available(cfg: Any = None) -> bool:
    """True iff tirith can actually run on this host. Two
    requirements: the platform is supported (Linux or macOS)
    AND a binary is on PATH (or pointed at via
    ``cfg.tirith_binary_path``)."""
    if platform.system().lower() not in _SUPPORTED_SYSTEMS:
        return False
    return _resolve_binary(cfg) is not None


def check_command_security(
    command: str,
    *,
    cfg: Any = None,
    timeout_s: float | None = None,
    shell: str | None = None,
) -> Verdict:
    """Run tirith on ``command``. Returns a structured Verdict.

    Never raises into the caller — the Bash precheck path
    needs a guaranteed verdict to branch on. Failure modes
    (missing binary, timeout, non-JSON output) all map to
    either the fail-open ``"allow"`` verdict or ``"warn"``
    depending on the config.

    ``cfg.tirith_fail_open=True`` (default): unavailable /
    timed-out tirith → action="allow" + available=False so
    the operator sees it but the command isn't blocked by a
    missing tool.
    """
    cfg = cfg if cfg is not None else _load_cfg()

    if not getattr(cfg, "tirith_enabled", True):
        return Verdict(
            action="allow",
            findings=[],
            summary="tirith disabled by config",
            available=False,
        )

    if not is_available(cfg):
        fail_open = bool(getattr(cfg, "tirith_fail_open", True))
        return Verdict(
            action="allow" if fail_open else "block",
            findings=[],
            summary=(
                "tirith not installed on this host "
                f"(platform={platform.system()}); " + ("fail-open" if fail_open else "fail-closed")
            ),
            available=False,
        )

    binary = _resolve_binary(cfg)
    if binary is None:  # mypy-style narrow; checked above too
        return Verdict(
            action="allow",
            findings=[],
            summary="tirith binary not found",
            available=False,
        )

    to_s = timeout_s if timeout_s is not None else float(getattr(cfg, "tirith_timeout_s", 5.0))
    sh = shell or getattr(cfg, "tirith_shell", "posix")

    try:
        proc = subprocess.run(
            [
                str(binary),
                "check",
                "--json",
                "--non-interactive",
                "--shell",
                str(sh),
                "--",
                str(command),
            ],
            capture_output=True,
            text=True,
            timeout=to_s,
        )
    except subprocess.TimeoutExpired:
        fail_open = bool(getattr(cfg, "tirith_fail_open", True))
        logger.warning(
            "tirith timed out after %.1fs on command (len=%d); %s",
            to_s,
            len(command),
            "allowing" if fail_open else "blocking",
        )
        return Verdict(
            action="allow" if fail_open else "block",
            findings=[],
            summary=f"tirith timed out after {to_s:.1f}s",
            available=True,
        )
    except (OSError, FileNotFoundError) as e:
        logger.warning("tirith spawn failed: %s", e)
        return Verdict(
            action="allow",
            findings=[],
            summary=f"tirith spawn failed: {e}",
            available=False,
        )

    return _verdict_from_proc(proc, cfg=cfg)


# ---------------------------------------------------------------
# internals
# ---------------------------------------------------------------


def _resolve_binary(cfg: Any) -> Path | None:
    """Find the tirith binary: configured path → PATH lookup."""
    if cfg is not None:
        explicit = getattr(cfg, "tirith_binary_path", None)
        if explicit:
            p = Path(str(explicit)).expanduser()
            return p if p.exists() else None
    loc = shutil.which("tirith")
    return Path(loc) if loc else None


def _verdict_from_proc(
    proc: subprocess.CompletedProcess[str],
    *,
    cfg: Any,
) -> Verdict:
    """Map a finished tirith run into a Verdict.

    Per the upstream contract:
      exit 0 → allow
      exit 1 → block
      exit 2 → warn
      anything else → respect ``tirith_fail_open``

    Tirith's stdout (when --json) carries the structured
    findings + a summary; we parse it for the details but
    NEVER let JSON parsing override the exit-code-derived
    action (defense against a malformed payload from a
    compromised binary)."""
    code = proc.returncode
    if code == 0:
        action = "allow"
    elif code == 1:
        action = "block"
    elif code == 2:
        action = "warn"
    else:
        fail_open = bool(getattr(cfg, "tirith_fail_open", True))
        action = "allow" if fail_open else "block"

    findings: list[dict[str, Any]] = []
    summary = f"tirith exit {code}"
    if proc.stdout:
        try:
            data = json.loads(proc.stdout)
            if isinstance(data, dict):
                f = data.get("findings")
                if isinstance(f, list):
                    findings = [x for x in f if isinstance(x, dict)]
                s = data.get("summary")
                if isinstance(s, str) and s.strip():
                    summary = s.strip()
        except json.JSONDecodeError:
            # Stick with the exit-code derived action; details
            # just say "couldn't parse JSON".
            summary = f"tirith exit {code} (non-JSON output)"

    return Verdict(
        action=action,
        findings=findings,
        summary=summary,
        available=True,
    )


def _load_cfg() -> Config:
    """Module-level cfg load for the no-arg public-API form.
    Tests override by passing cfg= directly."""
    from ..config import load_config

    return load_config()
