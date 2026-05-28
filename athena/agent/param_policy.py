"""Parseltongue — context-aware inference parameter policies.

The agent loop talks to a provider via ``stream_chat(..., temperature=X,
top_p=Y, ...)``. By default the kwargs are static — whatever was set
in ``~/.athena/config.toml`` or the provider's hardcoded defaults
(usually ``temperature=0.7``).

That static behaviour is wrong in two opposite directions at once:

- Coding work wants nearly deterministic output (``temperature=0.1,
  top_p=0.9``) so the model picks the right tool and arguments.
- Brainstorming or drafting wants the opposite (``temperature=0.8,
  top_p=0.95``) so the model actually explores.

A single global setting is a poor compromise. **Parseltongue** lets
the params adapt to the prompt and conversation state — what the user
just asked, how deep we are in a tool chain, whether a tool just
errored, whether code is in scope.

Three policies ship in this module:

- :class:`StaticPolicy` — current behaviour. Returns a fixed dict;
  default when the user opts out.
- :class:`HeuristicPolicy` — the parseltongue policy. A list of
  ``(predicate, params_delta)`` rules evaluated in order; later rules
  layer on top. Predicates are pure-Python over ``messages``,
  ``tools_available``, ``tool_calls_so_far``. Cheap, deterministic,
  no extra LLM call.
- :class:`LLMClassifierPolicy` — DEFERRED. Designed as an opt-in
  upgrade (one quick call to a small classifier model before the
  main generation, mapping to params), but the body is still a stub
  that falls through to a heuristic. ``policy_from_config`` rejects
  the ``llm_classifier`` selection rather than silently routing
  through the stub. Will be revived when the classifier model and
  prompt are settled.

The class returned by :func:`policy_from_config` is what the agent
asks for params before each provider call. The result is a kwarg dict
that goes straight into ``provider.stream_chat(**kwargs)``.

Design notes:

- **Bounded params.** :func:`_clamp` keeps the policy from producing
  values outside what providers accept (``temperature`` in [0, 2],
  ``top_p`` in [0, 1], etc.) even if a buggy rule emits nonsense.
- **Composable rules.** Each rule returns a *delta* dict that's merged
  over the running params; rules can specialize without rewriting
  prior decisions. A rule that only cares about ``temperature`` doesn't
  have to know what ``top_p`` is currently set to.
- **Inspection.** :meth:`HeuristicPolicy.explain` returns the list of
  rules that fired for a given input so ``/params`` can show the user
  why their last turn ran with ``temperature=0.15``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

# ---- Predicate input bundle --------------------------------------------


@dataclass(frozen=True)
class PolicyInput:
    """Inputs every predicate receives. Bundled into a frozen dataclass
    so adding new signals later doesn't break every predicate signature.

    ``messages`` is the full conversation as it will be sent to the
    provider (post-cache-marker insertion). ``tools_available`` is the
    list of registered tool names visible to the model this turn.
    ``tool_calls_so_far`` is how many tool calls have already happened
    in the current user turn — used by rules like "drop temperature
    when we're deep in a tool chain so the model doesn't get distracted."
    """

    messages: list[dict[str, Any]]
    tools_available: list[str] = field(default_factory=list)
    tool_calls_so_far: int = 0


# Predicate: returns True if the rule should fire for this input.
Predicate = Callable[[PolicyInput], bool]

# ParamDelta: a dict of provider kwargs to merge over the running params.
ParamDelta = dict[str, Any]


@dataclass(frozen=True)
class Rule:
    """One heuristic rule.

    ``name`` is for human-readable explanations; ``predicate`` decides
    whether the rule fires; ``params`` is the delta that merges over
    the running params when it does.
    """

    name: str
    predicate: Predicate
    params: ParamDelta

    def applies_to(self, inp: PolicyInput) -> bool:
        try:
            return bool(self.predicate(inp))
        except Exception:
            # A buggy user-supplied predicate must not break the agent.
            # Silent fail-closed (rule doesn't fire) keeps the runtime
            # safe; the user gets a hint via /params if they look.
            return False


# ---- The policies ------------------------------------------------------


class ParamPolicy(Protocol):
    """The interface the agent calls."""

    def params_for(self, inp: PolicyInput) -> ParamDelta: ...

    def explain(self, inp: PolicyInput) -> list[str]:
        """Human-readable list of what fired and why, for ``/params``."""
        ...


@dataclass
class StaticPolicy:
    """Returns the same params every turn. Equivalent to pre-parseltongue
    behaviour. Use this when you want to opt out of adaptive params
    without ripping the policy machinery out."""

    defaults: ParamDelta = field(default_factory=lambda: {"temperature": 0.7})

    def params_for(self, inp: PolicyInput) -> ParamDelta:
        return dict(self.defaults)

    def explain(self, inp: PolicyInput) -> list[str]:
        return [f"static policy: {self.defaults}"]


@dataclass
class HeuristicPolicy:
    """Walks an ordered rule list; merges each fired rule's delta over
    the running params. Built-in rules come from
    :func:`builtin_rules`; user rules from the ``[parseltongue]``
    config section layer on top.

    Rule ordering matters: later rules override earlier ones for the
    same key. The standard built-in ordering is:

    1. Baseline (always fires)
    2. Intent classifications (coding / explain / brainstorm / etc.)
    3. State modifiers (deep in tool chain, tool just errored, etc.)
    4. User-supplied rules
    """

    rules: list[Rule] = field(default_factory=list)

    def params_for(self, inp: PolicyInput) -> ParamDelta:
        out: ParamDelta = {}
        for rule in self.rules:
            if rule.applies_to(inp):
                _merge_params(out, rule.params)
        _clamp(out)
        return out

    def explain(self, inp: PolicyInput) -> list[str]:
        lines: list[str] = []
        running: ParamDelta = {}
        for rule in self.rules:
            if rule.applies_to(inp):
                _merge_params(running, rule.params)
                lines.append(f"  ✓ {rule.name:35s} {rule.params}")
            else:
                lines.append(f"    {rule.name:35s} (did not fire)")
        _clamp(running)
        lines.append(f"  → final: {running}")
        return lines


@dataclass
class LLMClassifierPolicy:
    """Stub for the opt-in classifier policy. Falls back to the
    fallback policy until wired (one quick call to a tiny model
    that returns a context label, mapping to params).

    Not exposed in the default config yet — landed as a placeholder
    so the policy registry has the right shape and we don't break
    the ``policy_from_config`` contract when it ships.
    """

    classifier_model: str
    fallback: ParamPolicy

    def params_for(self, inp: PolicyInput) -> ParamDelta:
        return self.fallback.params_for(inp)

    def explain(self, inp: PolicyInput) -> list[str]:
        return ["llm_classifier policy (stub) — falling back:"] + self.fallback.explain(inp)


# ---- Built-in rules ----------------------------------------------------


# Precompiled patterns. Kept at module scope so each turn doesn't pay
# the regex-compile tax; tweakable for tests via attribute substitution.
_CODE_INTENT_RE = re.compile(
    r"\b(refactor|rename (?:this |the |a )?(?:function|method|class|variable|file)|"
    r"implement (?:a |the |this )|"
    r"add (?:a |an )?(?:test|function|method|class)|"
    r"write (?:a |the )?(?:test|function|script)|"
    r"patch (?:this |the )|migrate|port (?:this |the )|extract (?:a |the |this )|"
    r"inline (?:this |the ))",
    re.IGNORECASE,
)
_EXPLAIN_INTENT_RE = re.compile(
    r"\b(explain|what (?:is|does|are)|how (?:does|do|can|should)|why (?:does|do|is|are)|"
    r"describe|tell me about|walk me through)\b",
    re.IGNORECASE,
)
_BRAINSTORM_INTENT_RE = re.compile(
    r"\b(brainstorm|ideas?|suggestions?|options?|alternatives?|approach(?:es)?|"
    r"draft (?:several|some|three|five)|come up with)\b",
    re.IGNORECASE,
)
_CREATIVE_INTENT_RE = re.compile(
    r"\b(creative|story|poem|fiction|imagine|invent|name (?:a |this |the ))\b",
    re.IGNORECASE,
)
_CODE_BLOCK_RE = re.compile(r"```[a-zA-Z+\-]*\n")


# Predicates --------------------------------------------------------------


def _last_user_text(inp: PolicyInput) -> str:
    """Most recent user message content as plain text. Trajectories
    pass through here so synthetic ``[/steer]`` markers count too —
    the steer text often signals intent."""
    for m in reversed(inp.messages):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # Vision messages: pull text parts.
            return "\n".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
    return ""


def _matches_code_intent(inp: PolicyInput) -> bool:
    return bool(_CODE_INTENT_RE.search(_last_user_text(inp)))


def _matches_explain_intent(inp: PolicyInput) -> bool:
    return bool(_EXPLAIN_INTENT_RE.search(_last_user_text(inp)))


def _matches_brainstorm_intent(inp: PolicyInput) -> bool:
    return bool(_BRAINSTORM_INTENT_RE.search(_last_user_text(inp)))


def _matches_creative_intent(inp: PolicyInput) -> bool:
    return bool(_CREATIVE_INTENT_RE.search(_last_user_text(inp)))


def _has_code_blocks_in_context(inp: PolicyInput) -> bool:
    """At least one fenced code block in the conversation so far. Strong
    signal that we're in coding territory regardless of the verbs."""
    for m in inp.messages[-10:]:  # only check recent window
        content = m.get("content")
        if isinstance(content, str) and _CODE_BLOCK_RE.search(content):
            return True
    return False


def _deep_in_tool_chain(inp: PolicyInput) -> bool:
    """Four-plus tool calls into the current turn. The model is doing
    multi-step work and should not be tempted to wander."""
    return inp.tool_calls_so_far >= 4


def _last_tool_was_error(inp: PolicyInput) -> bool:
    """The most recent tool message looks like an error. Bump top_k a
    touch so the model doesn't re-propose the same broken plan."""
    for m in reversed(inp.messages):
        if m.get("role") != "tool":
            continue
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        return any(s in content for s in ("Error:", "Traceback", "BLOCKED", "DENIED"))
    return False


def builtin_rules() -> list[Rule]:
    """The default parseltongue rule set. Order matters — later rules
    win on conflicting keys.

    Returns a fresh list each call so callers can mutate without
    affecting other policies.
    """
    return [
        # 1. Baseline. Always fires but emits NO params — the model's
        # Modelfile-tuned defaults (temperature, top_p, etc.) are
        # preserved unless an intent-matching rule below overrides
        # them. This is the "context-aware" spirit of parseltongue:
        # we adapt when we have a signal, not unconditionally.
        #
        # The previous baseline forced temperature=0.7 + repeat_penalty=1.1
        # on EVERY call, overriding Modelfile-tuned values (e.g. the
        # athena-tuned q35 model uses temperature=0.3, repeat_penalty=1.05).
        # That broke structured tool-call emission for any prompt that
        # didn't match an intent regex — the e2e tool-call test caught
        # the regression. Keeping the rule for "policy always returns
        # an answer" semantics but with an empty delta.
        Rule(
            name="baseline",
            predicate=lambda _: True,
            params={},
        ),
        # 2. Intent classifications (mutually somewhat-exclusive; the
        # last-wins behaviour means if a prompt matches multiple, the
        # later one wins — and "creative" beats "brainstorm" beats
        # "explain" beats "code" by ordering choice).
        Rule(
            name="intent:code",
            predicate=_matches_code_intent,
            params={"temperature": 0.3, "top_p": 0.9},
        ),
        Rule(
            name="intent:explain",
            predicate=_matches_explain_intent,
            params={"temperature": 0.4, "top_p": 0.95},
        ),
        Rule(
            name="intent:brainstorm",
            predicate=_matches_brainstorm_intent,
            params={"temperature": 0.85, "top_p": 0.95, "top_k": 60},
        ),
        Rule(
            name="intent:creative",
            predicate=_matches_creative_intent,
            params={"temperature": 0.95, "top_p": 0.98, "top_k": 80},
        ),
        # 3. Context-signal modifiers. Code in scope is a strong vote
        # for "coding work" even when the verbs don't say so.
        Rule(
            name="context:code_blocks_present",
            predicate=_has_code_blocks_in_context,
            params={"temperature": 0.35},
        ),
        # 4. State modifiers. These layer on top of intent — even a
        # creative request, four tool calls in, should narrow to
        # finish the work.
        Rule(
            name="state:deep_tool_chain",
            predicate=_deep_in_tool_chain,
            params={"temperature": 0.1, "repeat_penalty": 1.15},
        ),
        Rule(
            name="state:tool_just_errored",
            predicate=_last_tool_was_error,
            params={"top_k": 80, "temperature": 0.3},
        ),
    ]


def heuristic_policy(extra_rules: list[Rule] | None = None) -> HeuristicPolicy:
    """Convenience constructor: built-in rules + optional user rules."""
    rules = builtin_rules()
    if extra_rules:
        rules.extend(extra_rules)
    return HeuristicPolicy(rules=rules)


# ---- User-rule loading from config ------------------------------------


def user_rules_from_config(entries: list[dict[str, Any]]) -> list[Rule]:
    """Load user-supplied rules from the ``[[parseltongue.user_rules]]``
    TOML array.

    Each entry is a dict like::

        {"when": "user_message_matches", "pattern": "(?i)\\\\byolo\\\\b",
         "params": {"temperature": 0.95}}

    Supported ``when`` predicates:

    - ``user_message_matches`` — ``pattern`` is matched against the
      last user message (case-sensitive — use ``(?i)`` inline if you
      want case-insensitive).
    - ``always`` — fires every turn. Useful for setting global defaults
      that differ from the built-in baseline.
    - ``tool_calls_at_least`` — ``count`` integer. Fires when
      ``tool_calls_so_far`` is at or above the threshold.

    Unknown ``when`` values produce no-op rules (logged, not raised)
    so a typo in config doesn't crash the agent.
    """
    rules: list[Rule] = []
    for i, entry in enumerate(entries or []):
        name = entry.get("name") or f"user_rule_{i}"
        when = entry.get("when")
        params = entry.get("params") or {}
        if when == "user_message_matches":
            pattern_src = entry.get("pattern", "")
            try:
                pattern = re.compile(pattern_src)
            except re.error:
                # Bad regex → drop the rule rather than crash.
                continue
            rules.append(
                Rule(
                    name=f"user:{name}",
                    predicate=lambda inp, p=pattern: bool(p.search(_last_user_text(inp))),
                    params=dict(params),
                )
            )
        elif when == "always":
            rules.append(
                Rule(name=f"user:{name}", predicate=lambda _: True, params=dict(params))
            )
        elif when == "tool_calls_at_least":
            count = int(entry.get("count", 1))
            rules.append(
                Rule(
                    name=f"user:{name}",
                    predicate=lambda inp, c=count: inp.tool_calls_so_far >= c,
                    params=dict(params),
                )
            )
        # Unknown `when` → silently skip. Logged elsewhere if logging
        # is configured; here we prefer never-crash over loud.
    return rules


# ---- Factory from config ----------------------------------------------


def policy_from_config(config_section: dict[str, Any] | None) -> ParamPolicy:
    """Build the active policy from a config dict matching the shape
    of the ``[parseltongue]`` TOML section.

    ``None`` or an empty dict picks the heuristic policy with default
    rules — the same behaviour as ``policy = "heuristic"`` explicitly.
    To opt out, set ``policy = "static"``.
    """
    cfg = dict(config_section or {})
    name = cfg.get("policy", "heuristic")
    user_rules = user_rules_from_config(cfg.get("user_rules") or [])

    if name == "static":
        defaults = dict(cfg.get("defaults") or {"temperature": 0.7})
        return StaticPolicy(defaults=defaults)
    if name == "heuristic":
        return heuristic_policy(extra_rules=user_rules)
    if name == "llm_classifier":
        # LLMClassifierPolicy is a stub (params_for falls through to
        # the heuristic fallback). Silently routing through it gave
        # config-readers the false impression they had opted into an
        # LLM classifier when they hadn't. Until the real one ships,
        # refuse the selection so the operator gets an explicit error
        # rather than a phantom upgrade.
        raise ValueError(
            "policy='llm_classifier' is not yet implemented; "
            "use policy='heuristic' or policy='static' instead"
        )
    # Unknown policy → fall back to heuristic rather than refuse to
    # start. The agent should never fail to boot over a config typo.
    return heuristic_policy(extra_rules=user_rules)


# ---- Internals --------------------------------------------------------


# Bounds enforced by :func:`_clamp` after all rules fire. Values come
# from what providers (Ollama, Anthropic, OpenAI, etc.) actually
# accept; anything outside these is silently clipped.
_PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "temperature": (0.0, 2.0),
    "top_p": (0.0, 1.0),
    "top_k": (1, 200),
    "repeat_penalty": (0.5, 2.0),
    "mirostat": (0, 2),
    "mirostat_tau": (0.0, 10.0),
    "mirostat_eta": (0.0, 1.0),
}


def _merge_params(running: ParamDelta, delta: ParamDelta) -> None:
    """In-place merge. Later values override earlier ones key-by-key."""
    for k, v in delta.items():
        running[k] = v


def _clamp(params: ParamDelta) -> None:
    """In-place clip each known param to its valid bound. Unknown
    params pass through untouched so providers can accept their own
    bespoke options. Non-numeric values for known params are also
    left alone — a buggy rule that emitted a string shouldn't crash
    the agent; downstream type checking or the provider will surface
    the error more meaningfully."""
    for k, (lo, hi) in _PARAM_BOUNDS.items():
        if k not in params:
            continue
        v = params[k]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            # ``bool`` is a subclass of ``int`` but we don't want to
            # treat True/False as 1/0 in a temperature setting — much
            # more likely it was a config mistake. Leave it; the
            # provider can complain.
            continue
        if v < lo:
            params[k] = lo if isinstance(v, float) else int(lo)
        elif v > hi:
            params[k] = hi if isinstance(v, float) else int(hi)
