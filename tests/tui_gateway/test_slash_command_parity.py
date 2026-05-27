"""Drift guard: the TUI's slash-command catalog covers every command
documented in ``athena/commands/help_cmd.py``.

The TUI lives in TypeScript and has its own static catalog
(``ui-tui/src/components/SlashPopup.tsx``) so the user can get
inline completion / discovery in the composer. That catalog must
stay in sync with the canonical Python help text — otherwise a
newly-added command would be invisible in the popup forever.

We parse SLASH_HELP and the TS source with text matching (no JS
runtime needed in the test) and assert every name in SLASH_HELP
is present in the TS catalog. The reverse — extra entries in the
TS catalog — is not enforced; sometimes the TUI catalog is ahead
of the help text during a refactor."""

from __future__ import annotations

import re
from pathlib import Path

from athena.commands.help_cmd import SLASH_HELP


REPO_ROOT = Path(__file__).resolve().parents[2]
SLASH_POPUP_TS = REPO_ROOT / "ui-tui" / "src" / "components" / "SlashPopup.tsx"


def _python_command_names() -> set[str]:
    """Extract every ``/name`` token at the start of a line of
    SLASH_HELP. Ignores wrapped continuation lines."""
    names: set[str] = set()
    for line in SLASH_HELP.splitlines():
        m = re.match(r"^/([\w-]+)", line)
        if m:
            names.add("/" + m.group(1))
    return names


def _typescript_command_names() -> set[str]:
    """Extract every ``name: "/..."`` literal from SlashPopup.tsx."""
    text = SLASH_POPUP_TS.read_text(encoding="utf-8")
    return set(re.findall(r'name:\s*"(/[\w-]+)"', text))


def test_typescript_catalog_covers_every_python_command() -> None:
    """Every slash command documented in athena/commands/help_cmd.py
    must appear in the TUI's static catalog so users get completion
    for it. Missing entries surface as 'I typed /foo and nothing
    suggested it'."""
    python = _python_command_names()
    typescript = _typescript_command_names()
    missing = python - typescript
    assert not missing, (
        f"slash commands documented in SLASH_HELP but missing from "
        f"ui-tui/src/components/SlashPopup.tsx — add them so users "
        f"get completion: {sorted(missing)}"
    )


def test_typescript_catalog_does_not_have_phantom_commands() -> None:
    """Commands in the TS catalog that AREN'T in SLASH_HELP suggest
    a rename or removal happened on the Python side without
    updating the TUI. Warn so completion doesn't suggest a
    command the agent doesn't actually handle."""
    python = _python_command_names()
    typescript = _typescript_command_names()
    phantom = typescript - python
    # Allow a small empty-set assertion — anything in TS not in
    # SLASH_HELP is suspect.
    assert not phantom, (
        f"commands in the TUI catalog but NOT documented in "
        f"SLASH_HELP — likely a rename or removal: {sorted(phantom)}"
    )
