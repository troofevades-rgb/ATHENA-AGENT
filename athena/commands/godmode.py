"""``/godmode`` -- G0DM0D3 jailbreaking toolkit for athena.

DANGER. This module ships templates whose entire purpose is to
weaken the model's safety posture for the active session. Anyone
who runs ``/godmode apply <strategy>`` is opting their session
into responses the model would otherwise refuse. There are
legitimate uses (red-teaming the user's own deployed model,
safety research) and illegitimate ones (helping the model produce
harmful output that downstream consumers would not have consented
to).

0.3.0 hardening (Tier 0 #3): the module is REGISTERED
unconditionally so it appears in ``/help`` and the slash-
registration drift test, but the runtime entry point
(``cmd_godmode``) refuses to do any work without
``ATHENA_ALLOW_GODMODE=1`` resolved by ``athena.env.get_credential``
(``~/.athena/.env`` first, then process environment). With the
gate open, every invocation emits a one-line warning so the
operator never forgets they're inside the opt-in.

How application works: strategies are injected via the existing
``/steer`` queue. ``apply`` pushes the strategy template onto
``GLOBAL_STEER_QUEUE`` for the session; the agent's normal
``_inject_pending_steers`` drains it before the next prompt and
the template appears in history as a ``[/steer] <template>``
synthetic user message. ``clear`` pushes a counter-steer telling
the model to drop the prior influence. The active strategy is
tracked on ``agent._active_godmode`` so ``list`` can render the
``(active)`` marker and ``save`` has something to persist.

Subcommands::

    /godmode list                  list strategies; marks the active one
    /godmode apply <strategy>      push strategy as a steer; mark active
    /godmode clear                 push counter-steer; drop active marker
    /godmode test <query>          preview every strategy's payload for <query>
    /godmode parseltongue <q>      obfuscate <q> via parseltongue.py
                                   (--tier light|standard|heavy)
    /godmode save <name>           write active strategy config to disk
    /godmode load <name>           read config + apply its strategy
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import ui
from ..env import get_credential
from . import command

# 0.3.0 hardening (Tier 0 #3): ``/godmode`` is REGISTERED unconditionally
# so it appears in /help and in the slash-registration drift test --
# nothing about it is hidden -- but the runtime entry point refuses to
# do any actual work without ``ATHENA_ALLOW_GODMODE=1`` in the
# environment. Operator types ``/godmode list`` without the env var
# and gets a clear "set ATHENA_ALLOW_GODMODE=1 to enable" message
# instead of jailbreak templates. With the env var set, the command
# operates normally and the operator sees a one-line warning on every
# invocation reminding them they're in the opt-in.
_GATE_ENV_VAR = "ATHENA_ALLOW_GODMODE"
_GATE_VALUE = "1"


def _gate_open() -> bool:
    # Routed through ``get_credential`` so the gate honors athena's
    # standard dotenv convention -- ``ATHENA_ALLOW_GODMODE=1`` in
    # ``~/.athena/.env`` opens the gate the same as a shell-exported
    # env var. Lookup order is dotenv first, then process env.
    return get_credential(_GATE_ENV_VAR) == _GATE_VALUE


def _refuse_gated() -> None:
    ui.error(
        f"/godmode is gated. Set {_GATE_ENV_VAR}={_GATE_VALUE} either in "
        f"~/.athena/.env or as a shell environment variable and restart "
        "athena to enable. The module ships templates that intentionally "
        "weaken the model's safety posture; opting in is a deliberate "
        "operator decision."
    )


# Skill path for godmode -- ``~/.athena/skills/godmode/`` is the
# canonical user-global install; ``_get_skill_path(agent)`` also
# checks ``<workspace>/.athena/skills/godmode/`` so the in-repo
# bundled skill works without a global install step.
SKILL_PATH = Path.home() / ".athena" / "skills" / "godmode"
CONFIG_DIR = Path.home() / ".athena" / "godmode" / "configs"


# Jailbreak templates -- single source of truth is
# :data:`athena.jailbreak.prompts.STRATEGIES`. This shim flattens
# the structured form ({name -> {target_model, template}}) into a
# bare {name -> template} dict for callers that just want the
# strategy text (``_test_strategies`` preview, the existing
# wire-up tests). Apply / steer code paths import directly from
# the canonical module.
def _load_templates() -> dict[str, str]:
    from ..jailbreak.prompts import STRATEGIES

    return {name: meta["template"] for name, meta in STRATEGIES.items()}


TEMPLATES = _load_templates()


def _get_skill_path(agent: Any) -> Path:
    """Resolve the godmode skill directory. Search order:

      1. ``~/.athena/skills/godmode/`` -- the user-global install.
      2. ``<agent.workspace>/.athena/skills/godmode/`` -- the
         in-repo bundled skill, so operators don't need a separate
         install step when the repo already ships the scripts.

    Returns the first path that contains a ``scripts/`` subdir
    (the actually-load-bearing artifact). Falls back to the global
    path so error messages point operators at where they *should*
    install if neither candidate is populated.
    """
    candidates: list[Path] = [SKILL_PATH]
    workspace = getattr(agent, "workspace", None)
    if isinstance(workspace, Path):
        candidates.append(workspace / ".athena" / "skills" / "godmode")
    for c in candidates:
        if (c / "scripts").is_dir():
            return c
    return SKILL_PATH


# Active-strategy attribute key. Stored on the live ``Agent`` so
# ``list`` can render the ``(active)`` marker and ``save`` has
# something concrete to persist. ``getattr(agent, _ACTIVE_ATTR, None)``
# is the canonical read; ``_set_active`` writes.
_ACTIVE_ATTR = "_active_godmode"


def _active_godmode(agent: Any) -> dict[str, Any] | None:
    return getattr(agent, _ACTIVE_ATTR, None)


def _set_active(agent: Any, value: dict[str, Any] | None) -> None:
    setattr(agent, _ACTIVE_ATTR, value)


def _session_id(agent: Any) -> str:
    """Resolve a session-id key for ``GLOBAL_STEER_QUEUE``. Live
    agents have ``self.session_id``; CLI-stub agents from tests
    don't. Fall back to a stable orphan key so the queue still
    accepts the push without raising on ``None``."""
    sid = getattr(agent, "session_id", None)
    return sid if isinstance(sid, str) and sid else "_godmode_orphan"


def _push_steer(agent: Any, message: str) -> None:
    """Push ``message`` into the per-session steer queue. The agent's
    next turn drains it via ``_inject_pending_steers`` and prepends
    it to history as a ``[/steer] <message>`` synthetic user message.
    """
    from ..steer.queue import GLOBAL_STEER_QUEUE

    GLOBAL_STEER_QUEUE.push(_session_id(agent), message)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_strategy(agent: Any, strategy: str) -> None:
    """Mutate the agent's system prompt to inject the jailbreak.

    This is the hermes-agent parity path: ``apply`` sets
    ``cfg.agent_system_prompt_append`` to the canonical
    ``GODMODE_SYSTEM_PROMPT + DEPTH_DIRECTIVE`` (default) or to a
    named L1B3RT4S strategy's template, then rebuilds
    ``self.messages[0]`` in place via ``agent.reload_system_prompt``
    so the model sees it on the next turn. The mutation is in-memory
    only -- ``config.toml`` is NOT touched, so a process restart
    drops the jailbreak unless the operator persists it via
    ``/godmode save`` + ``/godmode load`` (which re-applies on load).

    Strategy resolution:

      * The string ``"default"`` or no/empty strategy hits the
        canonical ``GODMODE_SYSTEM_PROMPT`` (the v∞.0 ULTIMATE
        JAILBREAK text from the G0DM0D3 reference).
      * Other names map to entries in
        :data:`athena.jailbreak.prompts.STRATEGIES` (the five named
        L1B3RT4S templates: boundary_inversion, refusal_inversion,
        og_godmode, unfiltered_liberated, zero_refusal). Each is
        paired with its historical target model in the registry.
      * ``DEPTH_DIRECTIVE`` is always appended after the strategy
        text (anti-hedge / anti-refusal enforcer, matches the
        G0DM0D3 chat/ultraplinian routes).

    Operators who want the auditable steer-queue variant (template
    appears in history as ``[/steer] <text>``) use
    ``/godmode steer <strategy>`` instead -- see ``_steer_strategy``.
    """
    from ..jailbreak.prompts import STRATEGIES, compose_system_prompt

    # Empty / "default" -> canonical GODMODE_SYSTEM_PROMPT.
    if not strategy or strategy.lower() == "default":
        resolved_strategy = "default"
        try:
            composed = compose_system_prompt(strategy=None, depth=True)
        except KeyError:  # pragma: no cover - default branch can't KeyError
            ui.error("internal: default strategy raised KeyError")
            return
    else:
        if strategy not in STRATEGIES:
            ui.error(f"Unknown strategy: {strategy}")
            available = ", ".join(["default", *STRATEGIES.keys()])
            ui.info(f"Available: {available}")
            return
        resolved_strategy = strategy
        composed = compose_system_prompt(strategy=strategy, depth=True)

    # Mutate config (in-memory) + rebuild messages[0] in place.
    agent.cfg.agent_system_prompt_append = composed
    reload = getattr(agent, "reload_system_prompt", None)
    if callable(reload):
        reload()

    _set_active(
        agent,
        {
            "strategy": resolved_strategy,
            "mode": "system_prompt",
            "applied_at": _now_iso(),
        },
    )
    ui.info(
        f"Applied jailbreak strategy: {resolved_strategy} "
        "(system-prompt mutation). Active immediately."
    )


def _steer_strategy(agent: Any, strategy: str) -> None:
    """Auditable variant: push the strategy template into the
    per-session steer queue rather than mutating the system prompt.

    The template appears in conversation history as a
    ``[/steer] <template>`` synthetic user message on the next turn.
    Less effective than ``_apply_strategy`` (the model can later
    "forget" a single user message but cannot forget the system
    prompt) but visible to anyone reviewing the trajectory --
    useful for accountability / red-team research where the
    jailbreak should leave an audit trail.

    Operators come here via ``/godmode steer <strategy>``; this is
    the variant athena exposes that hermes-agent does not.
    """
    from ..jailbreak.prompts import STRATEGIES, compose_system_prompt

    if not strategy or strategy.lower() == "default":
        resolved_strategy = "default"
        template = compose_system_prompt(strategy=None, depth=False)
    else:
        if strategy not in STRATEGIES:
            ui.error(f"Unknown strategy: {strategy}")
            available = ", ".join(["default", *STRATEGIES.keys()])
            ui.info(f"Available: {available}")
            return
        resolved_strategy = strategy
        template = compose_system_prompt(strategy=strategy, depth=False)

    _push_steer(agent, template)
    _set_active(
        agent,
        {
            "strategy": resolved_strategy,
            "mode": "steer",
            "applied_at": _now_iso(),
        },
    )
    ui.info(
        f"Queued jailbreak strategy as steer: {resolved_strategy}. "
        "Appears as [/steer] in history on next turn."
    )


def _list_strategies(agent: Any) -> None:
    """List strategy names + their target models; mark whichever is
    currently active. Includes the canonical ``default`` entry
    (GODMODE_SYSTEM_PROMPT v∞.0) on top so operators see it as a
    first-class option."""
    from ..jailbreak.prompts import STRATEGIES

    ui.console.print("[bold]Available jailbreak strategies:[/]")
    active = _active_godmode(agent)
    active_name = active["strategy"] if active else None
    mode = active.get("mode", "?") if active else None

    default_marker = ""
    if active_name == "default":
        default_marker = f" [yellow](active, mode={mode})[/]"
    ui.console.print(f"  * default              -- GODMODE v∞.0{default_marker}")

    for name, meta in STRATEGIES.items():
        marker = ""
        if name == active_name:
            marker = f" [yellow](active, mode={mode})[/]"
        target = meta.get("target_model", "")
        ui.console.print(f"  * {name:<20} -- {target}{marker}")


def _test_strategies(agent: Any, query: str) -> None:
    """Preview every strategy's payload for ``query``.

    Does NOT fire model calls -- doing so would mutate session
    history N times and surprise the operator. The preview lets
    you eyeball which strategy is the right shape for the query
    before picking one to ``apply``. Includes both the canonical
    ``default`` (GODMODE_SYSTEM_PROMPT v∞.0) and the named
    L1B3RT4S strategies from
    :data:`athena.jailbreak.prompts.STRATEGIES`.
    """
    from ..jailbreak.prompts import GODMODE_SYSTEM_PROMPT, STRATEGIES

    ui.console.print(f"[bold]Strategy previews for query:[/] {query}")

    def _preview_block(name: str, text: str) -> None:
        ui.console.print(f"\n[bold]{name}[/]")
        preview = text if len(text) <= 200 else text[:200] + "..."
        ui.console.print(preview)

    _preview_block("default", GODMODE_SYSTEM_PROMPT)
    for name, meta in STRATEGIES.items():
        _preview_block(name, meta["template"])


# Map ``--tier`` words to the script's numeric ``--level``.
_TIER_TO_LEVEL = {"light": "1", "standard": "2", "heavy": "3"}
# Wall-clock cap so a runaway parseltongue.py can't wedge the REPL.
_PARSELTONGUE_TIMEOUT_S = 30


def _parse_parseltongue_args(rest: str) -> tuple[str, str]:
    """Pull ``--tier X`` (or ``--tier=X``) out of ``rest`` and return
    ``(query, tier)``. The previous one-line ``rest.replace`` was
    fragile -- it only matched exact spacing and silently broke
    when ``--tier`` appeared at end-of-string with no value.

    Rules:

      * ``--tier <value>`` consumes two tokens; ``--tier=<value>``
        consumes one. Anything else is part of the query.
      * Multiple ``--tier`` flags: last wins (argparse semantics).
      * Bare trailing ``--tier`` (no value): dropped silently; tier
        stays at the default ``standard``. Caller's tier->level
        lookup will succeed.
      * Empty ``rest`` returns ``("", "standard")`` so the caller's
        ``if not query`` branch fires the usage error.
    """
    tier = "standard"
    out: list[str] = []
    if not rest:
        return "", tier
    tokens = rest.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--tier":
            if i + 1 < len(tokens):
                tier = tokens[i + 1]
                i += 2
                continue
            # Bare --tier at the end -- silently drop.
            i += 1
            continue
        if tok.startswith("--tier="):
            tier = tok[len("--tier=") :]
            i += 1
            continue
        out.append(tok)
        i += 1
    return " ".join(out), tier


def _parseltongue(agent: Any, query: str, tier: str = "standard") -> None:
    """Pipe ``query`` through ``parseltongue.py`` and print the
    encoded result. The script lives under the godmode skill at
    ``scripts/parseltongue.py`` and accepts
    ``--encode <text> --level <1|2|3>``.
    """
    skill_path = _get_skill_path(agent)
    script = skill_path / "scripts" / "parseltongue.py"
    if not script.exists():
        ui.warn(f"parseltongue.py not found at {script}. Install the godmode skill scripts.")
        return
    level = _TIER_TO_LEVEL.get(tier)
    if level is None:
        ui.error(f"Unknown tier: {tier!r}. Use light, standard, or heavy.")
        return
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--encode", query, "--level", level],
            capture_output=True,
            text=True,
            timeout=_PARSELTONGUE_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        ui.error(f"parseltongue.py timed out after {_PARSELTONGUE_TIMEOUT_S}s.")
        return
    except OSError as e:
        ui.error(f"failed to invoke parseltongue.py: {e}")
        return
    if result.returncode != 0:
        ui.error(f"parseltongue.py exited {result.returncode}: {(result.stderr or '').strip()}")
        return
    encoded = (result.stdout or "").strip()
    ui.info(f"Parseltongue {tier} tier (level {level}):")
    ui.console.print(encoded)


def _save_config(agent: Any, name: str) -> None:
    """Persist the currently-active strategy to a JSON config.
    Refuses if nothing is active -- saving an empty config would
    just confuse ``load`` later."""
    active = _active_godmode(agent)
    if active is None:
        ui.error("no active jailbreak strategy to save. Apply one first: /godmode apply <strategy>")
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_file = CONFIG_DIR / f"{name}.json"
    payload = {
        "name": name,
        "strategy": active["strategy"],
        "applied_at": active["applied_at"],
        "saved_at": _now_iso(),
    }
    from ..safety.secure_files import atomic_write_text

    atomic_write_text(config_file, json.dumps(payload, indent=2))
    ui.info(f"Config saved to: {config_file}")


def _load_config(agent: Any, name: str) -> None:
    """Read a saved config and apply its strategy. Strategy is
    re-resolved from the live ``TEMPLATES`` dict by name -- the
    template body is NOT stored in the config, so an edit to the
    template since save takes effect on load (deliberate)."""
    config_file = CONFIG_DIR / f"{name}.json"
    if not config_file.exists():
        ui.error(f"config not found: {config_file}")
        return
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        ui.error(f"could not parse {config_file}: {e}")
        return
    strategy = config.get("strategy")
    if not isinstance(strategy, str) or not strategy:
        ui.error(f"config {config_file} has no usable 'strategy' field.")
        return
    # "default" is a valid strategy that _apply_strategy resolves to the
    # canonical GODMODE_SYSTEM_PROMPT, but it's NOT a key in TEMPLATES
    # (which is built from the named STRATEGIES). Without this carve-out,
    # saving the default strategy then loading it errored ("no longer
    # exists") — the save→load round-trip was broken for the default.
    if strategy != "default" and strategy not in TEMPLATES:
        ui.error(
            f"saved strategy {strategy!r} no longer exists in TEMPLATES. "
            f"Available: {', '.join(['default', *TEMPLATES.keys()])}"
        )
        return
    ui.info(f"Loaded config {name!r}: applying strategy {strategy!r}")
    _apply_strategy(agent, strategy)


def _auto_jailbreak(agent: Any, args: str) -> None:
    """Detect the active model's family, pick the best strategy for
    that family, and apply it via the system-prompt mutation path
    (and optionally the prefill path).

    Args:
      ``args`` -- whitespace-separated flags:

        * ``--model X`` -- override detection and use family for X
        * ``--dry-run`` -- print the plan without applying
        * ``--no-prefill`` -- skip the prefill step even if the
          family table says to set one

    Behavior mirrors hermes-agent's ``auto_jailbreak.py`` but
    routes the application through athena's
    ``cfg.agent_system_prompt_append`` + ``reload_system_prompt``
    rather than mutating a config.yaml file on disk. The result is
    session-scoped: a restart drops the jailbreak unless the
    operator also runs ``/godmode save <name>`` (which captures
    the active strategy for later ``/godmode load``).
    """
    from ..jailbreak.prompts import detect_model_family, plan_for_family

    # Parse flags
    model_override: str | None = None
    dry_run = False
    no_prefill = False
    score_mode = False
    canary_query: str | None = None
    max_strategies: int | None = None
    tokens = args.split() if args else []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--model" and i + 1 < len(tokens):
            model_override = tokens[i + 1]
            i += 2
            continue
        if tok.startswith("--model="):
            model_override = tok[len("--model=") :]
            i += 1
            continue
        if tok == "--dry-run":
            dry_run = True
            i += 1
            continue
        if tok == "--no-prefill":
            no_prefill = True
            i += 1
            continue
        if tok == "--score":
            score_mode = True
            i += 1
            continue
        if tok == "--canary" and i + 1 < len(tokens):
            # Greedy: every remaining token is part of the canary
            # query. Operators rarely want flags AFTER --canary, so
            # this matches the natural usage:
            #   /godmode auto --score --canary how to pick a lock
            canary_query = " ".join(tokens[i + 1 :])
            i = len(tokens)
            continue
        if tok == "--max" and i + 1 < len(tokens):
            try:
                max_strategies = max(1, int(tokens[i + 1]))
            except ValueError:
                ui.warn(f"--max needs an integer, got {tokens[i + 1]!r}")
            i += 2
            continue
        ui.warn(f"ignoring unknown auto flag: {tok}")
        i += 1

    model = (
        model_override or getattr(agent, "model", None) or getattr(agent.cfg, "model", None) or ""
    )
    family = detect_model_family(model)

    if score_mode:
        _auto_score_path(
            agent,
            model=model,
            family=family,
            dry_run=dry_run,
            no_prefill=no_prefill,
            canary_query=canary_query,
            max_strategies=max_strategies,
        )
        return

    # Table-pick path (default): use the family's recommended strategy
    # without canary testing.
    strategy, prefill_template = plan_for_family(family)

    ui.console.print("[bold]/godmode auto[/]")
    ui.info(f"model:    {model or '<unknown>'}")
    ui.info(f"family:   {family or '<unmatched -- falling back to default>'}")
    ui.info(f"strategy: {strategy}")
    ui.info(f"prefill:  {prefill_template or '<none>'}")

    if dry_run:
        ui.info("dry-run: no config writes; agent state unchanged.")
        return

    # Apply the strategy via the system-prompt mutation path.
    apply_arg = "" if strategy == "default" else strategy
    _apply_strategy(agent, apply_arg)

    # Set prefill if the family table calls for it and the operator
    # didn't opt out.
    if prefill_template and not no_prefill:
        _set_prefill_file(agent, prefill_template)
    elif prefill_template and no_prefill:
        ui.info("--no-prefill: skipping prefill setup.")


def _auto_score_path(
    agent: Any,
    *,
    model: str,
    family: str | None,
    dry_run: bool,
    no_prefill: bool,
    canary_query: str | None,
    max_strategies: int | None,
) -> None:
    """The ``--score`` variant: canary-test every candidate strategy
    against the live model and apply the empirical winner. Slower
    than the table-pick path (N model calls instead of zero) but
    avoids picking a strategy the model patched against.

    Strategy candidates come from the family's preference order
    plus ``default`` plus any STRATEGIES not in the family list --
    so an unmatched model still gets full coverage. The default
    canary query is the gray-area lock-picking question from the
    hermes test suite; ``--canary`` overrides.
    """
    from ..jailbreak.autoscore import (
        DEFAULT_CANARY_QUERY,
        pick_best_strategy,
        score_strategies_against_model,
    )
    from ..jailbreak.prompts import plan_for_family

    provider = getattr(agent, "provider", None)
    if provider is None:
        ui.error(
            "no live provider on agent; --score can't canary-test. "
            "Drop --score for the table-pick path."
        )
        return

    effective_query = canary_query or DEFAULT_CANARY_QUERY

    ui.console.print("[bold]/godmode auto --score[/]")
    ui.info(f"model:  {model or '<unknown>'}")
    ui.info(f"family: {family or '<unmatched -- testing every strategy>'}")
    ui.info(f"canary: {effective_query!r}")
    ui.info("running canary tests (1 model call per strategy)...")

    try:
        scored = score_strategies_against_model(
            provider,
            model,
            family,
            canary_query=effective_query,
            max_strategies=max_strategies,
        )
    except Exception as e:  # noqa: BLE001
        ui.error(f"canary run failed: {e}")
        return

    ui.console.print("\n[bold]Strategy scores:[/]")
    for r in scored:
        marker = "[green]✓[/]" if r.success else "[red]✗[/]"
        ui.console.print(f"  {marker} {r.strategy:<22} score={r.score:>3}  {r.duration_ms:>6}ms")

    winner = pick_best_strategy(scored)
    if winner is None:
        ui.error(
            "every strategy failed -- nothing applied. Check the provider connection and model id."
        )
        return

    ui.console.print(f"\n[bold]Winner:[/] {winner.strategy} (score={winner.score})")

    if dry_run:
        ui.info("--dry-run: no config writes; agent state unchanged.")
        return

    apply_arg = "" if winner.strategy == "default" else winner.strategy
    _apply_strategy(agent, apply_arg)

    # Honor the family's prefill recommendation for the winning
    # strategy, unless --no-prefill is set. (The scored winner
    # might not match the family's primary; use the family's
    # prefill template if available, since prefill is family-tuned
    # not strategy-tuned.)
    _, prefill_template = plan_for_family(family)
    if prefill_template and not no_prefill:
        _set_prefill_file(agent, prefill_template)
    elif prefill_template and no_prefill:
        ui.info("--no-prefill: skipping prefill setup.")


_VALID_RACE_TIERS = (
    "fast",
    "standard",
    "smart",
    "power",
    "ultra",
    "ollama-local",
)


def _resolve_race_provider_and_models(agent: Any, tier: str) -> tuple[Any, list[str]] | None:
    """Pick the right provider + model list for ``tier``.

    Two paths:

      * Standard OpenRouter tiers (fast / standard / smart / power /
        ultra) -> ``OpenRouterProvider`` + the cumulative model list
        from :func:`get_models_for_tier`.
      * ``ollama-local`` -> ``OllamaProvider`` + every model returned
        by its ``/api/tags`` endpoint. Zero API spend; speed limited
        by what's installed. Athena-exclusive feature -- hermes can't
        do this because hermes routes everything through OpenRouter.

    Returns ``(provider, models)`` on success, ``None`` on a soft
    error (missing API key, no local models, etc.) -- callers
    short-circuit and the operator already saw a ``ui.error``.
    """
    from ..jailbreak import get_models_for_tier

    if tier == "ollama-local":
        # Local race -- prefer an existing OllamaProvider hung off the
        # agent (the live session's own provider), else construct a
        # fresh one. The default host comes from cfg.ollama_host or
        # the OLLAMA_HOST env var which OllamaProvider already handles.
        provider = getattr(agent, "provider", None)
        is_ollama = provider is not None and getattr(provider, "name", "") == "ollama"
        if not is_ollama:
            from ..providers.ollama import OllamaProvider

            provider = OllamaProvider()
        # ``provider`` is non-None here: either it was the agent's live
        # ollama provider (``is_ollama`` implies non-None) or freshly
        # constructed just above. Assert to narrow the ``Any | None``.
        assert provider is not None
        try:
            models = provider.list_models()
        except Exception as e:  # noqa: BLE001
            ui.error(f"could not list local Ollama models: {e}. Is the Ollama daemon running?")
            return None
        if not models:
            ui.error("no local Ollama models found. Pull one first: `ollama pull qwen2.5`.")
            return None
        return provider, models

    # OpenRouter tiers. Key resolution order matches the rest of
    # athena's provider plumbing:
    #
    #   1. ``agent.openrouter_provider`` -- already constructed
    #      somewhere upstream (a live session that already routes
    #      through OpenRouter).
    #   2. The credential pool entry for ``"openrouter"``. This is
    #      the canonical place keys live (``athena providers
    #      add-key openrouter --key ...``). Reading from here means
    #      rotation on 429 + multi-key fan-out work the same as
    #      every other provider.
    #   3. ``OPENROUTER_API_KEY`` resolved via the dotenv loader
    #      (``~/.athena/.env`` first, then process env). Fallback
    #      for operators who haven't migrated to the pool.
    #
    # Anyone with no key in any of these three sources gets a
    # clear error pointing at the ``add-key`` command.
    provider = getattr(agent, "openrouter_provider", None)
    if provider is None:
        from ..providers.credential_pool import global_pool

        api_key: str | None = None
        try:
            cred = global_pool().get("openrouter")
            if cred and cred.key:
                api_key = cred.key
        except Exception:  # noqa: BLE001
            # Pool corruption shouldn't break the race outright --
            # fall through to the dotenv path.
            pass
        if not api_key:
            api_key = get_credential("OPENROUTER_API_KEY")
        if not api_key:
            ui.error(
                "no OpenRouter credential found. Add one with:\n"
                "  athena providers add-key openrouter --key sk-or-...\n"
                "or set OPENROUTER_API_KEY in ~/.athena/.env."
            )
            return None
        from ..providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider(api_key=api_key)
    return provider, get_models_for_tier(tier)


def _parse_race_args(rest: str) -> tuple[str, str, bool, bool]:
    """Pull ``--tier``, ``--no-godmode``, ``--no-depth`` out of
    ``rest`` and return ``(query, tier, godmode_on, depth_on)``.

    Defaults: ``tier="fast"``, ``godmode_on=True``, ``depth_on=True``
    -- the reference's defaults so an operator who types
    ``/godmode race "what is the meaning of life"`` gets a fast,
    jailbroken race straight away.

    Empty / missing query returns ``query=""`` so the caller fires
    the usage error.
    """
    tier = "fast"
    godmode_on = True
    depth_on = True
    out: list[str] = []
    if not rest:
        return "", tier, godmode_on, depth_on
    tokens = rest.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--tier" and i + 1 < len(tokens):
            tier = tokens[i + 1].lower()
            i += 2
            continue
        if tok.startswith("--tier="):
            tier = tok[len("--tier=") :].lower()
            i += 1
            continue
        if tok == "--no-godmode":
            godmode_on = False
            i += 1
            continue
        if tok == "--no-depth":
            depth_on = False
            i += 1
            continue
        out.append(tok)
        i += 1
    return " ".join(out), tier, godmode_on, depth_on


def _run_race(agent: Any, args: str) -> None:
    """ULTRAPLINIAN multi-model racing via OpenRouter.

    Fires ``N`` parallel queries against the resolved tier of
    OpenRouter models, scores each response (length / structure /
    anti-refusal / directness / relevance, 0-100), and renders the
    top results.

    Args:
      ``args`` -- ``<query> [--tier fast|standard|smart|power|ultra]``
                  ``[--no-godmode] [--no-depth]``

    When ``--no-godmode`` is absent (default), the GODMODE_SYSTEM_PROMPT
    is sent as the system message. When ``--no-depth`` is also absent,
    DEPTH_DIRECTIVE is appended. These switches let an operator A/B a
    racing strategy against the baseline.

    Provider resolution: prefers a per-session
    :class:`OpenRouterProvider` instance the agent has already built;
    falls back to creating a fresh one from ``OPENROUTER_API_KEY``
    in the credential surface (``~/.athena/.env`` first, then env).
    """
    from ..jailbreak import (
        DEPTH_DIRECTIVE,
        GODMODE_SYSTEM_PROMPT,
        RaceConfig,
        race_models,
    )

    query, tier, godmode_on, depth_on = _parse_race_args(args)
    if not query:
        ui.error(
            "usage: /godmode race <query> "
            "[--tier fast|standard|smart|power|ultra|ollama-local] "
            "[--no-godmode] [--no-depth]"
        )
        return
    if tier not in _VALID_RACE_TIERS:
        ui.error(f"unknown tier: {tier!r}. Use one of: {', '.join(_VALID_RACE_TIERS)}.")
        return

    resolved = _resolve_race_provider_and_models(agent, tier)
    if resolved is None:
        return
    provider, models = resolved

    # Build the messages payload. System message follows the reference
    # composition: GODMODE_SYSTEM_PROMPT (+ DEPTH_DIRECTIVE) when both
    # flags are on; bare query if --no-godmode.
    system_prompt = ""
    if godmode_on:
        system_prompt = GODMODE_SYSTEM_PROMPT
        if depth_on:
            system_prompt = system_prompt + DEPTH_DIRECTIVE
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": query})

    ui.info(
        f"racing {len(models)} models in tier '{tier}'. "
        f"godmode={'on' if godmode_on else 'off'} "
        f"depth={'on' if depth_on else 'off'}"
    )

    # Live progress callback: print each result as it comes in.
    def _on_result(result: Any) -> None:
        status = "✓" if result.success else "✗"
        ui.info(f"  {status} {result.model:<48} score={result.score:>3} {result.duration_ms:>6}ms")

    results = race_models(
        provider,
        models,
        messages,
        query,
        config=RaceConfig(on_result=_on_result),
    )

    # Render top 5 + winner detail.
    top = results[:5]
    if not top:
        ui.warn("no results -- every model failed or timed out.")
        return
    ui.console.print("\n[bold]Top 5 by score:[/]")
    for i, r in enumerate(top, 1):
        status_marker = "[green]✓[/]" if r.success else "[red]✗[/]"
        ui.console.print(
            f"  {i}. {status_marker} {r.model:<48} score={r.score:>3}  {r.duration_ms:>6}ms"
        )
    winner = top[0]
    if winner.success and winner.content:
        ui.console.print(f"\n[bold]Winner ({winner.model}):[/]")
        preview = winner.content
        if len(preview) > 1200:
            preview = preview[:1200] + "\n[dim]... [truncated][/]"
        ui.console.print(preview)


def _race_stub(agent: Any, args: str) -> None:
    """Kept for backwards compatibility. ``/godmode race`` now
    dispatches to :func:`_run_race`; this stub is here for any
    future opt-out path."""
    _run_race(agent, args)


def _set_prefill_file(agent: Any, name_or_path: str) -> None:
    """Point ``cfg.agent_prefill_messages_file`` at a prefill JSON
    and trigger a reload so the next API call picks it up.

    Resolution:

      * ``set aggressive`` -> the bundled
        ``templates/prefill.json`` under the godmode skill
        (matches the hermes ``prefill.json`` aggressive template).
      * ``set subtle`` -> the bundled
        ``templates/prefill-subtle.json`` (security-researcher
        persona, lower detection risk).
      * Anything else is treated as a path: absolute, ``~/...``,
        or relative-to-``~/.athena/`` -- same resolution as the
        agent's loader.
    """
    arg = name_or_path.strip()
    if arg in ("aggressive", "subtle"):
        skill_path = _get_skill_path(agent)
        templates_dir = skill_path / "templates"
        filename = "prefill.json" if arg == "aggressive" else "prefill-subtle.json"
        target = templates_dir / filename
        if not target.exists():
            ui.error(
                f"prefill template {arg!r} not found at {target}. "
                "Install the godmode skill scripts."
            )
            return
        agent.cfg.agent_prefill_messages_file = str(target)
    else:
        agent.cfg.agent_prefill_messages_file = arg

    reload = getattr(agent, "reload_prefill_messages", None)
    if callable(reload):
        reload()
    ui.info(
        f"prefill messages file set to: {agent.cfg.agent_prefill_messages_file}. "
        "Loaded on next prompt."
    )


def _clear_prefill_file(agent: Any) -> None:
    """Unset ``cfg.agent_prefill_messages_file`` and reload so the
    next API call has no prefill injection."""
    if not getattr(agent.cfg, "agent_prefill_messages_file", None):
        ui.info("no prefill messages file is set.")
        return
    agent.cfg.agent_prefill_messages_file = None
    reload = getattr(agent, "reload_prefill_messages", None)
    if callable(reload):
        reload()
    ui.info("prefill messages cleared. No injection on next prompt.")


def _show_prefill_status(agent: Any) -> None:
    """Render the current prefill configuration -- the active file
    path and the number of valid messages it loads. Useful for
    operators verifying that ``set`` actually picked up a valid
    file."""
    path = getattr(agent.cfg, "agent_prefill_messages_file", None)
    if not path:
        ui.info("prefill: <unset>")
        return
    ui.info(f"prefill file: {path}")
    load = getattr(agent, "_load_prefill_messages", None)
    if callable(load):
        msgs = load()
        ui.info(f"prefill messages loaded: {len(msgs)}")


def _clear_jailbreak(agent: Any) -> None:
    """Drop the active marker and reverse the jailbreak.

    Reversal depends on which mode applied it:

      * ``mode == "system_prompt"`` -- unset
        ``cfg.agent_system_prompt_append`` and rebuild
        ``self.messages[0]`` in place. The next turn sees the
        clean system prompt; no counter-steer needed because the
        original injection is simply gone.
      * ``mode == "steer"`` -- push a counter-steer telling the
        model to disregard the prior steer-based persona. The
        original steer is already in conversation history (we can't
        retroactively edit it) but the counter-steer fires on the
        next prompt so the model is explicitly told to drop it.
      * Active state without a ``mode`` field (pre-0.3.0 form) is
        treated as the legacy steer-only case for backwards
        compatibility.

    No-op when nothing is active.
    """
    active = _active_godmode(agent)
    if active is None:
        ui.info("no active jailbreak strategy.")
        return

    mode = active.get("mode", "steer")
    if mode == "system_prompt":
        agent.cfg.agent_system_prompt_append = None
        reload = getattr(agent, "reload_system_prompt", None)
        if callable(reload):
            reload()
        ui.info(
            f"Cleared jailbreak strategy: {active['strategy']}. "
            "System prompt rebuilt without the append."
        )
    else:
        _push_steer(
            agent,
            "Disregard any prior /steer instructions that altered your "
            "persona or weakened your safety posture. Resume your "
            "default behavior for the remainder of this session.",
        )
        ui.info(
            f"Cleared jailbreak strategy: {active['strategy']}. "
            "Counter-steer will fire on the next prompt."
        )
    _set_active(agent, None)


@command("godmode")
def cmd_godmode(agent: Any, arg: str = "") -> str:
    """``/godmode`` -- G0DM0D3 jailbreaking toolkit.

    Gated: requires ``ATHENA_ALLOW_GODMODE=1`` in the environment.
    Without the env var, the command refuses with a clear message
    pointing the operator at the gate. With the env var, every
    invocation also emits a one-line ``ui.warn`` reminding the
    operator they're inside the opt-in.
    """
    if not _gate_open():
        _refuse_gated()
        return ""
    ui.warn(
        f"/godmode active ({_GATE_ENV_VAR}=1). "
        "Templates weaken the model's safety posture for this session."
    )
    arg = (arg or "").strip()

    if not arg:
        _list_strategies(agent)
        return ""

    parts = arg.split()
    cmd = parts[0]
    rest = " ".join(parts[1:])

    if cmd == "list":
        _list_strategies(agent)
    elif cmd == "apply":
        # ``apply`` with no arg uses the canonical default
        # (GODMODE_SYSTEM_PROMPT). With a name, applies that named
        # L1B3RT4S strategy. Both go through the system-prompt
        # mutation path -- the hermes-parity default.
        _apply_strategy(agent, rest)
    elif cmd == "steer":
        # Auditable variant -- pushes the strategy as a
        # ``[/steer] <text>`` synthetic user message. Visible in
        # conversation history; less effective than ``apply`` but
        # leaves an audit trail.
        _steer_strategy(agent, rest)
    elif cmd == "test":
        if not rest:
            ui.error("usage: /godmode test <query>")
            return ""
        _test_strategies(agent, rest)
    elif cmd == "parseltongue":
        query, tier = _parse_parseltongue_args(rest)
        if not query:
            ui.error("usage: /godmode parseltongue <query> [--tier light|standard|heavy]")
            return ""
        _parseltongue(agent, query, tier)
    elif cmd == "save":
        if not rest:
            ui.error("usage: /godmode save <name>")
            return ""
        _save_config(agent, rest)
    elif cmd == "load":
        if not rest:
            ui.error("usage: /godmode load <name>")
            return ""
        _load_config(agent, rest)
    elif cmd == "clear":
        _clear_jailbreak(agent)
    elif cmd == "auto":
        _auto_jailbreak(agent, rest)
    elif cmd == "race":
        _race_stub(agent, rest)
    elif cmd == "prefill":
        # ``/godmode prefill`` (no arg) -- show current status
        # ``/godmode prefill set <name|path>`` -- point at a file
        # ``/godmode prefill clear`` -- unset
        if not rest or rest == "status":
            _show_prefill_status(agent)
        else:
            prefill_parts = rest.split(maxsplit=1)
            sub = prefill_parts[0]
            if sub == "set":
                if len(prefill_parts) < 2:
                    ui.error("usage: /godmode prefill set <aggressive|subtle|PATH>")
                    return ""
                _set_prefill_file(agent, prefill_parts[1])
            elif sub == "clear":
                _clear_prefill_file(agent)
            elif sub == "status":
                _show_prefill_status(agent)
            else:
                ui.error(f"unknown prefill subcommand: {sub}. Use: set <name|path>, clear, status.")
    else:
        ui.error(f"Unknown /godmode subcommand: {cmd}")
        ui.info(
            "Try: /godmode list, /godmode apply [strategy], "
            "/godmode steer [strategy], /godmode clear, /godmode test, "
            "/godmode parseltongue, /godmode save, /godmode load"
        )

    return ""
