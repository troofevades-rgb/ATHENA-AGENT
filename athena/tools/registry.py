"""Tool registry. Tools register themselves via @tool() and expose:
   - a name
   - a JSON schema description (Ollama function-call format)
   - a Python callable that takes kwargs from the model and returns a string

Tools are scoped into named toolsets. The agent (and forks) advertise tools to
the model by filtering the registry to a subset of toolsets via the
``enabled_toolsets`` keyword. A tool may also declare a ``check_fn`` whose
return value gates whether the tool is advertised at all on a given call.
"""

import difflib
import inspect
import json
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., str]
    toolset: str = "core"
    requires_confirmation: bool = False
    check_fn: Callable[[], bool] | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    # Phase 18.2: opt-in marker for parallel tool dispatch.
    # ``True`` means the tool is safe to execute concurrently with
    # other parallel-safe tools in the same tool-call round -- i.e. it
    # is read-only with respect to athena's shared state (workspace
    # files, messages, plan mode, goal state, session JSONL, etc.) and
    # has no ordering dependency on a sibling call in the same batch.
    # Conservative default: ``False``. A ``requires_confirmation=True``
    # tool is always serial regardless of this flag (the prompt
    # serializes naturally). Stage 1 of the parallel-tool-execution
    # work adds the field + flags the obvious read-only surface; the
    # actual batched dispatch lands in stage 3.
    parallel_safe: bool = False
    # Opt-in marker for surfacing this tool's RESULT into a gateway chat
    # (Discord/Telegram/etc.). The gateway normally relays only the
    # model's final text + media files; a tool whose output is itself
    # the thing the user asked to see (``skills_list``, a status dump)
    # sets ``gateway_relay=True`` so its result is delivered to the chat
    # (truncated/chunked). Default ``False`` — most tool output is
    # internal scaffolding the model summarizes, not chat-facing.
    gateway_relay: bool = False


_REGISTRY: dict[str, Tool] = {}
_TOOLSETS: dict[str, set[str]] = {}
_ALIASES: dict[str, str] = {}

# Bumped on every mutation that changes which tools the toolset filter
# would select (registry add/remove). Used to cache the post-filter Tool
# list so ollama_schema() doesn't walk the whole registry every turn.
# check_fn results are NOT memoized — they are re-evaluated on every
# ollama_schema() call for tools that declare one.
_SCHEMA_VERSION: int = 0
_FILTER_CACHE: dict[tuple[int, tuple[str, ...] | None, tuple[str, ...]], list["Tool"]] = {}


def bump_schema_version() -> None:
    """Invalidate the registry-filter cache. Call from any mutation that
    changes which tools the toolset filter would return."""
    global _SCHEMA_VERSION
    _SCHEMA_VERSION += 1
    _FILTER_CACHE.clear()


def tool(
    *,
    name: str,
    description: str,
    parameters: dict[str, Any],
    toolset: str = "core",
    requires_confirmation: bool = False,
    check_fn: Callable[[], bool] | None = None,
    aliases: list[str] | None = None,
    parallel_safe: bool = False,
    gateway_relay: bool = False,
) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """Register a function as a tool.

    ``toolset`` groups the tool with peers; callers select active toolsets via
    ``enabled_toolsets``. ``check_fn`` is re-evaluated every time the schema
    is rendered so connection-state-dependent tools reflect current availability.
    ``aliases`` registers additional dispatch names -- aliases are NOT included
    in the schema sent to the model.

    ``parallel_safe`` (Phase 18.2) opts the tool into concurrent dispatch
    with other parallel-safe siblings in the same tool-call round.
    Defaults to ``False`` (serial). See :class:`Tool` for the contract.

    ``gateway_relay`` opts the tool's result into delivery to a gateway
    chat (the result is what the user wanted to see, e.g. ``skills_list``).
    Defaults to ``False``. See :class:`Tool` for the contract.
    """

    def deco(fn: Callable[..., str]) -> Callable[..., str]:
        t = Tool(
            name=name,
            description=description,
            parameters=parameters,
            func=fn,
            toolset=toolset,
            requires_confirmation=requires_confirmation,
            check_fn=check_fn,
            aliases=tuple(aliases or ()),
            parallel_safe=parallel_safe,
            gateway_relay=gateway_relay,
        )
        _REGISTRY[name] = t
        _TOOLSETS.setdefault(toolset, set()).add(name)
        for alias in t.aliases:
            _ALIASES[alias] = name
        bump_schema_version()
        return fn

    return deco


def resolve_alias(name: str) -> str:
    return _ALIASES.get(name, name)


def get_tool(name: str) -> Tool | None:
    canonical = _ALIASES.get(name, name)
    return _REGISTRY.get(canonical)


def all_tools(
    *,
    enabled_toolsets: list[str] | None = None,
    disabled: list[str] | None = None,
) -> list[Tool]:
    """Return every registered tool, optionally filtered.

    ``enabled_toolsets=None`` returns all tools (legacy / default).
    ``enabled_toolsets=[]`` returns no tools — a valid scope for sub-agents
    that should produce a final answer without taking actions.
    ``disabled`` is subtracted last.
    """
    disabled_set = set(disabled or [])
    if enabled_toolsets is None:
        names = set(_REGISTRY.keys())
    else:
        names = set()
        for ts in enabled_toolsets:
            names |= _TOOLSETS.get(ts, set())
    names -= disabled_set
    return [t for n, t in _REGISTRY.items() if n in names]


def ollama_schema(
    *,
    enabled_toolsets: list[str] | None = None,
    disabled: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build the tools[] array Ollama expects.

    Tools whose ``check_fn`` is set and returns False are omitted;
    ``check_fn`` is called fresh on every invocation. The post-toolset,
    post-disabled tool list is memoized by (schema_version, enabled_toolsets,
    disabled) so we don't walk the whole registry every turn.
    """
    key = (
        _SCHEMA_VERSION,
        tuple(enabled_toolsets) if enabled_toolsets is not None else None,
        tuple(disabled or ()),
    )
    tools = _FILTER_CACHE.get(key)
    if tools is None:
        tools = all_tools(enabled_toolsets=enabled_toolsets, disabled=disabled)
        _FILTER_CACHE[key] = tools
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
        if t.check_fn is None or t.check_fn()
    ]


def dispatch(name: str, arguments: Any) -> str:
    """Call a tool by name with arguments dict (or JSON string).

    Returns the string result that goes back to the model. Catches exceptions
    so the agent can keep going. Names matching an alias are resolved to the
    canonical tool.
    """
    t = get_tool(name)
    if not t:
        # Suggest the nearest real tool so a model that hallucinated or
        # typo'd a name can self-correct instead of repeating it.
        known = sorted(set(_REGISTRY) | set(_ALIASES))
        close = difflib.get_close_matches(name, known, n=3, cutoff=0.6)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        return f"ERROR: unknown tool '{name}'.{hint}"
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return f"ERROR: arguments to '{name}' were not valid JSON: {arguments!r}"
    if not isinstance(arguments, dict):
        return f"ERROR: arguments to '{name}' must be an object, got {type(arguments).__name__}"

    from . import thrash

    thrash_warning = thrash.precheck(name, arguments)
    if thrash_warning is not None:
        return thrash_warning

    sig = inspect.signature(t.func)
    accepts_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if accepts_var_kw:
        valid = dict(arguments)
    else:
        valid = {k: v for k, v in arguments.items() if k in sig.parameters}
    # Actionable feedback for malformed calls so a small/local model can
    # self-correct: name the required args it omitted, and flag arg names
    # we had to drop (often a typo of a real param — silently dropping
    # them otherwise left the model to fail with an opaque TypeError and
    # no clue which name was wrong).
    required = [
        p.name
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and p.default is inspect.Parameter.empty
    ]
    missing = [p for p in required if p not in valid]
    if missing:
        dropped = [] if accepts_var_kw else [k for k in arguments if k not in sig.parameters]
        hints = [
            f"'{d}' looks like '{near[0]}'"
            for d in dropped
            if (near := difflib.get_close_matches(d, missing, n=1, cutoff=0.6))
        ]
        accepted = [
            p.name
            for p in sig.parameters.values()
            if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        ]
        msg = f"ERROR: tool '{name}' is missing required argument(s): {', '.join(missing)}."
        if hints:
            msg += " " + "; ".join(hints) + "."
        elif dropped:
            msg += f" (ignored unknown argument(s): {', '.join(dropped)})"
        msg += f" Accepted arguments: {', '.join(accepted)}."
        return msg
    try:
        result = t.func(**valid)
        if not isinstance(result, str):
            result = json.dumps(result, default=str)
    except Exception as e:
        import sys

        print(f"[tool {name}] {traceback.format_exc()}", file=sys.stderr)
        result = f"ERROR running {name}: {type(e).__name__}: {e}"
    thrash.record(name, arguments, result)
    return result
