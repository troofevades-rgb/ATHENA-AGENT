"""Helpers around curator dry-run mode.

The real enforcement is split between the prompt (which instructs the
curator fork to refrain from destructive skill_manage actions) and the
write_origin gate in ``skill_manage`` (which refuses curator-origin
mutations when policy says so). These helpers only need to surface the
flag in a uniform way for the CLI to inject and for tests to inspect.
"""
from __future__ import annotations

from ..provenance import set_current_write_origin, reset_current_write_origin, CURATOR


def is_dry_run_addendum(addendum: str) -> bool:
    """Return True iff ``addendum`` was prefixed with the DRY_RUN banner.

    The CURATOR_REVIEW_PROMPT itself mentions the DRY_RUN=true marker (in
    its "Dry-run mode" section), so we check for the banner specifically
    at the top of the addendum — that's the signal the orchestrator
    wired the flag through.
    """
    from . import prompts
    return addendum.lstrip().startswith(prompts.DRY_RUN_BANNER.strip())
