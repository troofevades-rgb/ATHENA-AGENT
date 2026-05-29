"""Lifecycle mixin for :class:`~athena.agent.core.Agent`.

R1 stage 2 of the inheritance split. Owns the agent-startup helpers
that the plan groups under "lifecycle":

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

``__init__`` and ``close`` are intentionally still on
:class:`~athena.agent.core.Agent` -- those are the riskiest moves
(ContextVar setup, plugin teardown ordering) and get pulled in R1
stage 3 once the suite around the smaller helpers is comfortable.

The mixin reaches into roughly two dozen attributes on ``self`` --
all populated by :meth:`Agent.__init__`. The TYPE_CHECKING block
documents the contract.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import ui
from ..config import profile_dir as _profile_dir
from ..plugins.hooks import HookDispatcher
from ..prompts import build_system_prompt

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..cache import CacheEntry
    from ..config import Config
    from ..goal.state import GoalState
    from ..providers import Provider

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
        # Deferred import to avoid the core -> lifecycle -> core cycle.
        # ``Stats`` lives in core.py until R1 stage 3 hollows core out.
        from .core import Stats

        self.messages = [{"role": "system", "content": self._build_system()}]
        self.stats = Stats()
        ui.info("conversation cleared")
