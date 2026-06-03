"""Configuration section dataclasses.

Extracted from ``athena/config.py`` (2026-06-03 consolidation pass): the
per-feature config section schemas (``SkillsConfig`` … ``GatewayConfig``)
that the top-level ``Config`` aggregates. Pure data definitions with no
dependency on config.py's constants, loader, or deprecation logic, so they
live here to keep ``config.py`` focused on ``Config`` + loading. Re-exported
from ``athena.config`` — ``from athena.config import SkillsConfig`` still works.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any


@dataclass
class SkillsConfig:
    """Skills subsystem config.

    Pilot for the Phase 18.1 R4 nested-config migration: the legacy
    ``cfg.skills_autoload`` + ``cfg.skills_autoload_interval`` flat
    fields are still accessible via ``Config.__getattr__`` shims that
    emit a ``DeprecationWarning`` and resolve through this nested
    instance. New code should read ``cfg.skills.autoload`` directly.
    """

    # When True, the Agent runs a polling watcher over the skill search
    # paths and reloads the catalog in place whenever a SKILL.md is
    # added, edited, or removed. OFF by default to avoid a per-session
    # background thread for users who never edit skills mid-session.
    autoload: bool = False
    # Poll interval (seconds) for the skill watcher when ``autoload`` is
    # True. Default tuned low enough to feel interactive but high enough
    # that the watch loop is invisible in profilers.
    autoload_interval: float = 2.0


@dataclass
class SafetyConfig:
    """Snapshot + audit retention policy + mutation-snapshot behaviour.

    Phase 18.1 R4 stage 2: replaces the ``cfg.safety: dict[str, Any]``
    blob whose keys were advertised in code but never actually consulted
    (verified by grep: zero readers). This commit also threads the
    dataclass through to :class:`~athena.safety.snapshots.SnapshotStore`
    so the user's ``[safety]`` TOML table finally takes effect.

    Defaults match the prior dict exactly (no behaviour change for
    users on factory settings).
    """

    # When True, also snapshot mutations made under
    # write_origin="foreground" -- not just background_review / curator /
    # migration. False by default because foreground writes are
    # user-driven and undo is already a user-driven question; the
    # snapshot/audit chain mainly exists for autonomous mutations.
    snapshot_foreground: bool = False
    # Retention policy. The store's prune() pass deletes snapshots older
    # than retention_days, beyond retention_count, or in excess of
    # retention_bytes total on disk -- whichever fires first. Pinned
    # snapshots bypass every rule.
    retention_days: int = 90
    retention_count: int = 5_000
    retention_bytes: int = 5 * 1024**3
    # Note: bash denylist patterns live in BashConfig.extra_denylist.
    # The legacy cfg.safety["extra_denylist"] key was a duplicate that
    # nobody read; dropped here to avoid the parallel-keys footgun.


@dataclass
class OcrConfig:
    """OCR subsystem (Tesseract by default, capability-brokered).

    Phase 18.1 R4 stage 5: promotes the five ``ocr_*`` flat fields.
    Legacy reads/writes still resolve through the Config shim.
    """

    enabled: bool = True
    backend_prefer: str = "local"
    # ISO 639-2/T language codes -- tesseract joins with '+'. Each
    # non-default language needs the matching tessdata file installed.
    languages: list[str] = field(default_factory=lambda: ["eng"])
    # Drop OCR blocks below this engine-reported confidence (0-100).
    # 0 keeps everything; 60+ filters noisy recognitions.
    min_confidence: int = 0
    # Override the tesseract binary path. None -> PATH lookup.
    tesseract_cmd: str | None = None


@dataclass
class VideoGenerationConfig:
    """Native video generation broker (T6-05).

    Phase 18.1 R4 stage 5: half the legacy ``video_*`` namespace --
    the generation broker bits (``video_generation_enabled``,
    ``video_backend*``, cost guards). The analysis half lives in
    :class:`VideoAnalysisConfig`; this split keeps the two distinct
    subsystems from sharing ambiguous field names.
    """

    enabled: bool = False
    # Capability-broker preference order; "local" prefers in-tree
    # backends, "remote" prefers hosted vendor adapters.
    backend_prefer: str = "local"
    # Cost guard. The model confirms before submitting any job
    # exceeding either threshold; never silently spend.
    confirm_over_seconds: float = 60.0
    confirm_over_cost: float = 1.0
    # Default <profile_dir>/videos when None.
    output_dir: str | None = None
    poll_interval_s: float = 5.0
    # Pinned backend name (overrides the broker). None lets the
    # broker pick via backend_prefer. Mutated by ``/video set <name>``.
    backend: str | None = None


@dataclass
class VideoAnalysisConfig:
    """video_analyze tool (T4-04).

    Phase 18.1 R4 stage 5: the analysis half of the legacy ``video_*``
    namespace. Wraps ffmpeg/ffprobe for frame extraction + per-frame
    vision routing. The generation broker bits live in
    :class:`VideoGenerationConfig`.
    """

    enabled: bool = True
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    # Default <profile_dir>/video/frames when None.
    frames_dir: str | None = None
    # Cap extracted frames per file -- vision context window protection.
    max_frames: int = 200
    # Default extract mode: ``"keyframes"`` | ``"sampled"`` | ``"range"``.
    default_extract: str = "keyframes"
    # Interval between sampled frames in seconds when default_extract
    # == "sampled".
    sampled_interval_s: float = 5.0


@dataclass
class PluginsConfig:
    """Plugin enable overrides + per-plugin config slices.

    Phase 18.1 R4 stage 4b: promotes ``cfg.plugins: dict[str, Any]`` to
    a typed dataclass. The dict had two roles -- an ``"enabled"`` key
    mapping ``plugin_name -> bool`` AND arbitrary other keys (one per
    plugin) carrying per-plugin config. The dataclass splits those:

    - :attr:`enabled` -- ``{plugin_name: bool}`` override map. Managed
      by ``athena plugins {enable,disable}`` writing to
      ``~/.athena/plugins_state.json``.
    - :attr:`per_plugin` -- ``{plugin_name: {key: value, ...}}`` for
      the slice the plugin's ``Plugin.__init__`` receives as
      ``config``.

    Implements ``__getitem__`` + ``get`` so existing dict-style readers
    (``cfg.plugins.get("enabled")``, ``cfg.plugins["plugin_name"]``)
    keep working without changes. Internal helpers
    (:meth:`as_dict_for_loader`) bridge to call sites that need the
    legacy dict envelope.
    """

    enabled: dict[str, bool] = field(default_factory=dict)
    per_plugin: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style read. ``"enabled"`` returns the enable map;
        anything else returns the per-plugin slice if present, else
        ``default``."""
        if key == "enabled":
            return self.enabled
        return self.per_plugin.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if key == "enabled":
            return self.enabled
        return self.per_plugin[key]

    def __contains__(self, key: str) -> bool:
        if key == "enabled":
            return True
        return key in self.per_plugin

    def as_dict_for_loader(self) -> dict[str, Any]:
        """Reconstitute the legacy ``{"enabled": ..., "<name>": ...}``
        envelope the plugin loader expects. Kept narrow on purpose --
        ad-hoc dict conversions across the rest of the codebase should
        prefer :meth:`get` / attribute access."""
        return {
            "enabled": dict(self.enabled),
            **{k: dict(v) for k, v in self.per_plugin.items()},
        }


@dataclass
class ProvidersConfig:
    """Provider routing + per-provider config slices.

    Phase 18.1 R4 stage 6 (closes R4): promotes ``cfg.providers:
    dict[str, Any]`` to a typed dataclass. The legacy dict had two
    roles -- a ``"routing"`` key mapping ``model_name -> provider``
    PLUS arbitrary other keys (one per provider) carrying that
    provider's host/fallback/base_url slice. The dataclass splits
    those:

    - :attr:`routing` -- ``{model_name: provider_name}`` overrides
      consulted before the prefix-based dispatch in
      :func:`athena.providers.runtime_resolver._route`.
    - :attr:`per_provider` -- ``{provider_name: {key: value, ...}}``
      slice the runtime resolver reads to find ``host``,
      ``base_url``, ``fallback`` chains, etc.

    Implements ``__getitem__`` / ``get`` / ``__contains__`` so the
    existing ``(cfg.providers or {}).get("routing")`` /
    ``.get(name, {})`` readers in
    :mod:`athena.providers.runtime_resolver` and
    :mod:`athena.cli.providers` keep working without changes.
    :meth:`from_dict` lets callers (Config.__post_init__, test
    fixtures) coerce a legacy dict into the dataclass shape.
    """

    routing: dict[str, str] = field(default_factory=dict)
    per_provider: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProvidersConfig:
        """Build a ProvidersConfig from the legacy flat-dict envelope.

        ``d["routing"]`` (if a dict) populates :attr:`routing`; every
        other dict-valued key becomes a :attr:`per_provider` slice.
        Non-dict garbage is silently dropped -- the runtime resolver
        already tolerates malformed config and prints warnings at
        usage time.
        """
        if not isinstance(d, dict):
            return cls()
        routing_raw = d.get("routing")
        routing: dict[str, str] = {}
        if isinstance(routing_raw, dict):
            for k, v in routing_raw.items():
                if isinstance(k, str) and isinstance(v, str):
                    routing[k] = v
        per_provider: dict[str, dict[str, Any]] = {}
        for k, v in d.items():
            if k == "routing":
                continue
            if isinstance(k, str) and isinstance(v, dict):
                per_provider[k] = dict(v)
        return cls(routing=routing, per_provider=per_provider)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style read. ``"routing"`` returns the routing map;
        anything else returns the per-provider slice if present, else
        ``default``."""
        if key == "routing":
            return self.routing
        return self.per_provider.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if key == "routing":
            return self.routing
        return self.per_provider[key]

    def __contains__(self, key: str) -> bool:
        if key == "routing":
            return True
        return key in self.per_provider

    def __bool__(self) -> bool:
        """Truthy iff at least one routing entry or per-provider slice
        is present. Keeps the legacy ``(cfg.providers or {}).get(...)``
        defensive pattern doing the right thing when the config is
        empty."""
        return bool(self.routing) or bool(self.per_provider)


@dataclass
class ParseltongueConfig:
    """Parseltongue inference-param policy config.

    Phase 18.1 R4 stage 4: promotes ``cfg.parseltongue: dict[str, Any]``
    to a real dataclass. The dict's documented schema (``policy``,
    ``defaults``, ``user_rules``, ``classifier_model``) is now
    type-checked at construction; unknown keys in the TOML table fall
    through silently rather than being treated as live config (matches
    the prior dict behaviour exactly).
    """

    # Which policy class drives params_for(). One of "static",
    # "heuristic", "llm_classifier". Empty string means "use the
    # heuristic default". The llm_classifier branch currently raises
    # at construction time (see ``policy_from_config``).
    policy: str = "heuristic"
    # Param dict baked into StaticPolicy when ``policy == "static"``.
    # Keys match provider stream_chat kwargs (temperature, top_p,
    # repeat_penalty, mirostat*, etc.).
    defaults: dict[str, Any] = field(default_factory=dict)
    # User-defined rules layered on top of the built-in heuristic
    # rules. Each entry: {"when": str, "params": dict[str, Any],
    # plus when-specific keys like ``pattern`` or ``count``}. See
    # athena/agent/param_policy.py:user_rules_from_config for the
    # supported ``when`` predicates.
    user_rules: list[dict[str, Any]] = field(default_factory=list)
    # Classifier model when ``policy == "llm_classifier"`` (deferred).
    # Kept on the dataclass so the future implementation can read it
    # without a schema migration.
    classifier_model: str = "qwen2.5:1.5b"


@dataclass
class ComputerConfig:
    """Computer-use subsystem config (T6-04 + T6-04R).

    Phase 18.1 R4 stage 3: promotes the 12 flat ``computer_*`` Config
    fields into one nested dataclass. Legacy reads (``cfg.computer_use_enabled``)
    keep working for one release via ``Config.__getattr__``; legacy
    writes (``cfg.computer_use_enabled = True``, common in test fixtures)
    route through ``Config.__setattr__`` to the nested instance so
    canonical readers and test mutations agree.
    """

    # Master enable. Disabled by default -- the model gets a structured
    # "computer use is disabled" tool result on every input call until
    # the operator turns this on.
    use_enabled: bool = False
    # Permission gate mode:
    #   "observe_only"  watches + advises, never inputs (default)
    #   "per_action"    confirm every input event (safest active mode)
    #   "per_session"   confirm input once per task; destructive STILL
    #                   confirms individually in every mode
    permission_mode: str = "observe_only"
    app_allowlist: list[str] = field(default_factory=list)
    app_denylist: list[str] = field(
        default_factory=lambda: [
            # Sensible defaults -- denylist wins, so even when the user
            # opts in to control they must explicitly REMOVE one of
            # these to touch it.
            "1password",
            "bitwarden",
            "lastpass",
            "keychain",
            "keepass",
            "banking",
            "wallet",
            "ledger live",
            "metamask",
        ]
    )
    kill_hotkey: str = "ctrl+alt+k"
    max_actions_per_task: int = 40
    max_actions_per_sec: float = 2.0
    backend: str = "auto"
    dry_run: bool = False
    audit_path: str | None = None  # default <profile_dir>/computer_audit.jsonl
    # T6-04.4 follow-up: screenshots are written to disk (NOT inlined
    # as base64 -- a 4K screen would be ~30 MB of base64 -> ~10M tokens,
    # way beyond local-model context windows). Default location is
    # <profile_dir>/screenshots/<ts>-<sha8>.bmp.
    screenshots_dir: str | None = None
    # T6-04R: refuse input + destructive when the autonomous /goal
    # continuation loop is driving turns. The goal loop runs in
    # FOREGROUND origin (not BACKGROUND_REVIEW), so approval_guard's
    # background-deny alone wouldn't catch it; this is the
    # computer-use-specific extra check. Default True -- the
    # autonomous loop never gets to drive the desktop unless the
    # operator deliberately disables this.
    deny_during_goal_loop: bool = True


@dataclass
class BashConfig:
    """Bash gate config -- allowlist + extra denylist patterns.

    Pilot for the Phase 18.1 R4 nested-config migration: the legacy
    ``cfg.bash_allowlist`` + ``cfg.bash_extra_denylist`` flat fields
    are still accessible via ``Config.__getattr__`` shims. New code
    should read ``cfg.bash.allowlist`` / ``cfg.bash.extra_denylist``.
    """

    # Per-Bash command allowlist; entries are word-boundary matched
    # against the binary token. E.g. ``["git", "ls", "cat"]``.
    # Allowlisted commands skip the confirmation prompt even when
    # ``auto_approve_tools`` is False.
    allowlist: list[str] = field(default_factory=list)
    # Additional regex denylist patterns appended to
    # ``athena.safety.shell_policy.DEFAULT_DENYLIST``. Always enforced
    # before the allowlist; matching commands are rejected outright.
    extra_denylist: list[str] = field(default_factory=list)


@dataclass
class ReviewConfig:
    """Per-turn background review settings."""

    nudge_interval: int = 10  # fire review every N tool calls
    disabled: bool = False
    max_iterations: int = 8  # fork loop cap


@dataclass
class CuratorConfig:
    """Curator (umbrella consolidation) settings."""

    interval_hours: int = 168  # default 7 days between runs
    min_idle_hours: int = 2  # don't run if a session ended within this window
    max_iterations: int = 9999  # fork loop cap; effectively unbounded


@dataclass
class WebhookServerConfig:
    """Webhook listener settings (Phase 15). Lives inside
    GatewayConfig because the listener shares the gateway daemon's
    process — start gateway, get webhooks for free (when enabled)."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 4747


@dataclass
class UserModelConfig:
    """Auto-extracted user/project observations — separate from the
    ``write_memory`` user-authored store. ``backend`` picks the
    implementation: ``markdown`` (default; writes to
    ``~/.athena/profiles/<profile>/user_model/``), ``honcho`` (points
    at a Honcho instance for server-scale deployments — planned), or
    ``none`` (disables auto extraction entirely)."""

    backend: str = "markdown"
    # Triggers for the post-session fact-extraction LLM call. Both
    # fire-and-forget; if either is wedged it never blocks the user.
    ingest_on_compact: bool = True
    ingest_on_session_end: bool = True
    # Per-N-turn ingestion for long sessions. 0 disables.
    ingest_every_n_turns: int = 0
    # Model used for extraction + query. None = use the main agent
    # model. Set to a smaller / cheaper model when the main model
    # is paid-per-token; the extractor's job is structured fact
    # output, which smaller models handle fine.
    extract_model: str | None = None
    # Honcho-specific. Unused until the Honcho backend lands.
    honcho_url: str = "http://localhost:8000"
    honcho_workspace: str = "athena-default"
    honcho_peer_id: str = ""
    honcho_api_key_env: str = "ATHENA_HONCHO_API_KEY"


@dataclass
class GatewayConfig:
    """Gateway daemon settings (Phase 10).

    ``max_warm_agents`` bounds the in-memory agent pool — sessions
    beyond the cap get evicted LRU-style and reload from JSONL the
    next time their chat fires. Sized for a single-user gateway; bump
    if running multi-tenant.

    ``continuity`` toggles cross-platform user linking — when True,
    the router consults ``gateway_user_links`` so the same human on
    Telegram and Slack shares one session.

    Per-platform credentials live under
    ``[gateway.platforms.<name>]`` in config.toml — adapters read what
    they need (bot tokens, app tokens, intents) directly from there,
    keeping the dataclass platform-agnostic.
    """

    max_warm_agents: int = 50
    continuity: bool = False
    platforms: dict[str, Any] = field(default_factory=dict)
    webhooks: WebhookServerConfig = field(default_factory=WebhookServerConfig)
