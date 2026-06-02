"""Word-boundary allowlist + explicit denylist for the Bash tool.

athena v1's allowlist used Python's ``in`` operator against a list
of strings, which collapses two distinct categories of bug:

- Prefix shadowing: an allowlist containing ``git`` matches
  ``gitlab-cli`` and ``gitleaks``.
- Path-component leak: an allowlist containing ``rm`` matches
  ``rm -rf /home/user/.git/objects`` *and* ``mv x.rm dest``.

This module replaces that with two cooperating layers:

1. A denylist of regex patterns that always fires regardless of
   the allowlist. The default covers the high-damage verbs and
   pipeline shapes (``rm -rf /``, ``curl | sh``, ``mkfs.*``, ...).
2. A word-boundary allowlist: each entry compiles to
   ``^<escaped-entry>\\b`` and must match the *binary token*
   (the first non-environment-assignment token) of the command.

The denylist is the security floor — call
:meth:`ShellPolicy.evaluate_denylist_only` to enforce just that
without locking the user into an allowlist. The full strict mode
(``evaluate``) is what Phase 17's CI / safety tests rely on.
"""

from __future__ import annotations

import dataclasses
import re
import shlex
from collections.abc import Iterable


@dataclasses.dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    matched_rule: str | None = None


# Each pattern is a regex applied to the raw command string before
# tokenisation. Patterns are ordered roughly by severity. Patterns
# are case-INsensitive at compile time below so Windows / cmd-style
# verbs (``DEL``, ``Format``) match the same as their lowercase
# equivalents -- operators copy-pasting from shell history shouldn't
# evade the floor by accidental capitalization.
DEFAULT_DENYLIST: tuple[str, ...] = (
    # ---- POSIX / Linux ----
    r"\brm\s+-rf\s+/(?!home/|tmp/|var/tmp/)",  # rm -rf of system roots
    r"\bsudo\s+rm\s+-rf",  # any sudo rm -rf
    r"\bmkfs\.",  # filesystem creation (any fs flavour)
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",  # fork bomb
    r"\bchmod\s+.*\b777\b\s+/",  # chmod 777 on system paths
    # ---- block-device destruction (covers macOS + Linux) ----
    # macOS uses /dev/disk* and /dev/rdisk*; FreeBSD adds /dev/ada*.
    # Without these, ``dd if=/dev/zero of=/dev/disk0`` evaded the
    # floor on Apple Silicon and Intel Macs alike.
    r"\bdd\s+.*\bof=/dev/(sd|nvme|hd|disk|rdisk|ada|vd)",
    r">\s*/dev/(sda|nvme|hda|disk|rdisk)",  # redirect to block device
    # ---- pipe-to-shell pattern ----
    r"\bcurl\b.*\|\s*(sudo\s+)?(sh|bash|zsh)",
    r"\bwget\b.*\|\s*(sudo\s+)?(sh|bash|zsh)",
    # ---- Windows / cmd / PowerShell ----
    # ATHENA.md treats Windows as first-class so the denylist must
    # cover Windows-native destruction verbs. ``del /s /q`` is the
    # Windows analogue of ``rm -rf``; ``format`` and ``cipher /w``
    # are direct disk-wipe vectors that no agent should ever issue.
    # ``rd /s /q`` (alias ``rmdir``) on a system root is equivalent
    # to del. Patterns are written so a lone ``del foo.txt`` is
    # untouched -- only the recursive/quiet+root combinations fire.
    r"\b(del|erase)\s+(/[sq]\s+)+",  # del /s /q or /q /s (any order)
    r"\b(rd|rmdir)\s+/s\b",  # recursive rmdir
    r"\bformat\b\s+[a-z]:",  # format C: / format D:
    r"\bcipher\s+/w:",  # cipher /w: secure-wipes free space
    r"\bdiskpart\b",  # interactive disk partition tool
    # PowerShell remove-item with -recurse + -force on system paths
    r"\bremove-item\b.*\-recurse\b.*\-force\b",
)


class ShellPolicy:
    """Evaluate shell commands against a denylist + allowlist."""

    def __init__(
        self,
        allowlist: Iterable[str] = (),
        denylist: Iterable[str] = DEFAULT_DENYLIST,
    ) -> None:
        allowlist = tuple(allowlist)
        self._allow_raw: tuple[str, ...] = allowlist
        self._allow_patterns: tuple[re.Pattern[str], ...] = tuple(
            re.compile(rf"^{re.escape(entry)}\b") for entry in allowlist
        )
        # Case-INsensitive on the denylist so Windows-style
        # capitalization (``DEL /S /Q``, ``Format C:``) doesn't
        # evade the floor. POSIX patterns are unaffected -- shell
        # binaries are conventionally lowercase, so a ``RM -RF /``
        # is non-functional but still indicative of intent and
        # worth blocking. Allowlist patterns stay case-sensitive
        # (the operator's allowlist is explicit configuration; we
        # don't second-guess the case they typed).
        self._deny_patterns: tuple[re.Pattern[str], ...] = tuple(
            re.compile(p, re.IGNORECASE) for p in denylist
        )

    # ---- public API ------------------------------------------------

    def evaluate_denylist_only(self, command: str) -> PolicyDecision:
        """Apply only the denylist + parseability checks.

        Used as the always-on safety floor: even when the agent has
        no explicit allowlist configured we still block ``rm -rf /``
        and friends. Allowlist enforcement is a separate opt-in.
        """
        cmd = command.strip()
        if not cmd:
            return PolicyDecision(False, "empty command", None)
        deny = self._scan_denylist(cmd)
        if deny is not None:
            return deny
        # Also verify shlex-parseable so unbalanced quotes don't slip
        # through to the shell; the agent has zero hope of debugging
        # the resulting subprocess error.
        try:
            shlex.split(cmd, posix=True)
        except ValueError as e:
            return PolicyDecision(False, f"unparseable: {e}", None)
        return PolicyDecision(True, "denylist clean", None)

    def evaluate(self, command: str) -> PolicyDecision:
        """Strict evaluation: deny on denylist match, deny when the
        command's binary is not in the allowlist."""
        cmd = command.strip()
        if not cmd:
            return PolicyDecision(False, "empty command", None)

        deny = self._scan_denylist(cmd)
        if deny is not None:
            return deny

        try:
            tokens = shlex.split(cmd, posix=True)
        except ValueError as e:
            return PolicyDecision(False, f"unparseable: {e}", None)
        if not tokens:
            return PolicyDecision(False, "no tokens after shlex", None)

        idx = 0
        while (
            idx < len(tokens)
            and "=" in tokens[idx]
            and not tokens[idx].startswith("-")
            and not tokens[idx].startswith("=")
            and tokens[idx].split("=", 1)[0].isidentifier()
        ):
            idx += 1
        if idx >= len(tokens):
            return PolicyDecision(False, "no command after env assignments", None)

        binary = tokens[idx]
        for pat, raw in zip(self._allow_patterns, self._allow_raw):
            if pat.match(binary):
                return PolicyDecision(True, f"allowlist match: {raw}", raw)
        return PolicyDecision(
            False,
            f"binary {binary!r} not in allowlist",
            None,
        )

    # ---- internals -------------------------------------------------

    def _scan_denylist(self, cmd: str) -> PolicyDecision | None:
        for p in self._deny_patterns:
            if p.search(cmd):
                return PolicyDecision(
                    False,
                    f"denylist match: {p.pattern}",
                    p.pattern,
                )
        return None
