"""Lifecycle mixin for :class:`~athena.agent.core.Agent`.

R1 stages 2 + 4 of the inheritance split. Owns every method tied
to the agent's setup and teardown:

  * :meth:`__init__` -- the dense construction path: provider
    routing, session-store wiring, plugin discovery, browser
    binding, cancel-hook registration, skill watcher kickoff
    (R1 stage 4)
  * :meth:`close` -- mirror teardown: cancel-hook deregistration,
    plugin lifecycle end, browser shutdown (R1 stage 4)
  * Plugin discovery + dispatcher build (:meth:`_build_plugin_hooks`)
  * Session-start lifecycle / curator spawn
    (:meth:`_run_session_start_hooks`)
  * Cross-session prefix cache wiring (:meth:`_init_cross_session_cache`)
  * System-prompt build (:meth:`_build_system`) + the in-place
    reload helpers (:meth:`reload_skills`, :meth:`reload_goal`,
    :meth:`reset`)
  * Goal load + profile dir resolution
  * Cancel-in-flight hook
  * Shell-hook plugin workspace configuration

Every method is still on the public :class:`Agent` surface via
the mixin -- callers (gateway, CLI, tests) keep using
``Agent(...)`` and ``agent.close()`` unchanged.

The mixin reaches into roughly two dozen attributes on ``self`` --
all populated by :meth:`__init__`. The TYPE_CHECKING block
documents the contract.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import tools, ui
from ..config import Config
from ..config import profile_dir as _profile_dir
from ..plugins.hooks import HookDispatcher
from ..prompts import build_system_prompt
from ..providers import Provider
from ..providers.credential_pool import global_pool as _global_pool
from ..providers.runtime_resolver import resolve_provider
from ..sessions.store import SessionMeta, SessionStore, new_session_id
from .param_policy import ParamPolicy, policy_from_config
from .stats import Stats

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..cache import CacheEntry
    from ..goal.state import GoalState

logger = logging.getLogger(__name__)

_MAX_DOCUMENT_BYTES = 32_000


class AgentLifecycle:
    """Mixin providing lifecycle helpers for :class:`Agent`.

    Expects the concrete :class:`Agent` to populate (via its
    ``__init__``) these attributes the mixin reads or mutates:

      * ``self.cfg`` -- :class:`~athena.config.Config`
      * ``self.workspace`` -- :class:`pathlib.Path`
      * ``self.model`` -- ``str``
      * ``self.provider`` -- :class:`~athena.providers.Provider`
      * ``self.messages`` -- ``list[dict[str, Any]]``
      * ``self.stats`` -- :class:`Stats`
      * ``self.session_id`` -- ``str | None``
      * ``self.goal`` -- ``str | None``
      * ``self.goal_state`` -- :class:`GoalState | None`
      * ``self._goal_loop_tokens_used`` -- ``int``
      * ``self.plugin_hooks`` -- :class:`HookDispatcher`
      * ``self.cross_session_cache_entry`` -- ``CacheEntry | None``
      * ``self._model_system_cache`` -- ``dict[str, str]``
    """

    if TYPE_CHECKING:  # pragma: no cover - typing only
        cfg: Config
        workspace: Path
        model: str
        provider: Provider
        messages: list[dict[str, Any]]
        session_id: str | None
        goal: str | None
        goal_state: GoalState | None
        plugin_hooks: HookDispatcher
        cross_session_cache_entry: CacheEntry | None
        _model_system_cache: dict[str, str]
        _goal_loop_tokens_used: int

    def _cancel_in_flight(self) -> None:
        """Force an in-flight LLM HTTP stream to abort. Called from
        the gateway reader thread on InterruptCommand. MUST NOT
        raise -- the cancel-hook dispatcher catches but logs noisily.

        Preferred path: ``provider.abort_current_stream()`` -- closes
        just the current Response so the Client stays alive for the
        next request. All hosted providers (openai/anthropic/ollama)
        expose this.

        Fallback: close the whole Client (older providers without
        the abort method) -- they'll need to rebuild lazily.
        """
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
        # test and race for the same Ollama inference queue --
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
        """T5-06 -- at session start, look up the cross-session
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
            profile = self.cfg.profile or "default"
            idx_path = _profile_dir(profile) / "cache_index.json"

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
            logger.info(
                "cross-session cache HIT for %s/%s (mode=%s, age=%ds)",
                workspace,
                provider_name,
                plan.mode,
                int(time.time() - hit.created_at),
            )
            return

        # Miss -> record the new entry. provider_cache_id is None
        # because the provider's server-side cache id (if any)
        # isn't observable from athena's side -- that's the
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
        logger.info(
            "cross-session cache MISS for %s/%s -- recorded (mode=%s, ttl=%ds)",
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
        # A fresh goal resets the running token budget -- last goal's
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
