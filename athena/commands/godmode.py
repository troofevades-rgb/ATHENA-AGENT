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
            tier = tok[len("--tier="):]
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
        ui.warn(
            f"parseltongue.py not found at {script}. "
            "Install the godmode skill scripts."
        )
        return
    level = _TIER_TO_LEVEL.get(tier)
    if level is None:
        ui.error(
            f"Unknown tier: {tier!r}. Use light, standard, or heavy."
        )
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
        ui.error(
            f"parseltongue.py exited {result.returncode}: "
            f"{(result.stderr or '').strip()}"
        )
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
        ui.error(
            "no active jailbreak strategy to save. "
            "Apply one first: /godmode apply <strategy>"
        )
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_file = CONFIG_DIR / f"{name}.json"
    payload = {
        "name": name,
        "strategy": active["strategy"],
        "applied_at": active["applied_at"],
        "saved_at": _now_iso(),
    }
    config_file.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
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
    if strategy not in TEMPLATES:
        ui.error(
            f"saved strategy {strategy!r} no longer exists in TEMPLATES. "
            f"Available: {', '.join(TEMPLATES.keys())}"
        )
        return
    ui.info(f"Loaded config {name!r}: applying strategy {strategy!r}")
    _apply_strategy(agent, strategy)


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
def cmd_godmode(agent, arg: str = "") -> str:
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
            ui.error(
                "usage: /godmode parseltongue <query> "
                "[--tier light|standard|heavy]"
            )
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
    else:
        ui.error(f"Unknown /godmode subcommand: {cmd}")
        ui.info(
            "Try: /godmode list, /godmode apply [strategy], "
            "/godmode steer [strategy], /godmode clear, /godmode test, "
            "/godmode parseltongue, /godmode save, /godmode load"
        )

    return ""
