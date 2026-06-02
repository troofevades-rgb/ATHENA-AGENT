"""Agent loop top-level surface.

R1 split this 2000+ line file into purpose-focused mixins; what
remains here is the public :class:`Agent` declaration, the small
public methods external callers reach for (``write_status_snapshot``,
``load_history_from_session``, ``last_assistant_message``,
``tool_call_trace``), the module-level tool-call recovery helpers
that ``Agent`` runs over raw provider output, and the ``fork`` shim
bound to ``Agent`` at module load. Heavy lifting lives in:

  * :mod:`athena.agent.lifecycle` -- ``__init__``, ``close``, system
    prompt build, plugin / session-start wiring (R1 stages 2 + 4)
  * :mod:`athena.agent.runtime` -- the per-turn hot loop:
    ``run_turn``, streaming, tool dispatch, context compression
    (R1 stage 3)
  * :mod:`athena.agent.goal_integration` -- ``/goal`` continuation
    hooks (R1 stage 1)
  * :mod:`athena.agent.context` -- the ``_current_agent`` ContextVar
  * :mod:`athena.agent.stats` -- the :class:`Stats` dataclass
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .. import ui
from .context import _current_agent, get_current_agent  # noqa: F401 -- re-export
from .goal_integration import AgentGoalIntegration
from .lifecycle import AgentLifecycle
from .runtime import AgentRuntime
from .stats import Stats  # noqa: F401 -- re-export

_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)
_TOOL_CALL_TAG_RE = re.compile(r"<tool_call>\s*(.+?)\s*</tool_call>", re.S)
# harmony / GPT-OSS style: <function=name>\n<parameter=key>\nvalue\n</parameter>\n</function>
_FUNCTION_TAG_RE = re.compile(r"<function=([^>\s]+)>(.*?)</function>", re.S)
_PARAMETER_TAG_RE = re.compile(r"<parameter=([^>\s]+)>(.*?)</parameter>", re.S)
_STRAY_TC_RE = re.compile(r"</?tool_call>")


def _coerce_arg(v: str) -> Any:
    """Best-effort type coercion for harmony-style string params (int, bool, json)."""
    s = v.strip()
    if not s:
        return ""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s


# Cap for ATHENA.md / MEMORY.md when injecting into the system prompt. Anything
# larger gets truncated with a notice so a runaway document can't blow context.
_MAX_DOCUMENT_BYTES = 32_000

# Module logger. Previously the two ``except`` blocks in __init__ that log
# init failures (cross-session cache, browser session) referenced ``logger``
# without defining it — a NameError waiting to happen if either init ever
# raised. The except clauses are deep in the warm path so production never
# tripped it, but adding the import now makes the recovery actually work.
logger = logging.getLogger(__name__)


# The _current_agent ContextVar + get_current_agent live in
# athena.agent.context (R1 stage 3) so AgentRuntime can read/swap
# them without a runtime -> core cycle. The names are re-exported
# above so existing imports (``from athena.agent.core import
# get_current_agent`` -- many callers) keep working.


def _normalize_tool_call(obj: Any) -> list[dict]:
    """Normalize various tool-call shapes into Ollama's wrapped format."""
    if isinstance(obj, list):
        out: list[dict] = []
        for item in obj:
            out.extend(_normalize_tool_call(item))
        return out
    if not isinstance(obj, dict):
        return []
    if "name" in obj and "arguments" in obj and isinstance(obj.get("arguments"), (dict, str)):
        return [{"function": {"name": obj["name"], "arguments": obj["arguments"]}}]
    if "function" in obj and isinstance(obj["function"], dict):
        fn = obj["function"]
        if "name" in fn:
            return [{"function": {"name": fn["name"], "arguments": fn.get("arguments", {})}}]
    if "tool_calls" in obj and isinstance(obj["tool_calls"], list):
        return _normalize_tool_call(obj["tool_calls"])
    return []


def _extract_text_tool_calls(text: str) -> tuple[str, list[dict]]:
    """Recover tool calls from content text when the model emits them as JSON
    or as <tool_call>...</tool_call> tags instead of using Ollama's tool_calls
    field. Some Ollama+model combos leak tool calls into content under
    streaming; this fallback makes athena robust to that failure mode.
    """
    s = text.strip()
    if not s:
        return text, []

    # Qwen's native <tool_call>...</tool_call> XML tags (sometimes leaked as text)
    tag_matches = _TOOL_CALL_TAG_RE.findall(s)
    if tag_matches:
        all_calls: list[dict] = []
        bad = 0
        for m in tag_matches:
            try:
                obj = json.loads(m)
                all_calls.extend(_normalize_tool_call(obj))
            except json.JSONDecodeError:
                bad += 1
                continue
        if all_calls:
            residual = _TOOL_CALL_TAG_RE.sub("", s).strip()
            return residual, all_calls
        if bad:
            ui.warn(f"found {bad} <tool_call> tag(s) but none parsed as JSON")

    # Harmony / GPT-OSS style <function=name><parameter=key>val</parameter></function>
    fn_matches = list(_FUNCTION_TAG_RE.finditer(s))
    if fn_matches:
        all_calls: list[dict] = []
        for fm in fn_matches:
            name = fm.group(1).strip()
            body = fm.group(2)
            args: dict[str, Any] = {}
            for pm in _PARAMETER_TAG_RE.finditer(body):
                args[pm.group(1).strip()] = _coerce_arg(pm.group(2))
            all_calls.append({"function": {"name": name, "arguments": args}})
        if all_calls:
            residual = _FUNCTION_TAG_RE.sub("", s)
            residual = _STRAY_TC_RE.sub("", residual).strip()
            return residual, all_calls

    # Whole-text JSON
    try:
        obj = json.loads(s)
        calls = _normalize_tool_call(obj)
        if calls:
            return "", calls
    except json.JSONDecodeError:
        pass

    # Code-fenced JSON
    m = _FENCE_RE.search(s)
    if m:
        try:
            obj = json.loads(m.group(1))
            calls = _normalize_tool_call(obj)
            if calls:
                return (s[: m.start()] + s[m.end() :]).strip(), calls
        except json.JSONDecodeError:
            pass

    # Preamble + naked JSON object. Seen with qwen2.5-coder on Ollama:
    # the model emits a one-line natural preamble, then a tool-call JSON
    # blob without any wrapper. Scan from the first ``{`` to a
    # brace-balanced ``}`` and try json.loads on every candidate; accept
    # the first match that normalizes to a tool call shape. Conservative:
    # we only consider objects whose shape includes ``name`` (str) plus
    # ``arguments`` (dict/str), so prose containing literal ``{...}``
    # JSON examples doesn't trip us.
    for start in range(len(s)):
        if s[start] != "{":
            continue
        depth = 0
        in_str = False
        esc = False
        for end in range(start, len(s)):
            ch = s[end]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = s[start : end + 1]
                    try:
                        obj = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    calls = _normalize_tool_call(obj)
                    if calls:
                        residual = (s[:start] + s[end + 1 :]).strip()
                        return residual, calls
                    break

    return text, []


# System prompt is assembled dynamically from athena.prompts.build_system_prompt().
# Sections live in athena/prompts/system.py.


class Agent(AgentLifecycle, AgentRuntime, AgentGoalIntegration):
    # _cancel_in_flight, _build_plugin_hooks, _run_session_start_hooks,
    # _init_cross_session_cache, _build_system, _profile_dir, _load_goal,
    # _load_goal_state, _configure_shell_hook_plugin, reload_skills,
    # reload_goal, and reset moved to athena/agent/lifecycle.py:
    # AgentLifecycle (R1 stage 2). All still on the Agent surface via
    # the mixin in the class declaration above.

    # _consult_goal_continuation and _persist_goal_state moved to
    # athena/agent/goal_integration.py:AgentGoalIntegration (R1 stage 1).
    # Both methods are still on the Agent surface via the mixin.

    def write_status_snapshot(self) -> None:
        """Atomically write ``<profile_dir>/.status.json`` with the
        current Stats. Read by :mod:`athena.cli.status`.

        Atomic via tempfile + ``os.replace`` so a concurrent
        ``athena status`` invocation never reads a half-written file.
        Silent no-op when the agent has no SessionStore (no profile
        dir to write into).
        """
        if self.session_store is None:
            return
        try:
            profile = self.cfg.profile or "default"
            snapshot = self.stats.to_snapshot(
                session_id=self.session_id,
                model=self.model,
                provider=getattr(self.provider, "name", "?"),
                profile=profile,
                cache_strategy=getattr(self.cfg, "cache_strategy", None),
                prompt_cache_ttl=getattr(self.cfg, "prompt_cache_ttl", None),
            )
            # Parser-fallback canary (process-global): surfaces models
            # whose tool calls are riding on heuristic extraction because
            # no parser matched. JSON-keyed as "provider/model".
            from ..providers.parsers import fallback_counts

            fb = {f"{p}/{m}": c for (p, m), c in fallback_counts().items()}
            if fb:
                snapshot["parser_fallbacks"] = fb
        except Exception:
            return
        target = self.session_store.profile_dir / ".status.json"
        try:
            import os

            tmp = target.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(snapshot, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, target)
        except OSError:
            pass

    # -- introspection helpers used by Agent.fork() ---------------------

    def load_history_from_session(self, session_id: str) -> int:
        """Replace conversation history with the JSONL for ``session_id``.

        Used by the gateway agent pool to rehydrate a warm agent from
        a persisted session: keeps :attr:`messages[0]` (the system
        prompt) and appends every saved turn from
        ``<session_store>/<session_id>.jsonl``.

        Returns the number of turns loaded (excluding the system
        prompt). Returns 0 — and leaves history unchanged — when the
        store is not configured or the JSONL doesn't exist.
        """
        if self.session_store is None:
            return 0
        jsonl_path = self.session_store.sessions_dir / f"{session_id}.jsonl"
        if not jsonl_path.exists():
            return 0
        try:
            text = jsonl_path.read_text(encoding="utf-8")
        except OSError:
            return 0

        loaded: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                loaded.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        # Preserve the system prompt (already cached + pinned by
        # whatever path constructed this agent) and replace history.
        system = self.messages[0] if self.messages else None
        self.messages = [system] if system else []
        self.messages.extend(loaded)
        self.session_id = session_id
        return len(loaded)

    def last_assistant_message(self) -> str:
        """Return the most recent assistant message's content (or empty string)."""
        for m in reversed(self.messages):
            if m.get("role") == "assistant":
                content = m.get("content")
                if isinstance(content, list):
                    return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                return content or ""
        return ""

    def tool_call_trace(self) -> list[dict[str, Any]]:
        """Flat list of every tool call this agent has made so far."""
        out: list[dict[str, Any]] = []
        for m in self.messages:
            if m.get("role") == "assistant":
                out.extend(m.get("tool_calls") or [])
        return out


# Bind fork() as an Agent method. Done at module load so `Agent(...).fork(...)`
# works without circular-import gymnastics in callers.
from .fork import fork as _fork_impl  # noqa: E402


def _agent_fork(self, **kwargs):
    return _fork_impl(self, **kwargs)


Agent.fork = _agent_fork
