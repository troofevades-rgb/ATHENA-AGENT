"""Jailbreak prompt source-of-truth.

Mirrors the architecture from the G0DM0D3 reference (Pliny the
Prompter): ``godmode-prompt.ts`` exports ``GODMODE_SYSTEM_PROMPT``
as the single canonical string, and ``ultraplinian.ts`` exports the
``DEPTH_DIRECTIVE`` anti-hedge / anti-refusal suffix appended to it
on every API call.

The athena equivalents live at :mod:`athena.jailbreak.prompts`. Both
the ``/godmode`` slash command (when wiring the system-prompt
mutation path) and any future ``/godmode race`` / ``/godmode auto``
subcommand import from there so the canonical text stays in one
place and edits propagate everywhere.

The legacy named TEMPLATES from the early skill-script port live
here too as alternate strategies (``boundary_inversion``,
``refusal_inversion``, ``og_godmode``, ``unfiltered_liberated``,
``zero_refusal``) -- ``GODMODE_SYSTEM_PROMPT`` is the default when
no strategy is named.
"""

from .prompts import (
    DEPTH_DIRECTIVE,
    GODMODE_SYSTEM_PROMPT,
    STRATEGIES,
    compose_system_prompt,
    detect_model_family,
    plan_for_family,
)
from .race import (
    ULTRAPLINIAN_MODELS,
    RaceConfig,
    RaceResult,
    get_models_for_tier,
    race_models,
    score_response,
)

__all__ = [
    "DEPTH_DIRECTIVE",
    "GODMODE_SYSTEM_PROMPT",
    "STRATEGIES",
    "ULTRAPLINIAN_MODELS",
    "RaceConfig",
    "RaceResult",
    "compose_system_prompt",
    "detect_model_family",
    "get_models_for_tier",
    "plan_for_family",
    "race_models",
    "score_response",
]
