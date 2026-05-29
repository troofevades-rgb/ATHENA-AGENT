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
from .param_policy import ParamPolicy, PolicyInput, policy_from_config

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


# ContextVar so a fork running on its own thread can register itself as the
# current parent for any grand-children it spawns, without clobbering the
# foreground agent on the main thread.
_current_agent: contextvars.ContextVar[Agent | None] = contextvars.ContextVar(
    "athena_current_agent", default=None
)


def get_current_agent() -> Agent | None:
    """Return the Agent whose run_turn is currently active on this context, or None."""
    return _current_agent.get()


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


class Agent:
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

    def _cancel_in_flight(self) -> None:
        """Force an in-flight LLM HTTP stream to abort. Called from
        the gateway reader thread on InterruptCommand. MUST NOT
        raise — the cancel-hook dispatcher catches but logs noisily.

        Preferred path: ``provider.abort_current_stream()`` — closes
        just the current Response so the Client stays alive for the
        next request. All hosted providers (openai/anthropic/ollama)
        expose this.

        Fallback: close the whole Client (older providers without
        the abort method) — they'll need to rebuild lazily."""
        prov = getattr(self, "provider", None)
        if prov is None:
            return
        abort = getattr(prov, "abort_current_stream", None)
        if callable(abort):
            try:
                abort()
                return
            except Exception:  # noqa: BLE001
                logger.debug(
                    "provider.abort_current_stream raised; falling back to client close",
                    exc_info=True,
                )
        client = getattr(prov, "_client", None)
        if client is None:
            return
        try:
            client.close()
        except Exception:  # noqa: BLE001
            logger.debug("provider client close raised during cancel", exc_info=True)

    def _build_plugin_hooks(self) -> HookDispatcher:
        """Discover + load enabled plugins. Best-effort; a load failure must
        never break agent startup, so the result on error is an empty
        dispatcher.
        """
        try:
            from ..plugins.discovery import discover
            from ..plugins.loader import load_plugins

            manifests = discover()
            # The plugin loader's contract is a dict-shaped config; the
            # PluginsConfig dataclass exposes ``as_dict_for_loader`` to
            # reconstitute the legacy envelope. Defensive fallback for
            # SimpleNamespace stubs in tests that don't carry the
            # PluginsConfig instance.
            plugins_field = getattr(self.cfg, "plugins", None)
            if plugins_field is None:
                plugins_block: dict = {}
            elif hasattr(plugins_field, "as_dict_for_loader"):
                plugins_block = plugins_field.as_dict_for_loader()
            else:
                plugins_block = dict(plugins_field)
            instances = load_plugins(manifests, config={"plugins": plugins_block})
            if instances:
                ui.info(
                    f"loaded {len(instances)} plugin(s): {', '.join(p.name for p in instances)}"
                )
            return HookDispatcher(plugins=instances)
        except Exception as e:
            ui.info(f"plugin load failed: {e}")
            return HookDispatcher(plugins=[])

    def _run_session_start_hooks(self) -> None:
        """Lifecycle transitions + curator-spawn at session start.

        Both are best-effort; the foreground REPL must never crash because
        a background loop misbehaved.
        """
        try:
            from ..skills.state_machine_runner import run_lifecycle

            run_lifecycle(self.workspace)
        except Exception as e:
            ui.info(f"lifecycle pass skipped: {e}")

        # ``ATHENA_DISABLE_BACKGROUND_CURATOR=1`` short-circuits the
        # session-start curator spawn. The spawn launches a daemon
        # thread that calls ``maybe_run_curator(self)``, which forks
        # another Agent and hits the LLM provider. Agent.close()
        # can't reach the daemon thread to stop it; once spawned, it
        # runs until natural completion or process exit. In pytest,
        # that means a prior test's curator can leak into the next
        # test and race for the same Ollama inference queue —
        # deadlocking under single-inference-at-a-time. Tests set
        # the env var session-wide. Direct calls to
        # ``maybe_run_curator(agent, force=True)`` from curator unit
        # tests are unaffected; only the background spawn is gated.
        import os
        if os.environ.get("ATHENA_DISABLE_BACKGROUND_CURATOR") == "1":
            return
        try:
            import threading

            from ..curator.orchestrator import maybe_run_curator

            def _spawn():
                try:
                    maybe_run_curator(self)
                except Exception as e:
                    ui.info(f"curator run failed: {e}")

            threading.Thread(
                target=_spawn,
                daemon=True,
                name=f"curator-{(self.session_id or 'init')[:8]}",
            ).start()
        except Exception as e:
            ui.info(f"curator could not start: {e}")

    def _init_cross_session_cache(self) -> None:
        """T5-06 — at session start, look up the cross-session
        cache for the current system prefix; record on miss so a
        future session in this workspace can hit.

        Reuse mechanics are the provider/backend's job; this is
        the index half. ``cross_session_cache_entry`` is set to
        the live :class:`CacheEntry` on hit, None otherwise.
        """
        if not getattr(self.cfg, "cross_session_cache_enabled", True):
            return
        from ..cache import CrossSessionCache

        provider_name = getattr(self.provider, "name", "")
        if not provider_name:
            return

        idx_path = getattr(self.cfg, "cache_index_path", None)
        if not idx_path:
            from ..config import profile_dir as _pd

            profile = self.cfg.profile or "default"
            idx_path = _pd(profile) / "cache_index.json"

        cache = CrossSessionCache(index_path=Path(str(idx_path)), cfg=self.cfg)
        plan = cache.caching_plan(provider_name)
        if plan.mode == "none":
            return

        # The "stable prefix" for cache-key purposes is the
        # initial system message bytes. Pinned skills + project
        # context + memory index are already folded into it by
        # _build_system, so a single hash captures the whole
        # stable layer.
        system_msg = self.messages[0]
        prefix_text = system_msg.get("content", "")
        if not isinstance(prefix_text, str) or not prefix_text:
            return

        workspace = str(self.workspace)
        hit = cache.lookup(
            workspace=workspace,
            prefix_text=prefix_text,
            provider=provider_name,
        )
        if hit is not None:
            self.cross_session_cache_entry = hit
            import logging as _logging

            _logging.getLogger(__name__).info(
                "cross-session cache HIT for %s/%s (mode=%s, age=%ds)",
                workspace,
                provider_name,
                plan.mode,
                int(time.time() - hit.created_at),
            )
            return

        # Miss → record the new entry. provider_cache_id is None
        # because the provider's server-side cache id (if any)
        # isn't observable from athena's side — that's the
        # backend's bookkeeping; what we record here is the FACT
        # that this prefix was sent at this time so a fresh
        # next-session can deduce reuse from the matching hash.
        ttl_s = plan.ttl_s or 3600  # kv_reuse has no TTL; pick 1h
        new_entry = cache.record(
            workspace=workspace,
            prefix_text=prefix_text,
            provider=provider_name,
            provider_cache_id=None,
            ttl_s=ttl_s,
        )
        self.cross_session_cache_entry = new_entry
        import logging as _logging

        _logging.getLogger(__name__).info(
            "cross-session cache MISS for %s/%s — recorded (mode=%s, ttl=%ds)",
            workspace,
            provider_name,
            plan.mode,
            ttl_s,
        )

    def _build_system(self) -> str:
        # Modelfile SYSTEM (persona); Ollama drops it when we send our own
        # system message, so re-include it ourselves. Cached per-model.
        if self.model in self._model_system_cache:
            ms = self._model_system_cache[self.model]
        else:
            ms = ""
            try:
                info = self.provider.show_model(self.model)
                ms = (info.get("system") or "").strip()
                if ms:
                    ui.info(f"inherited SYSTEM from {self.model} ({len(ms)} chars)")
            except Exception as e:
                ui.info(f"could not fetch model SYSTEM ({e}); using rules only")
            self._model_system_cache[self.model] = ms
        model_system: str | None = ms or None

        project_context: str | None = None
        project_md = self.workspace / "ATHENA.md"
        if project_md.exists():
            try:
                raw = project_md.read_text(encoding="utf-8")
                if len(raw) > _MAX_DOCUMENT_BYTES:
                    ui.warn(
                        f"{project_md.name} is {len(raw)} bytes; truncating to "
                        f"{_MAX_DOCUMENT_BYTES} for context safety"
                    )
                    project_context = raw[:_MAX_DOCUMENT_BYTES] + "\n\n[truncated]"
                else:
                    project_context = raw
                ui.info(f"loaded {project_md.name} ({len(project_context)} bytes)")
            except OSError:
                pass

        # R2 stage 4: opportunistic one-shot migration of this
        # workspace's legacy memory tree into the new sub-store. No-op
        # when ``cfg.migrate_legacy_memory`` is False (default during
        # the dogfood window) or when the target already exists.
        # Failures inside the migrator are logged but do not break
        # session start.
        try:
            from ..profiles.migration import maybe_migrate_workspace_memory

            summary = maybe_migrate_workspace_memory(self.cfg, self.workspace)
            if summary and summary.get("ran") and summary.get("copied"):
                ui.info(
                    f"migrated {len(summary['copied'])} legacy memory file(s) "
                    f"into {summary['target']}"
                )
        except Exception as e:
            ui.info(f"legacy memory migration skipped: {e}")

        memory_index: str | None = None
        try:
            # R2 stage 2 + 5: read through the profile-keyed provider.
            # The stage-2 fallback to the legacy
            # ``~/.athena/projects/<slug>/memory/MEMORY.md`` path retired
            # at stage 5. Users with legacy data should set
            # ``migrate_legacy_memory = true`` in config.toml -- the
            # opportunistic call to
            # :func:`~athena.profiles.migration.maybe_migrate_workspace_memory`
            # above will copy their entries into the new sub-store on
            # next session, at which point this read sees them. Until
            # the flag flips on, untouched legacy data is still
            # readable on-disk (it's a copy, not a move) and will be
            # picked up the first time the operator opts in.
            from ..memory.store import load_index as _store_load

            profile = self.cfg.profile or "default"
            memory_index = _store_load(profile, workspace=self.workspace)
            if memory_index:
                if len(memory_index) > _MAX_DOCUMENT_BYTES:
                    ui.warn(
                        f"MEMORY.md is {len(memory_index)} bytes; truncating to "
                        f"{_MAX_DOCUMENT_BYTES} for context safety"
                    )
                    memory_index = memory_index[:_MAX_DOCUMENT_BYTES] + "\n\n[truncated]"
                ui.info(f"loaded MEMORY.md ({len(memory_index)} bytes)")
        except Exception as e:
            ui.info(f"memory load failed: {e}")

        skills_catalog: str | None = None
        try:
            from ..skills.progressive_disclosure import build_catalog

            skills_catalog = build_catalog(self.workspace) or None
            if skills_catalog:
                ui.info(f"loaded skills catalog ({len(skills_catalog)} bytes)")
        except Exception as e:
            ui.info(f"skills catalog load failed: {e}")

        return build_system_prompt(
            workspace=self.workspace,
            model=self.model,
            project_context=project_context,
            memory_index=memory_index,
            skills_catalog=skills_catalog,
            model_modelfile_system=model_system,
            goal=self.goal,
            goal_state=self.goal_state,
            board_auto_maintain=bool(getattr(self.cfg, "board_auto_maintain", False)),
            computer_use_status={
                "enabled": bool(self.cfg.computer.use_enabled),
                "mode": self.cfg.computer.permission_mode,
                "allowlist": list(self.cfg.computer.app_allowlist or []),
                "denylist": list(self.cfg.computer.app_denylist or []),
            },
            lean=self.cfg.lean_prompt,
            disabled_sections=self.cfg.disabled_prompt_sections,
        )

    def _profile_dir(self) -> Path:
        return _profile_dir(self.cfg.profile or "default")

    def _load_goal(self) -> str | None:
        """Read the persisted goal for this profile. Defensive: any read
        error returns None so a missing goal doesn't break agent startup.
        """
        try:
            from ..goal.invariant import get_goal

            return get_goal(self._profile_dir())
        except Exception:
            return None

    def _load_goal_state(self):
        """Read the T5-07 GoalState for this profile. None when no
        state file (no active loop)."""
        try:
            from ..goal.state import load_state

            return load_state(self._profile_dir())
        except Exception:
            return None

    def _configure_shell_hook_plugin(self) -> None:
        """Tell the bundled ShellHookPlugin which workspace it should consult
        for workspace-local ``settings.json`` hooks. Called from ``__init__``
        and from ``/cwd`` (after the workspace switch). Silent no-op when the
        plugin is disabled or unloaded.
        """
        try:
            for plugin in getattr(self.plugin_hooks, "plugins", []):
                if getattr(plugin, "name", "") == "shell_hook":
                    configure = getattr(plugin, "configure_workspace", None)
                    if callable(configure):
                        configure(self.workspace)
                    return
        except Exception:  # noqa: BLE001
            logger.debug("shell_hook configure_workspace failed", exc_info=True)

    def reload_skills(self) -> None:
        """Drop the skill-body cache and rebuild the system prompt in
        place so a freshly-imported / edited skill becomes visible to
        the model without a session restart. Mirrors :meth:`reload_goal`.

        Called by the ``athena skill add`` CLI's in-session companion
        (the ``/skill import`` slash) and by the filesystem watcher
        (``skills/watcher.py``) when it detects an external change.
        """
        try:
            from ..skills import loader as _skills_loader
            _skills_loader._BODY_CACHE.clear()
        except Exception:  # noqa: BLE001
            logger.debug("skill body cache invalidate failed", exc_info=True)
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0] = {
                "role": "system",
                "content": self._build_system(),
            }

    def reload_goal(self) -> None:
        """Re-read the persisted goal + state and rebuild the system
        prompt in place. Called by /goal subcommands after any
        mutation."""
        self.goal = self._load_goal()
        self.goal_state = self._load_goal_state()
        # A fresh goal resets the running token budget — last goal's
        # consumption shouldn't bleed into the new goal's cap.
        self._goal_loop_tokens_used = 0
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0] = {
                "role": "system",
                "content": self._build_system(),
            }

    def reset(self) -> None:
        """Wipe history but keep the system prompt."""
        self.messages = [{"role": "system", "content": self._build_system()}]
        self.stats = Stats()
        ui.info("conversation cleared")

    def run_turn(self, user_input: str) -> None:
        """Run one user turn to completion (model may call tools several times).

        T5-07: when an active GoalState is present, run_turn loops
        through synthetic continuation turns until the goal is
        achieved, blocked, or exhausted (turn cap OR token cap),
        or the user interrupts via Ctrl+C. Real user input always
        wins — a synthetic turn is only injected when the prior
        turn was NOT interrupted and the continuation hook says
        keep going. The /steer mechanism (drained at the top of
        each _run_turn_inner) preempts synthetic turns naturally.
        """
        from ..skills.metrics import set_active_store as _set_metrics_store
        from .checkpoints import set_active_checkpoint_manager

        with self._turn_lock:
            # Wait for any in-flight background review fork to finish
            # before we start a new foreground turn. Without this,
            # the review's child agent makes its own Ollama calls
            # concurrently with the foreground turn's calls, which
            # serializes on Ollama's single-inference-at-a-time
            # behavior and makes BOTH calls feel slow. Reviews are
            # best-effort observability — they should run when the
            # GPU is idle, never compete with the user-visible turn.
            self._wait_for_background_review(timeout=3.0)

            token = _current_agent.set(self)
            set_active_checkpoint_manager(self.checkpoint_manager)
            _set_metrics_store(self.skill_metrics_store)
            # T6-01: bind the per-session vector store on the
            # ContextVar so _persist_message's record_turn finds
            # it without explicit threading. Lazy-built once and
            # reused across run_turn calls in the same session.
            from ..recall import (
                build_vector_store as _build_vs,
                set_active_vector_store,
            )

            if not hasattr(self, "_vector_store"):
                try:
                    self._vector_store = _build_vs(
                        cfg=self.cfg, profile_dir=self._profile_dir()
                    )
                except Exception:  # noqa: BLE001
                    self._vector_store = None
            set_active_vector_store(self._vector_store)
            # Spawn the progress ticker so long turns surface as
            # periodic flashes rather than appearing hung.
            progress_stop = self._start_progress_ticker()
            try:
                current_input = user_input
                tokens_at_loop_start = (
                    self.stats.prompt_tokens + self.stats.eval_tokens
                )
                while True:
                    self._run_turn_inner(current_input)
                    next_input = self._consult_goal_continuation(
                        tokens_at_loop_start=tokens_at_loop_start,
                    )
                    if next_input is None:
                        return
                    current_input = next_input
            finally:
                progress_stop.set()
                set_active_vector_store(None)
                _set_metrics_store(None)
                set_active_checkpoint_manager(None)
                _current_agent.reset(token)

    def _consult_goal_continuation(
        self, *, tokens_at_loop_start: int
    ) -> str | None:
        """T5-07 hook called after each real assistant turn.

        Returns the synthetic prompt to inject for the next
        continuation, or None when the loop should stop. Handles
        the four stop conditions:

          interrupted     Ctrl+C anywhere → pause + return None
          token cap       loop tokens > goal_max_tokens → exhaust
          turn cap        turns_taken >= max_turns → exhausted
          sentinel        GOAL ACHIEVED → achieved
                          GOAL BLOCKED → paused + surface reason

        The returned synthetic prompt is the continuation nudge —
        run_turn will pass it to _run_turn_inner as the next
        "user" message.
        """
        if self.goal_state is None:
            return None

        # Interrupt wins over every continuation decision. A user
        # who hit Ctrl+C does not want another synthetic turn.
        if self._last_turn_interrupted:
            self.goal_state.status = "paused"
            self._persist_goal_state()
            ui.warn(
                "goal paused (interrupt detected) — /goal resume to continue"
            )
            return None

        # Token-cap check. The cap counts tokens consumed since
        # run_turn entered THIS loop (so /goal set + user turn
        # don't pre-consume the budget).
        used_this_loop = (
            self.stats.prompt_tokens + self.stats.eval_tokens
        ) - tokens_at_loop_start
        self._goal_loop_tokens_used = used_this_loop
        token_cap = int(getattr(self.cfg, "goal_max_tokens", 200_000))
        if token_cap > 0 and used_this_loop > token_cap:
            self.goal_state.status = "exhausted"
            self._persist_goal_state()
            ui.warn(
                f"goal exhausted (token cap {token_cap} exceeded — "
                f"{used_this_loop} used). "
                "/goal resume grants more, /goal status, or /goal clear."
            )
            return None

        from ..goal.loop import maybe_continue_goal_after_turn

        decision = maybe_continue_goal_after_turn(
            profile_dir=self._profile_dir(),
            state=self.goal_state,
            last_assistant_text=self._last_assistant_text,
            cfg=self.cfg,
        )
        if decision.should_continue:
            ui.info(
                f"[goal] continuing "
                f"(turn {self.goal_state.turns_taken}/"
                f"{self.goal_state.max_turns})"
            )
            return decision.synthetic_prompt

        # Stop. Announce the reason.
        if decision.stop_reason == "achieved":
            # Distinguish "verified achievement" (verifier ran + passed)
            # from "self-declared achievement" (no verifier configured —
            # model said done, we believed it). This matters because a
            # silent "Goal achieved" with no verifier looks identical to
            # a properly-checked completion, masking the gap.
            verifier_configured = bool(
                getattr(self.cfg, "goal_verifier_command", None)
            )
            if verifier_configured:
                ui.console.print(
                    f"[bold green]Goal achieved[/] in "
                    f"{self.goal_state.turns_taken} turn(s) "
                    "[dim](verifier passed)[/]"
                )
            else:
                ui.console.print(
                    f"[bold green]Goal achieved[/] in "
                    f"{self.goal_state.turns_taken} turn(s) "
                    "[yellow](self-declared; no verifier configured — "
                    "set cfg.goal_verifier_command to gate this)[/]"
                )
        elif decision.stop_reason == "blocked":
            ui.warn(
                f"goal blocked: {decision.blocked_reason}. "
                "/goal resume when ready."
            )
        elif decision.stop_reason == "exhausted":
            ui.warn(
                f"goal not completed after {self.goal_state.max_turns} "
                "turn(s). /goal resume (grants more), /goal status, "
                "or /goal clear."
            )
        # Other stop_reasons (paused, no_state, disabled) are silent —
        # the user either set them themselves (paused) or the loop
        # isn't engaged (no_state, disabled).
        return None

    def _persist_goal_state(self) -> None:
        """Best-effort write of self.goal_state. A disk error is
        logged but never raised — the loop is already mid-stop."""
        if self.goal_state is None:
            return
        try:
            from ..goal.state import save_state

            save_state(self._profile_dir(), self.goal_state)
        except Exception:  # noqa: BLE001
            import logging as _logging

            _logging.getLogger(__name__).debug(
                "could not persist goal state on stop", exc_info=True
            )

    def _run_turn_inner(self, user_input: str) -> None:
        # Clear any stale cancel flag so a True left from a previous
        # turn doesn't immediately abort this one.
        self.cancel_pending = False
        # T5-07: per-turn tracking the continuation loop in run_turn
        # consults after this method returns. Reset on entry.
        self._last_assistant_text = ""
        self._last_turn_interrupted = False
        # Per-plugin veto on the user prompt. The first plugin to return
        # (False, reason) cancels the turn. The bundled ShellHookPlugin
        # bridges the settings.json UserPromptSubmit hook into this
        # check, so existing user configs keep working without going
        # through the legacy athena.hooks path.
        allow, msg = self.plugin_hooks.check_user_message(user_input)
        if not allow:
            ui.error(f"prompt cancelled by plugin: {msg}")
            return
        # Plugin chain: each plugin sees the output of the prior one. A
        # plugin returning None is a pass-through. The chained result is
        # what lands in history and goes to the model.
        user_input = self.plugin_hooks.on_user_message(user_input)
        # Drain any pending /steer messages BEFORE the user prompt so the
        # model sees in-flight redirects first. Each steer becomes its own
        # synthetic user message; the actual prompt follows.
        self._inject_pending_steers()
        user_msg = {"role": "user", "content": user_input}
        self.messages.append(user_msg)
        self._persist_message(user_msg)
        self.stats.turns += 1

        # Loop until the model produces a final assistant message with no tool calls.
        max_steps = max(1, int(self.cfg.max_turn_steps))
        for step in range(max_steps):
            # T2-04: check token watermark before each provider call.
            # The compressor is a no-op when below threshold; when
            # above, it replaces self.messages with [head, summary, tail].
            self._maybe_compress_context()
            # External cancel check (ACP session/cancel sets this).
            # Honored between tool rounds — the in-flight stream
            # itself completes naturally, but no further rounds spawn.
            if self.cancel_pending:
                ui.info("turn cancelled by external request")
                self.messages.append(
                    {
                        "role": "user",
                        "content": "[turn cancelled by the user]",
                    }
                )
                self._fire_stop("cancelled")
                return
            assistant_text, tool_calls, raw_done = self._stream_one(tool_call_round=step)
            interrupted = bool(raw_done and raw_done.get("_interrupted"))

            # Track usage if the provider reported it (skip phantom raw on
            # interrupt). Accept both Ollama-flavoured field names
            # (prompt_eval_count / eval_count) and the OpenAI-style names
            # used by every hosted provider's usage chunk
            # (prompt_tokens / completion_tokens) so cross-provider token
            # accounting keeps working without per-provider branching here.
            if raw_done and not interrupted:
                self.stats.prompt_tokens += (
                    raw_done.get("prompt_eval_count") or raw_done.get("prompt_tokens") or 0
                )
                self.stats.eval_tokens += (
                    raw_done.get("eval_count") or raw_done.get("completion_tokens") or 0
                )
                # Anthropic prompt-cache counters (T2-01).
                self.stats.cache_read_tokens += raw_done.get("cache_read_input_tokens") or 0
                self.stats.cache_creation_tokens += raw_done.get("cache_creation_input_tokens") or 0

            # Record the assistant message (with tool_calls if any) into history
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": assistant_text}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            self.messages.append(assistant_msg)
            self._persist_message(assistant_msg)

            if interrupted:
                # T5-07: signal interrupt to the continuation loop in
                # run_turn so it pauses the goal instead of injecting
                # another synthetic turn.
                self._last_turn_interrupted = True
                # The stream was cut mid-flight. If the model had emitted tool_calls
                # before the interrupt, mark them DENIED so the next turn doesn't
                # see dangling calls. Then leave a marker so the model knows.
                for call in tool_calls or []:
                    fname = (call.get("function") or {}).get("name", "?")
                    self._record_tool_result(
                        call, fname, "DENIED: response interrupted by user (Ctrl+C)"
                    )
                self.messages.append(
                    {
                        "role": "user",
                        "content": "[previous response was interrupted by the user]",
                    }
                )
                # No Stop hook — the turn didn't complete.
                return

            if not tool_calls:
                # Plugin observation — fire on the final assistant message
                # only (intermediate tool-calling rounds aren't surfaced).
                if assistant_text:
                    self.plugin_hooks.on_assistant_message(assistant_text)
                self._fire_stop("completed")
                self._maybe_fire_review()
                # T5-07: surface the final assistant text for the
                # continuation hook in run_turn.
                self._last_assistant_text = assistant_text or ""
                return

            # Execute each tool call and append a tool message for it.
            # If the user interrupts mid-loop, mark unexecuted calls DENIED so
            # the assistant message's tool_calls are all paired with replies.
            ui.tool_round_header()
            asst_idx = len(self.messages) - 1
            try:
                for call in tool_calls:
                    self._handle_tool_call(call)
            except KeyboardInterrupt:
                self._last_turn_interrupted = True
                ui.warn("interrupted during tool execution")
                # Count is robust to interrupts firing anywhere in the loop body.
                recorded = sum(1 for m in self.messages[asst_idx + 1 :] if m.get("role") == "tool")
                for missing in tool_calls[recorded:]:
                    fname = (missing.get("function") or {}).get("name", "?")
                    self._record_tool_result(
                        missing, fname, "DENIED: tool execution interrupted by user (Ctrl+C)"
                    )
                self.messages.append(
                    {
                        "role": "user",
                        "content": "[previous tool execution was interrupted by the user]",
                    }
                )
                return

        ui.warn(f"reached step limit ({max_steps}); stopping for safety.")
        self._fire_stop("step_limit")

    def _wait_for_background_review(self, *, timeout: float = 3.0) -> None:
        """Block at most ``timeout`` seconds for an in-flight background-review
        thread before starting the foreground turn. No-op when no review
        is in flight.

        Past the timeout, surface a visible status hint and proceed.
        The review keeps running on its daemon thread; on local Ollama
        it'll briefly serialize with the foreground call, which is far
        better than making the user wait indefinitely.
        """
        t = self._active_review_thread
        if t is None or not t.is_alive():
            return
        import time as _time
        t0 = _time.monotonic()
        t.join(timeout=timeout)
        elapsed = _time.monotonic() - t0
        if t.is_alive():
            try:
                ui.info(
                    f"background review still running after {elapsed:.1f}s; "
                    f"proceeding (review will finish in background)"
                )
            except Exception:
                pass

    def _maybe_fire_review(self) -> None:
        """Hand off to the per-turn review orchestrator. Background reviews
        run on a daemon thread and never block this method."""
        from ..provenance import is_background

        # Don't recursively spawn reviews from inside background forks.
        if is_background():
            return
        # Skip if the previous review is still running. Stacking review
        # threads (one per turn boundary) compounds httpx connection
        # pressure and races for provider rate limits against the
        # foreground turn. The nudge counter still increments, so the
        # next idle boundary will trigger a fresh review.
        prior = self._active_review_thread
        if prior is not None and prior.is_alive():
            return
        try:
            from ..review.orchestrator import maybe_fire_review

            fired = maybe_fire_review(self)
            if fired is not None:
                self.stats.review_fired_count += 1
                # Record the thread on the agent so the next
                # run_turn can wait for it before competing for
                # Ollama. Without this the review's child agent
                # fights the next foreground turn for GPU time.
                self._active_review_thread = fired
        except Exception:
            # The review path must never break a foreground turn.
            ui.info("background review failed to fire (logged)")

    def _start_progress_ticker(self) -> threading.Event:
        """Spawn a daemon thread that emits a status.flash every
        ~30s if the turn hasn\'t finished. Returns the stop event;
        caller sets it in the run_turn finally block to terminate.

        The flash text shows tool-call count and elapsed time so
        the user sees ongoing progress even when the model is
        between tool calls and not streaming. Without this, long
        local-model turns look indistinguishable from a hang
        (caught during step-12 visual testing).
        """
        stop = threading.Event()
        start_at = time.monotonic()
        tools_at_start = self.stats.tool_calls

        def _tick() -> None:
            # Wait 30s before first flash so short turns don't flash at all.
            while not stop.wait(timeout=30.0):
                elapsed = int(time.monotonic() - start_at)
                tools_this_turn = self.stats.tool_calls - tools_at_start
                msg = (
                    f"still working — {tools_this_turn} tool call(s), "
                    f"{elapsed}s elapsed"
                )
                try:
                    ui._emit_flash("info", msg)
                except Exception:  # noqa: BLE001
                    # Flash is informational; never break the turn.
                    pass

        threading.Thread(
            target=_tick, name="athena-progress-ticker", daemon=True,
        ).start()
        return stop

    def _fire_stop(self, reason: str) -> None:
        stats = {
            "turns": self.stats.turns,
            "tool_calls": self.stats.tool_calls,
            "prompt_tokens": self.stats.prompt_tokens,
            "eval_tokens": self.stats.eval_tokens,
        }
        # Per-turn end-of-turn hook. The bundled ShellHookPlugin
        # bridges the settings.json Stop event into this dispatch.
        try:
            self.plugin_hooks.on_turn_end(reason, stats)
        except Exception:  # noqa: BLE001
            logger.debug("plugin on_turn_end raised", exc_info=True)
        # Phase 16: refresh the on-disk status snapshot so
        # ``athena status`` (running in another terminal) sees the
        # post-turn counters.
        try:
            self.write_status_snapshot()
        except Exception:
            # Status snapshot is observability, not correctness — a
            # failed write must never break the turn.
            pass

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

    def _stream_one(
        self, tool_call_round: int = 0
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
        """One model turn. Streams text to stdout, returns (text, tool_calls, usage).

        ``tool_call_round`` is the iteration index inside the current
        user turn (0 = first stream, 1 = after one round of tool calls,
        etc.) — passed through to the parseltongue param policy so
        rules like "drop temperature when we're deep in a tool chain"
        have something to fire on.

        ``usage`` is the Ollama-flavored dict the caller already knows how to
        read — ``prompt_eval_count`` / ``eval_count`` / ``eval_duration`` for
        Ollama; the same keys with zeros (and tokens from the provider's
        ``usage`` chunk) for other providers.
        """
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        usage: dict[str, Any] | None = None

        # Spinner during the silent first-token wait (partial-offload models can
        # take 5-30s before the first chunk). Stop it the moment any chunk lands.
        status = ui.console.status("[dim]thinking…[/]", spinner="dots")
        status.start()
        first = True
        # Render streamed text via the typewriter helper so we can swap
        # to a Rich.Markdown view at the end without polluting the
        # terminal with both the plain stream and the rendered copy.
        typewriter = ui.TypewriterStream(prefix="▌ ", prefix_style="bold #00ff00")
        msgs_to_send = self._messages_with_cache_markers()
        tool_schemas = tools.ollama_schema(
            enabled_toolsets=self.cfg.enabled_toolsets,
            disabled=self.cfg.disabled_tools,
        )
        # Parseltongue: ask the policy for this turn's inference params.
        # The policy returns a dict that goes into stream_chat as kwargs;
        # the provider filters to whichever options it actually accepts.
        policy_input = PolicyInput(
            messages=msgs_to_send,
            tools_available=[
                (t.get("function") or {}).get("name", "")
                for t in (tool_schemas or [])
                if isinstance(t, dict)
            ],
            tool_calls_so_far=tool_call_round,
        )
        policy_params = self._param_policy.params_for(policy_input)
        try:
            for chunk in self.provider.stream_chat(
                model=self.model,
                messages=msgs_to_send,
                tools=tool_schemas,
                num_ctx=self.cfg.context_window,
                **policy_params,
            ):
                if first and chunk.kind in ("content", "tool_call"):
                    status.stop()
                    if chunk.kind == "content":
                        typewriter.start()
                    first = False
                if chunk.kind == "content":
                    text = chunk.payload or ""
                    if text:
                        typewriter.feed(text)
                        text_parts.append(text)
                elif chunk.kind == "tool_call":
                    # Stream cuts to a tool call — finalize the
                    # typewriter on whatever text accumulated so the
                    # tool-call summary panel renders on a fresh line.
                    typewriter.finalize(markdown=False)
                    p = chunk.payload or {}
                    tool_calls.append(
                        {
                            "function": {
                                "name": p.get("name", ""),
                                "arguments": p.get("arguments", {}),
                            },
                            **({"id": p["id"]} if p.get("id") else {}),
                        }
                    )
                elif chunk.kind == "usage":
                    usage = dict(chunk.payload or {})
                # "end" chunk is informational; loop falls through naturally.
        except KeyboardInterrupt:
            if first:
                status.stop()
            typewriter.finalize(markdown=False)
            ui.warn("interrupted")
            # Signal interruption to run_turn via a sentinel on the usage dict.
            return "".join(text_parts), tool_calls, {"_interrupted": True}
        except Exception as e:
            if first:
                status.stop()
            typewriter.finalize(markdown=False)
            ui.error(f"provider error: {e}")
            return "".join(text_parts), [], None
        finally:
            # Tool-only or empty responses never trip the in-loop stop().
            if first:
                status.stop()
        # Final render — Markdown when the assembled text looks like
        # it'd benefit (code blocks, headings, lists). Plain text
        # responses re-render as plain.
        typewriter.finalize(markdown=True)
        # ``ui.stream_stats`` (per-turn token+throughput footer)
        # was removed during the UI cleanup — the Ink TUI's
        # bottom StatusBar already shows model/tokens/elapsed
        # continuously, so a per-turn footer was redundant.
        text = "".join(text_parts)
        # Recovery: if the model emitted tool-call JSON as content instead of
        # using the provider's native tool_calls field, parse it out and treat
        # as tool calls. Phase 9 routes this through the provider's
        # parse_tool_calls (which dispatches to the per-(provider, model)
        # parser registry); if that returns nothing, fall back to the in-agent
        # generic recovery for older patterns.
        if not tool_calls and text.strip():
            recovered_calls = self._recover_tool_calls_from_text(text)
            if recovered_calls:
                tool_calls = recovered_calls[0]
                text = recovered_calls[1]
                ui.info(f"recovered {len(tool_calls)} tool call(s) from content")
        return text, tool_calls, usage

    def _recover_tool_calls_from_text(self, text: str) -> tuple[list[dict[str, Any]], str] | None:
        """Try the per-(provider, model) parser registry first; if it
        returns no tool calls, fall through to the in-agent generic
        recovery. Returns (canonical_tool_calls, residual_content) on hit,
        or None if no recovery was possible.
        """
        try:
            cleaned, calls = self.provider.parse_tool_calls(text, {"model": self.model})
            if calls:
                normalized = [
                    {
                        "function": {
                            "name": c.get("name", ""),
                            "arguments": c.get("arguments", {}),
                        },
                        **({"id": c["id"]} if c.get("id") else {}),
                    }
                    for c in calls
                ]
                return normalized, cleaned
        except Exception:
            ui.info("provider parse_tool_calls raised; falling back to generic recovery")

        residual, recovered = _extract_text_tool_calls(text)
        if recovered:
            return recovered, residual
        return None

    def _handle_tool_call(self, call: dict[str, Any]) -> None:
        fn = call.get("function", {}) or {}
        name = fn.get("name", "")
        args_raw = fn.get("arguments", {})
        # Ollama may give us a dict or a JSON string depending on model
        if isinstance(args_raw, str):
            stripped = args_raw.strip()
            if not stripped:
                args = {}
            else:
                # T2-05: route through the JSON sanitiser before the
                # raw json.loads. Recovers smart quotes / single quotes
                # / trailing commas / unquoted keys without speculating
                # about missing values. Gated by cfg.tool_call_sanitize.
                to_parse = stripped
                if getattr(self.cfg, "tool_call_sanitize", True):
                    from ..providers.schema_sanitizer import sanitize_tool_call_args

                    sanitized, fixes = sanitize_tool_call_args(stripped, tool_name=name)
                    if sanitized is not None:
                        if fixes:
                            ui.info(f"sanitised tool-call args for {name}: {', '.join(fixes)}")
                        to_parse = sanitized
                try:
                    args = json.loads(to_parse)
                except json.JSONDecodeError:
                    args = {}
        else:
            args = args_raw or {}

        ui.tool_call_summary(name, args)
        self.stats.record_tool_call(name)

        # Plan-mode gate: only read-only tools are allowed
        from ..tools import plan as plan_mod

        if plan_mod.is_plan_mode() and name not in plan_mod.PLAN_MODE_ALLOWED:
            denied = (
                f"BLOCKED: tool {name!r} is not allowed in plan mode. "
                "Use Read/Glob/Grep/WebFetch/WebSearch to investigate, then "
                "call ExitPlanMode with the proposed plan."
            )
            self._record_tool_result(call, name, denied)
            ui.warn(denied)
            return

        t = tools.get_tool(name)
        # Confirmation gate for destructive tools.
        # For Bash, an allowlist short-circuits the prompt.
        if t and t.requires_confirmation and not self.cfg.auto_approve_tools:
            allowed = False
            if name in ("Bash", "bash"):
                from ..safety.shell_policy import DEFAULT_DENYLIST, ShellPolicy

                cmd = (args.get("command") or "").strip()
                # Word-boundary match via ShellPolicy: prefix "ls"
                # must not allow "lsof"; "git" must not allow "gitleaks".
                bash_cfg = self.cfg.bash
                deny = tuple(DEFAULT_DENYLIST) + tuple(bash_cfg.extra_denylist or ())
                policy = ShellPolicy(bash_cfg.allowlist, deny)
                allowed = policy.evaluate(cmd).allowed
            if not allowed:
                preview = args.get("command") or json.dumps(args)
                ui.console.print(f"[yellow]command:[/] [white]{preview}[/]")
                if get_approval_callback()(name, args) != "allow":
                    result = "DENIED by user"
                    self._record_tool_result(call, name, result)
                    return

        # Plugin veto: first plugin to return False from pre_tool_call
        # blocks. ShellHookPlugin bridges settings.json PreToolUse hooks
        # into this path so existing user configs keep working.
        plugin_allow, blocker = self.plugin_hooks.pre_tool_call(name, args)
        if not plugin_allow:
            blocked = f"BLOCKED by plugin {blocker!r}"
            self._record_tool_result(call, name, blocked)
            ui.warn(blocked)
            return

        # Show diffs for Write/write_file before they happen
        if name in ("Write", "write_file"):
            self._preview_write(args)

        result = tools.dispatch(name, args)
        ui.tool_result(name, result)

        # Plugin observation; cannot affect control flow. ShellHookPlugin
        # bridges settings.json PostToolUse hooks here.
        self.plugin_hooks.post_tool_call(name, args, result)

        # T2-06: out-of-band storage for large tool outputs. The
        # original `result` is still passed to the hooks above (so
        # observers see the raw text); only the message stored in
        # conversation history is replaced with the handle.
        result = self._maybe_store_tool_result(name, result)
        self._record_tool_result(call, name, result)

    def _maybe_store_tool_result(self, tool_name: str, result: str) -> str:
        """T2-06: if the tool result exceeds the configured threshold,
        persist it to a content-addressed blob and return the short
        reference handle. Below threshold passes through unchanged.
        """
        storage = getattr(self, "tool_result_storage", None)
        if storage is None:
            return result
        threshold = getattr(self.cfg, "tool_result_threshold_bytes", 1_000_000)
        if not isinstance(result, str):
            return result
        from ..tools.tool_result_storage import maybe_store_result

        return maybe_store_result(
            content=result,
            tool_name=tool_name,
            threshold_bytes=threshold,
            storage=storage,
        )

    def _preview_write(self, args: dict[str, Any]) -> None:
        # Accept both Claude-Code-style file_path/content and athena-style path/content
        path = args.get("file_path") or args.get("path")
        new = args.get("content", "")
        if not path:
            return
        target = (self.workspace / path) if not Path(path).is_absolute() else Path(path)
        old = ""
        if target.exists() and target.is_file():
            try:
                old = target.read_text(encoding="utf-8")
            except OSError:
                pass
        ui.show_diff(path, old, new)

    def _record_tool_result(self, call: dict[str, Any], name: str, result: str) -> None:
        msg: dict[str, Any] = {"role": "tool", "name": name, "content": result}
        # Some Ollama models send a tool_call_id; preserve when present
        if "id" in call:
            msg["tool_call_id"] = call["id"]
        self.messages.append(msg)
        self._persist_message(msg)

    def _inject_pending_steers(self) -> None:
        """Drain any pending /steer messages and append them as synthetic
        user messages before the next prompt. Steers are delivered in
        FIFO order.
        """
        if self.session_id is None:
            return
        from ..steer.queue import GLOBAL_STEER_QUEUE

        steers = GLOBAL_STEER_QUEUE.drain(self.session_id)
        for steer in steers:
            steer_msg = {"role": "user", "content": f"[/steer] {steer}"}
            self.messages.append(steer_msg)
            self._persist_message(steer_msg)

    def _persist_message(self, message: dict[str, Any]) -> None:
        """Append the message to the session store if one is active.

        Strips any Anthropic ``cache_control`` markers before writing —
        the current call path never plants them in ``self.messages``
        (they're applied to a deepcopy in ``_messages_with_cache_markers``)
        but the strip makes the invariant explicit and prevents a
        future regression from polluting the JSONL.
        """
        if self.session_store is None or self.session_id is None:
            return
        from .prompt_caching import strip_cache_markers

        clean = strip_cache_markers([message])[0]
        try:
            self.session_store.append_turn(self.session_id, clean)
        except Exception as e:  # pragma: no cover — defensive
            ui.info(f"session append failed (continuing): {e}")
            return

        # T6-01: incremental embedding for semantic recall. Best
        # effort — a recall-side failure must never block a
        # session write. The active vector store comes from the
        # recall ContextVar bound in run_turn (similar to T3-03's
        # checkpoint manager pattern).
        try:
            from ..recall import record_turn

            # turn_index = current length minus the just-appended
            # message (so this turn's persisted offset matches the
            # JSONL line count after append).
            turn_index = max(0, len(self.messages) - 1)
            record_turn(
                session_id=self.session_id,
                turn_index=turn_index,
                role=str(clean.get("role", "")),
                content=clean.get("content", ""),
                workspace=str(self.workspace),
            )
        except Exception:  # noqa: BLE001
            import logging as _logging

            _logging.getLogger(__name__).debug(
                "record_turn failed", exc_info=True
            )

    def _maybe_compress_context(self) -> None:
        """T2-04: compress ``self.messages`` if total tokens exceed
        the configured watermark. No-op when below threshold or when
        the head + tail already span the entire context (nothing in
        the middle to summarise).

        When compression runs, the synthetic summary message is
        persisted to the session JSONL so a resumed session sees the
        same compressed shape.
        """
        from .context_compressor import CompressionConfig, compress, should_compress

        cfg = CompressionConfig(
            model_context_window=self.cfg.context_window,
            watermark=self.cfg.context_compress_watermark,
            tail_protection_ratio=self.cfg.tail_protection_ratio,
            tool_output_prune_tokens=self.cfg.tool_output_prune_tokens,
            summary_budget_ratio=self.cfg.summary_budget_ratio,
            summary_budget_cap_tokens=self.cfg.summary_budget_cap_tokens,
            head_message_indices=1,
        )
        if not should_compress(self.messages, cfg):
            return

        def _summarizer(prompt_messages: list[dict[str, Any]], target_tokens: int) -> str:
            chunks: list[str] = []
            for chunk in self.provider.stream_chat(
                model=self.model,
                messages=prompt_messages,
                tools=None,
                max_tokens=target_tokens,
                num_ctx=self.cfg.context_window,
            ):
                if chunk.kind == "content":
                    payload = chunk.payload or ""
                    if isinstance(payload, str):
                        chunks.append(payload)
            return "".join(chunks)

        result = compress(self.messages, summarizer=_summarizer, cfg=cfg)
        if result.middle_message_count == 0:
            return
        ui.info(
            f"context compressed: {result.tokens_before:,} → "
            f"{result.tokens_after:,} tokens "
            f"({100 * (1 - result.compression_ratio):.0f}% reduction; "
            f"{result.middle_message_count} messages folded)"
        )
        self.messages = result.new_messages
        # Persist the synthetic summary (the new messages[1]) so a
        # resumed session sees the compressed shape rather than
        # re-replaying the original middle.
        if len(result.new_messages) > 1:
            self._persist_message(result.new_messages[1])

    def _messages_with_cache_markers(self) -> list[dict[str, Any]]:
        """Return ``self.messages`` with cache_control markers if the
        active provider has declared support for Anthropic-shape
        ``cache_control`` markers and caching is enabled in
        ``cfg.cache_strategy``. Pure copy — does not mutate
        ``self.messages``.

        Whether the provider wants markers is read from
        :attr:`Capabilities.anthropic_cache_markers` rather than a
        hardcoded provider-name allowlist; that lets new providers
        opt in by setting the capability instead of editing this
        method. Providers whose prompt caching is automatic (OpenAI
        server-side prefix detection) declare ``prompt_caching=True``
        without the marker flag and get this method as a no-op.
        """
        strategy = getattr(self.cfg, "cache_strategy", "none")
        if strategy == "none":
            return self.messages
        try:
            caps = self.provider.capabilities(self.model)
        except Exception:
            return self.messages
        if not getattr(caps, "anthropic_cache_markers", False):
            return self.messages
        from .prompt_caching import apply_cache_markers

        provider_name = getattr(self.provider, "name", "")
        return apply_cache_markers(
            self.messages,
            strategy=strategy,  # type: ignore[arg-type]
            ttl=getattr(self.cfg, "prompt_cache_ttl", "5m"),  # type: ignore[arg-type]
            native_anthropic=(provider_name == "anthropic"),
        )

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

    def run_until_done(self, user_prompt: str = "", *, max_iterations: int | None = None) -> None:
        """Run a single user turn to completion (loops internally over tool
        rounds). ``max_iterations``, when given, overrides ``cfg.max_turn_steps``
        for this call only — used by ``Agent.fork`` to cap fork loop length."""
        if max_iterations is not None:
            saved = self.cfg.max_turn_steps
            self.cfg.max_turn_steps = max_iterations
            try:
                self.run_turn(user_prompt)
            finally:
                self.cfg.max_turn_steps = saved
        else:
            self.run_turn(user_prompt)

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
