"""Tool registry. Tools register themselves via @tool() and expose:
   - a name
   - a JSON schema description (Ollama function-call format)
   - a Python callable that takes kwargs from the model and returns a string

Tools are scoped into named toolsets. The agent (and forks) advertise tools to
the model by filtering the registry to a subset of toolsets via the
``enabled_toolsets`` keyword. A tool may also declare a ``check_fn`` whose
return value gates whether the tool is advertised at all on a given call.
"""

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


_REGISTRY: dict[str, Tool] = {}
_TOOLSETS: dict[str, set[str]] = {}
_ALIASES: dict[str, str] = {}


def tool(
    *,
    name: str,
    description: str,
    parameters: dict[str, Any],
    toolset: str = "core",
    requires_confirmation: bool = False,
    check_fn: Callable[[], bool] | None = None,
    aliases: list[str] | None = None,
) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """Register a function as a tool.

    ``toolset`` groups the tool with peers; callers select active toolsets via
    ``enabled_toolsets``. ``check_fn`` is re-evaluated every time the schema
    is rendered so connection-state-dependent tools reflect current availability.
    ``aliases`` registers additional dispatch names — aliases are NOT included
    in the schema sent to the model.
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
        )
        _REGISTRY[name] = t
        _TOOLSETS.setdefault(toolset, set()).add(name)
        for alias in t.aliases:
            _ALIASES[alias] = name
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

    Tools whose ``check_fn`` is set and returns False are omitted; ``check_fn``
    is called fresh on every invocation, not cached.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in all_tools(enabled_toolsets=enabled_toolsets, disabled=disabled)
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
        return f"ERROR: unknown tool '{name}'"
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
