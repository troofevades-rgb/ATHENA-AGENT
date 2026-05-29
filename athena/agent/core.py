"""Agent loop: ferry messages between user, Ollama, and tools until done."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import tools, ui
from ..config import Config
from ..config import profile_dir as _profile_dir
from ..plugins.hooks import HookDispatcher
from ..prompts import build_system_prompt
from ..providers import Provider
from ..providers.credential_pool import global_pool as _global_pool
from ..providers.runtime_resolver import resolve_provider
from ..safety.approval_callback import get_approval_callback
from ..sessions.store import SessionMeta, SessionStore, new_session_id
from .context import _current_agent, get_current_agent  # noqa: F401 -- re-export
from .goal_integration import AgentGoalIntegration
from .lifecycle import AgentLifecycle
from .param_policy import ParamPolicy, PolicyInput, policy_from_config
from .runtime import AgentRuntime

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


@dataclass
class Stats:
    """Running counters for the active agent session.

    The first four fields (``prompt_tokens`` / ``eval_tokens`` /
    ``tool_calls`` / ``turns``) plus ``started`` are the original
    Phase 0 shape — kept for the ``/cost`` slash command and any
    external readers (``tool_call_trace``-style consumers).

    Phase 16 adds per-tool counts + fork / review / curator counters
    and an atomic snapshot writer so ``athena status`` (running in
    a separate process) can read live progress without IPC.
    """

    prompt_tokens: int = 0
    eval_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    started: float = field(default_factory=time.time)
    # Phase 16 additions:
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    fork_count: int = 0
    review_fired_count: int = 0
    curator_run_count: int = 0
    # T2-01: Anthropic prompt-cache counters, populated from the
    # provider's usage chunk. ``cache_read`` is the prefix the API
    # served from cache (cheap); ``cache_creation`` is the new prefix
    # being cached this turn (slightly more expensive than normal
    # input).
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def record_tool_call(self, tool_name: str) -> None:
        """Increment both the top-level counter (legacy ``/cost``)
        and the per-tool histogram used by ``/status``."""
        self.tool_calls += 1
        self.tool_call_counts[tool_name] = self.tool_call_counts.get(tool_name, 0) + 1

    def to_snapshot(
        self,
        *,
        session_id: str | None,
        model: str,
        provider: str,
        profile: str,
        cache_strategy: str | None = None,
        prompt_cache_ttl: str | None = None,
    ) -> dict:
        return {
            "session_id": session_id,
            "model": model,
            "provider": provider,
            "profile": profile,
            "started_at": self.started,
            "elapsed_seconds": time.time() - self.started,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "tool_call_counts": dict(self.tool_call_counts),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.eval_tokens,
            "total_tokens": self.prompt_tokens + self.eval_tokens,
            "fork_count": self.fork_count,
            "review_fired_count": self.review_fired_count,
            "curator_run_count": self.curator_run_count,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_strategy": cache_strategy,
            "prompt_cache_ttl": prompt_cache_ttl,
        }


class Agent(AgentLifecycle, AgentRuntime, AgentGoalIntegration):
    def __init__(
        self,
        cfg: Config,
        workspace: Path,
        model: str | None = None,
        *,
        session_store: SessionStore | None = None,
        parent_session_id: str | None = None,
        client: Provider | None = None,
        provider: Provider | None = None,
        plugin_hooks: HookDispatcher | None = None,
        resume_session_id: str | None = None,
    ):
        self.cfg = cfg
        self.workspace = workspace.resolve()
        self.model = model or cfg.model
        # Parseltongue: inference param policy. Built once at init from
        # the [parseltongue] config section; consulted before every
        # provider.stream_chat call to pick temperature / top_p / top_k
        # / repeat_penalty / mirostat* based on what's happening this
        # turn. ``None`` config or ``policy = "heuristic"`` is the
        # default; ``policy = "static"`` opts back into the pre-
        # parseltongue static-defaults behaviour.
        self._param_policy: ParamPolicy = policy_from_config(
            getattr(cfg, "parseltongue", None)
        )
        # Reset the per-process thrash buffer so a prior session's
        # repeat-call history doesn't bleed into this one.
        from ..tools import thrash as _thrash

        _thrash.reset()
        # Phase 8: the canonical attribute is now ``self.provider``. ``client``
        # is preserved as an alias (and as a constructor kwarg) for one
        # transitional release — existing call sites and tests that pass
        # ``client=`` keep working unchanged.
        passed = provider if provider is not None else client
        if passed is not None:
            self.provider: Provider = passed
            # Strip any routing prefix off self.model even when a
            # provider was passed in — otherwise the prefixed name
            # ("anthropic/claude-sonnet-4-6") goes straight onto the
            # wire and the hosted API rejects it as unknown. Affects
            # forks built via build_auxiliary_client.
            from ..providers.runtime_resolver import _bare_model, _route

            self.model = _bare_model(_route(self.model, cfg), self.model)
        else:
            # Route through the resolver. It returns the matching Provider
            # AND the bare model name (with any routing prefix stripped),
            # so ``self.model`` carries the on-the-wire name from here on.
            self.provider, self.model = resolve_provider(
                self.model,
                cfg,
                _global_pool(),
            )
        self.client = self.provider  # back-compat alias
        self._owns_client = passed is None
        self.messages: list[dict[str, Any]] = []
        self.stats = Stats()
        # Set by external callers (currently: ACP session/cancel) to
        # abort the current turn at the next tool-call boundary.
        # Checked between tool rounds and cleared at the start of
        # every new run_turn so a stale True from a prior turn doesn't
        # immediately abort.
        self.cancel_pending: bool = False
        # Cache for Modelfile SYSTEM keyed by model name; avoids re-fetching
        # on every /clear or /resume. Invalidated implicitly by /model switching
        # to an unseen model name.
        self._model_system_cache: dict[str, str] = {}
        # Serializes run_turn so the REPL thread and a /loop thread cannot
        # interleave turns or corrupt self.messages.
        self._turn_lock = threading.Lock()
        # Configure tools with workspace
        tools.file_ops.set_workspace(self.workspace, max_read=cfg.max_file_read)
        tools.shell.set_max_output(cfg.max_bash_output)
        # T2-06: out-of-band storage for large tool outputs. Each
        # Agent owns one ToolResultStorage; the read_tool_result tool
        # fetches it via get_current_agent() at call time.
        from ..tools.tool_result_storage import ToolResultStorage

        self.tool_result_storage = ToolResultStorage(
            Path(getattr(cfg, "tool_result_storage_path", "~/.athena/tool_results")).expanduser(),
            session_id="pending",  # rebound below once session_id is allocated
        )
        # ShellHookPlugin (bundled, enabled by default) replaces the legacy
        # athena.hooks settings.json reader. The plugin's
        # ``configure_workspace`` call below runs AFTER plugin_hooks is
        # built so workspace-local .athena/settings.json contributes
        # alongside ~/.athena/settings.json.
        # Session lineage. Three modes:
        #   1. session_store passed (fork path) → use it for a new child session
        #      tagged with parent_session_id.
        #   2. cfg.profile set (normal startup) → open our own store.
        #   3. cfg.profile == "" → no session persistence (deliberate opt-out).
        self.parent_session_id = parent_session_id
        self.session_store: SessionStore | None = None
        self.session_id: str | None = None
        self._owns_session_store = False
        # The most recent background-review summary, surfaced to the UI on
        # the next prompt. Populated by athena.review.orchestrator after each
        # review fork completes.
        self.last_review_summary: dict | None = None
        # Most recently spawned background-review thread. The agent
        # waits for this to finish before starting the next
        # foreground turn's model call so we don't run two
        # concurrent Ollama inferences fighting for GPU time.
        # See _wait_for_background_work() and maybe_fire_review().
        self._active_review_thread: threading.Thread | None = None
        # Optional polling skill-watcher (cfg.skills_autoload).
        # Started by _maybe_start_skill_watcher after history is
        # materialised; stopped in close(). None when autoload is off.
        self._skill_watcher = None  # type: ignore[var-annotated]
        # Persistent /goal invariant. Loaded from <profile_dir>/goal.txt at
        # session start and re-injected into the system prompt on every
        # rebuild. Mutated by the /goal slash command via Agent.reload_goal().
        self.goal: str | None = self._load_goal()
        # T5-07: active continuation state alongside the passive
        # invariant. None when no goal is set. Mutated by
        # /goal subcommands + the continuation hook in run_turn.
        self.goal_state = self._load_goal_state()
        # Per-turn tracking exposed to run_turn for the continuation
        # decision. Reset on every _run_turn_inner entry.
        self._last_assistant_text: str = ""
        self._last_turn_interrupted: bool = False
        # Running token budget for the active goal loop. Reset when
        # a new goal is set or the loop terminates. Each
        # continuation step adds the turn's prompt + eval tokens.
        self._goal_loop_tokens_used: int = 0
        if session_store is not None:
            self.session_store = session_store
            if resume_session_id is not None:
                # Gateway resume path: attach to an existing session id,
                # don't mint a new one. open_session is idempotent on a
                # session_id that already exists (it overwrites the meta
                # sidecar with current model/workspace, which is what we
                # want for a "warm pickup" after a model change). The
                # JSONL stays untouched so history reload below sees it.
                self.session_id = resume_session_id
                try:
                    self.session_store.open_session(
                        SessionMeta(
                            session_id=self.session_id,
                            profile=cfg.profile or "default",
                            model=self.model,
                            workspace=str(self.workspace),
                            parent_session_id=parent_session_id,
                        )
                    )
                except Exception as e:
                    ui.warn(f"session store resume failed: {e}")
                    self.session_id = None
            else:
                self.session_id = new_session_id()
                try:
                    self.session_store.open_session(
                        SessionMeta(
                            session_id=self.session_id,
                            profile=cfg.profile or "default",
                            model=self.model,
                            workspace=str(self.workspace),
                            parent_session_id=parent_session_id,
                        )
                    )
                except Exception as e:
                    ui.warn(f"session store open failed: {e}")
                    self.session_id = None
        elif cfg.profile:
            try:
                self.session_store = SessionStore(_profile_dir(cfg.profile))
                self._owns_session_store = True
                self.session_id = new_session_id()
                self.session_store.open_session(
                    SessionMeta(
                        session_id=self.session_id,
                        profile=cfg.profile,
                        model=self.model,
                        workspace=str(self.workspace),
                        parent_session_id=parent_session_id,
                    )
                )
            except Exception as e:
                ui.warn(f"session store unavailable: {e}")
                self.session_store = None
                self.session_id = None
        # T2-06: rebind tool_result_storage's session_id now that we
        # know it (storage was eagerly created earlier with "pending"
        # before the session_id allocation flow ran).
        self.tool_result_storage.session_id = self.session_id or "no-session"
        # T3-03: build a CheckpointManager for foreground sessions.
        # Forks (session_store passed in) skip — checkpoints belong to
        # the parent session, and the fork's writes don't survive past
        # the fork's lifetime anyway. Best-effort: a build failure
        # leaves checkpoint_manager=None and slash commands surface
        # that clearly.
        self.checkpoint_manager = None
        if session_store is None and self.session_id is not None:
            try:
                from ..safety.snapshots import SnapshotStore
                from .checkpoints import CheckpointAuditLog, CheckpointManager

                profile = cfg.profile or "default"
                pdir = _profile_dir(profile)
                ckpt_dir = pdir / "checkpoints" / self.session_id
                session_log = pdir / "sessions" / f"{self.session_id}.jsonl"
                # Wire the [safety] retention policy from cfg.safety.
                # Until R4 stage 2 SnapshotStore was constructed with
                # its hardcoded defaults regardless of what the user
                # had configured -- the [safety] TOML table was a
                # promise the code never kept.
                safety_cfg = self.cfg.safety
                snapshot_store = SnapshotStore(
                    retention_days=safety_cfg.retention_days,
                    retention_count=safety_cfg.retention_count,
                    retention_bytes=safety_cfg.retention_bytes,
                )
                self.checkpoint_manager = CheckpointManager(
                    session_id=self.session_id,
                    session_log_path=session_log,
                    checkpoint_dir=ckpt_dir,
                    snapshot_store=snapshot_store,
                    profile_dir=pdir,
                    workspace=self.workspace,
                    audit_log=CheckpointAuditLog(ckpt_dir / "audit.jsonl"),
                )
            except Exception as e:  # noqa: BLE001
                ui.warn(f"checkpoint manager unavailable: {e}")
        # T3-06R: per-skill usage metrics. Foreground sessions get an
        # active store rooted in the profile dir; forks share their
        # parent's store via the ContextVar (the fork.py runner pins
        # the context). Disabled by config → a no-op store so the
        # hook callsites stay quiet.
        self.skill_metrics_store = None
        if session_store is None and self.session_id is not None:
            try:
                from ..skills.metrics import (
                    SkillMetricsStore,
                    _NoopStore,
                    metrics_path,
                )

                profile = cfg.profile or "default"
                pdir2 = _profile_dir(profile)
                if getattr(cfg, "skill_metrics_enabled", True):
                    self.skill_metrics_store = SkillMetricsStore(metrics_path(pdir2))
                else:
                    self.skill_metrics_store = _NoopStore()
            except Exception as e:  # noqa: BLE001
                ui.warn(f"skill metrics store unavailable: {e}")
        # Run lifecycle transitions + (gated) curator at real session starts.
        # Forks skip both: session_store is inherited from parent, parent
        # already ran them, and a fork doing it again would race.
        if session_store is None and cfg.profile:
            self._run_session_start_hooks()
        # Plugin hooks. Foreground agents construct the dispatcher by
        # discovering+loading plugins; forks inherit an empty dispatcher by
        # default (callers can pass plugin_hooks explicitly to share parent's).
        # A broken plugin layer must never break the agent — wrap construction.
        if plugin_hooks is not None:
            self.plugin_hooks = plugin_hooks
        elif session_store is None and cfg.profile:
            self.plugin_hooks = self._build_plugin_hooks()
        else:
            self.plugin_hooks = HookDispatcher(plugins=[])
        # Fire on_session_start once the session_id exists.
        if self.session_id is not None:
            self.plugin_hooks.on_session_start(self.session_id, cfg.profile or "default")
        # Wire ShellHookPlugin's workspace AFTER on_session_start so it
        # can re-read settings.json with the correct workspace context.
        self._configure_shell_hook_plugin()
        # Build initial system message
        self.messages.append({"role": "system", "content": self._build_system()})

        # T5-06: cross-session prompt cache. Best-effort: a lookup
        # failure or absent provider must never block session
        # start. Records on miss so the next session in this
        # workspace can hit. Reuse mechanics (server cache /
        # KV reuse) are the provider/backend's job — the index
        # is athena's observation surface.
        self.cross_session_cache_entry = None
        try:
            self._init_cross_session_cache()
        except Exception:  # noqa: BLE001
            logger.debug("cross-session cache init failed", exc_info=True)

        # T4-03: bind a persistent BrowserSession for this athena
        # session. Lazy — construction does NOT launch chromium;
        # only the first browser_* tool call triggers
        # ensure_started(). An unused browser costs nothing.
        # Forks inherit via ContextVar so a fork uses the parent's
        # browser; this happens automatically via the ContextVar
        # copy at thread/task spawn.
        self.browser_session = None
        try:
            from ..browser.session import BrowserSession, set_active_browser
            if self.session_id is not None and getattr(cfg, "browser_enabled", True):
                self.browser_session = BrowserSession(
                    session_id=self.session_id, cfg=cfg,
                )
                set_active_browser(self.browser_session)
        except Exception:  # noqa: BLE001
            logger.debug("browser session init failed", exc_info=True)

        # Register a cancel hook so the gateway's interrupt path can
        # abort an in-flight LLM stream by closing the provider's
        # httpx client. Without this, _thread.interrupt_main() alone
        # doesn't deliver because the main thread is blocked in C
        # code (socket.recv) inside the stream and KeyboardInterrupt
        # only fires at the next bytecode boundary — which can be
        # minutes away on slow models. The user's symptom was "ESC
        # does nothing; I have to kill the terminal."
        try:
            from .. import interrupt_hooks as _ih
            _ih.register_cancel_hook(self._cancel_in_flight)
        except Exception:  # noqa: BLE001
            logger.debug("cancel hook registration failed", exc_info=True)

        # Optional skill watcher (cfg.skills.autoload). Kicks off a
        # daemon thread that polls the skill search paths and triggers
        # reload_skills() when a SKILL.md is added, edited, or
        # removed. OFF by default to avoid the background thread for
        # users who never edit skills mid-session.
        skills_cfg = getattr(cfg, "skills", None)
        if skills_cfg is not None and skills_cfg.autoload:
            try:
                from ..skills.watcher import SkillWatcher

                self._skill_watcher = SkillWatcher(
                    workspace=self.workspace,
                    on_change=self.reload_skills,
                    poll_interval=float(skills_cfg.autoload_interval),
                )
                self._skill_watcher.start()
            except Exception:  # noqa: BLE001
                logger.debug("skill watcher start failed", exc_info=True)

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


    def close(self) -> None:
        # Drop the cancel hook __init__ registered so long-lived
        # daemons (gateway, webhook, cron) don't accumulate one
        # bound-method-per-evicted-Agent in the module-level _hooks
        # list. Each entry pinned the entire Agent (provider,
        # SessionStore, messages); after thousands of session
        # rotations the leak was the dominant memory consumer.
        try:
            from .. import interrupt_hooks as _ih
            _ih.unregister_cancel_hook(self._cancel_in_flight)
        except Exception:  # noqa: BLE001
            logger.debug("cancel hook unregistration failed", exc_info=True)
        # Tear down the optional skill watcher (if running).
        if getattr(self, "_skill_watcher", None) is not None:
            try:
                self._skill_watcher.stop()
            except Exception:  # noqa: BLE001
                logger.debug("skill watcher stop failed", exc_info=True)
            self._skill_watcher = None
        # Plugin lifecycle end. Always fires when a session_id exists,
        # regardless of cleanup success below. The completed/interrupted
        # distinction is a Phase 10 concern (the gateway tracks it); for
        # now close() always reports completed=True.
        if self.session_id is not None:
            try:
                self.plugin_hooks.on_session_end(self.session_id, completed=True, interrupted=False)
            except Exception:
                pass
            # Drop this session's entry from the per-session review
            # nudge counter so long-lived daemons (gateway, scheduled
            # cron) don't accumulate stale ints forever.
            try:
                from ..review.nudge import reset as _nudge_reset
                _nudge_reset(self.session_id)
            except Exception:
                pass
        if self._owns_client:
            try:
                self.client.close()
            except Exception:
                pass
        if self.session_store is not None and self.session_id is not None:
            try:
                self.session_store.close_session(self.session_id)
            except Exception:
                pass
            if self._owns_session_store:
                try:
                    self.session_store.close()
                except Exception:
                    pass
        # T4-03: tear down the persistent browser session.
        # Idempotent — close() is safe to call even when
        # ensure_started never fired (no chromium to tear down).
        # The user_data_dir on disk persists for a future
        # resume; only the live process is released here.
        if getattr(self, "browser_session", None) is not None:
            try:
                self.browser_session.close()
            except Exception:
                pass
            try:
                from ..browser.session import set_active_browser
                set_active_browser(None)
            except Exception:
                pass


# Bind fork() as an Agent method. Done at module load so `Agent(...).fork(...)`
# works without circular-import gymnastics in callers.
from .fork import fork as _fork_impl  # noqa: E402


def _agent_fork(self, **kwargs):
    return _fork_impl(self, **kwargs)


Agent.fork = _agent_fork
