"""Configuration loading. Reads ~/.athena/config.toml; falls back to defaults."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore


_PRIMARY_HOME = Path.home() / ".athena"
_LEGACY_HOME = Path.home() / ".ocode"


def _resolve_home() -> Path:
    """Return the active athena home dir.

    Prefers ``~/.athena/``. Falls back to ``~/.ocode/`` if athena's home
    is missing but the legacy one exists — supports users migrating from
    the previous project name without forcing them to move files. Once
    ``~/.athena/`` exists (even empty), the legacy home is ignored.
    """
    if _PRIMARY_HOME.exists():
        return _PRIMARY_HOME
    if _LEGACY_HOME.exists():
        return _LEGACY_HOME
    return _PRIMARY_HOME


CONFIG_DIR = _resolve_home()
LEGACY_CONFIG_DIR = _LEGACY_HOME  # explicit handle for migration helpers
CONFIG_PATH = CONFIG_DIR / "config.toml"
SESSIONS_DIR = CONFIG_DIR / "sessions"  # legacy flat dir; new code uses profile_dir
USER_MCP_PATH = CONFIG_DIR / "mcp.json"
# Machine-managed plugin enable state; athena plugins {enable,disable} writes here.
PLUGINS_STATE_PATH = CONFIG_DIR / "plugins_state.json"


def profile_dir(profile: str = "default", home: Path | None = None) -> Path:
    """Return the on-disk root for ``profile`` (``~/.athena/profiles/<profile>``)."""
    return (home or CONFIG_DIR) / "profiles" / profile


def mcp_config_paths(workspace: Path) -> list[Path]:
    """Files to read for MCP server config, in precedence order (later wins).

    Order:
      1. ~/.athena/mcp.json           (user-level defaults)
      2. <workspace>/.athena/mcp.json (project-level, hidden)
      3. <workspace>/mcp.json        (project-level, visible — overrides above)
    """
    return [
        USER_MCP_PATH,
        workspace / ".athena" / "mcp.json",
        workspace / "mcp.json",
    ]


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


@dataclass
class Config:
    model: str = "qwen2.5-coder:14b"
    ollama_host: str = "http://127.0.0.1:11434"
    # Profile name under ~/.athena/profiles/<profile>/. Sessions, memory, and
    # per-profile config live here. Multiple profiles let a user keep work
    # contexts (default / personal / client-foo) separated without juggling
    # ATHENA_HOME values.
    profile: str = "default"
    review: ReviewConfig = field(default_factory=ReviewConfig)
    curator: CuratorConfig = field(default_factory=CuratorConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    # Skip the per-tool confirmation prompt for tools that opt into it
    # (Bash, Write to existing files, etc.). Replaces the old auto_approve_bash.
    auto_approve_tools: bool = False
    context_window: int = 32768
    # Toolsets advertised to the model. None means "all registered toolsets"
    # (legacy behavior). An explicit list scopes the registry — used by forks
    # to give sub-agents a narrow capability surface.
    enabled_toolsets: list[str] | None = None
    # Tools the user has globally disabled (by name). Deprecated in favor of
    # enabled_toolsets but kept for one transitional release; intersects with
    # enabled_toolsets when both are set.
    disabled_tools: list[str] = field(default_factory=list)
    # Max bytes to include from a single file read
    max_file_read: int = 256_000
    # Max stdout bytes captured per bash run
    max_bash_output: int = 64_000
    # Use a trimmed system prompt (helpful for small or low-context models)
    lean_prompt: bool = False
    # Section names to omit from the system prompt. Names match keys in
    # athena/prompts/system.py SECTIONS (e.g. "executing_with_care",
    # "session_guidance", "memory_header"). Combines with lean_prompt.
    disabled_prompt_sections: list[str] = field(default_factory=list)
    # Per-Bash command allowlist; entries are word-boundary matched
    # against the binary token (Phase 17 ShellPolicy). E.g.
    # ["git", "ls", "cat"]. Allowlisted commands skip the
    # confirmation prompt even when auto_approve_tools is False.
    bash_allowlist: list[str] = field(default_factory=list)
    # Additional regex denylist patterns appended to
    # athena.safety.shell_policy.DEFAULT_DENYLIST. Always enforced
    # before the allowlist; matching commands are rejected outright
    # by the Bash tool.
    bash_extra_denylist: list[str] = field(default_factory=list)
    # Phase 17 [safety] settings. Keys preserved in a sub-dict so
    # athena.safety modules can read them without growing the top-
    # level Config surface for every new option.
    safety: dict[str, Any] = field(
        default_factory=lambda: {
            "snapshot_foreground": False,
            "retention_days": 90,
            "retention_count": 5_000,
            "retention_bytes": 5 * 1024**3,
            "extra_denylist": [],
        }
    )
    # Hard cap on tool-call rounds per user turn. Stops runaway loops.
    max_turn_steps: int = 25
    # Plugin configuration. ``plugins["enabled"]`` is a {plugin_name: bool}
    # override map maintained by ``athena plugins enable|disable``. Per-plugin
    # config slices live under ``plugins[<plugin_name>]``.
    plugins: dict[str, Any] = field(default_factory=dict)
    # Provider configuration (Phase 8). Sub-keys:
    #   providers.routing     {model_name: provider_name} explicit overrides
    #   providers.<name>.host base URL for ollama / openai_compat
    #   providers.<name>.fallback  ordered list of provider names to try
    #                              when the primary's credentials are exhausted
    providers: dict[str, Any] = field(default_factory=dict)
    # Anthropic prompt caching (T2-01). Strategy "system_and_3" attaches
    # cache_control markers to the last system message + the last 3
    # non-system messages on Anthropic, OpenRouter, and Nous-Portal
    # provider calls. "none" disables caching (safe default for v0.3.0
    # dogfood while we shake out any routing-layer quirks). "aggressive"
    # is reserved for future strategies; currently behaves identically
    # to system_and_3.
    cache_strategy: str = "system_and_3"
    # Cache TTL. "5m" is Anthropic's default; "1h" extends caching
    # across sessions that hit the cache within the hour (slightly
    # higher per-write cost, much better for repeat usage patterns).
    prompt_cache_ttl: str = "5m"
    # Rate-limit throttle threshold (T2-02). When the provider's most
    # recent response reports usage ratio >= this value (i.e. less than
    # (1 - threshold) of the limit remains), the provider sleeps until
    # the soonest reset (capped at 60s) before sending the next
    # request. 0.95 means "throttle when within 5% of the limit"; set
    # to 1.0 to disable proactive throttling and react only to 429.
    rate_limit_throttle_threshold: float = 0.95
    # Retry budget per call to provider.stream_chat (T2-03). The
    # error_classifier dispatches each exception to RETRY /
    # ROTATE_CREDENTIAL / COMPRESS_CONTEXT / ABORT; retry_utils.with_retry
    # enforces this cap across all recovery actions.
    max_retries_per_turn: int = 5
    # Maximum backoff between retries, in seconds. The base is
    # exponential (2^attempt + jitter); a server-supplied Retry-After
    # also caps at this value so a malformed "Retry-After: 600" can't
    # accidentally sleep for ten minutes (T2-03).
    max_backoff_seconds: float = 30.0
    # T2-04 context compression knobs. When total session tokens
    # exceed `context_compress_watermark * context_window`, the
    # middle of the conversation is summarised via the auxiliary
    # client and replaced with a synthetic system-role summary
    # message. Head (system prompt) and tail (most recent turns
    # totalling `tail_protection_ratio * context_window` tokens) are
    # preserved verbatim.
    context_compress_watermark: float = 0.75
    tail_protection_ratio: float = 0.25
    # Tool-role messages in the to-be-summarised middle are pruned to
    # this many tokens before being fed to the summariser (cheap
    # pre-pass — keeps large grep / curl outputs from blowing the
    # summariser's own context).
    tool_output_prune_tokens: int = 200
    # The summary's target size is `summary_budget_ratio` of the
    # compressed-middle token count, capped at
    # `summary_budget_cap_tokens`. Defaults: 10% with a 4k cap.
    summary_budget_ratio: float = 0.10
    summary_budget_cap_tokens: int = 4000
    # T2-05: when a provider hands back a tool call whose arguments
    # string is malformed JSON (smart quotes, single quotes, trailing
    # commas, unquoted keys), athena.providers.schema_sanitizer
    # attempts a sequence of forgiving passes to recover the intended
    # JSON before dispatch. Set to False to fall straight through to
    # the raw json.loads error path (useful for debugging upstream
    # model behaviour).
    tool_call_sanitize: bool = True
    # T2-06: out-of-band tool result storage. When a tool's
    # stringified output exceeds tool_result_threshold_bytes, the
    # full output is persisted to a content-addressed blob under
    # tool_result_storage_path and the agent sees a short reference
    # handle in conversation history. The agent can read the stored
    # content later via the read_tool_result tool.
    tool_result_threshold_bytes: int = 1_000_000
    tool_result_storage_path: str = "~/.athena/tool_results"
    # T2-08: defaults for the clarify tool. Per-call args override.
    # When the user doesn't reply within `clarify_default_timeout_seconds`
    # the tool returns "no answer received (timeout after Ns)" and the
    # agent decides whether to fall back to a default guess or abort.
    # `clarify_allow_freeform = True` lets the user type a custom answer
    # alongside the numbered options.
    clarify_default_timeout_seconds: int = 300
    clarify_allow_freeform: bool = False
    # T3-01: athena proxy — local OpenAI-compatible HTTP endpoint.
    # `proxy_default_provider` is the provider used when neither
    # X-Athena-Provider nor the model-name match resolves a provider.
    # `proxy_bind_host` defaults to loopback; --bind-public on the CLI
    # is required to bind 0.0.0.0 (defense-in-depth: the proxy
    # forwards using your API keys). `proxy_log_path` /
    # `proxy_bodies_dir` are the summary JSONL and the optional
    # full-payload sidecar locations; `proxy_log_bodies` opt-ins
    # to the latter for deep debugging.
    proxy_default_provider: str = "anthropic"
    proxy_bind_host: str = "127.0.0.1"
    proxy_bind_port: int = 11434
    proxy_require_auth: bool = False
    proxy_log_path: str = "~/.athena/proxy.jsonl"
    proxy_log_bodies: bool = False
    proxy_bodies_dir: str = "~/.athena/proxy_bodies"
    proxy_no_translate: bool = False
    # T3-02: athena mcp serve — local MCP server exposing the curated
    # read-only + snapshot-revert tool surface to peer MCP clients
    # (Claude Desktop, Claude Code, Cursor). `mcp_default_transport`
    # is "stdio" (the spec-canonical transport launched by clients as
    # a subprocess); SSE is reserved. `mcp_allow_write` is reserved
    # for a future opt-in to write-capable tools (none ship yet).
    mcp_default_transport: str = "stdio"
    mcp_sse_port: int = 8765
    mcp_log_path: str = "~/.athena/mcp.jsonl"
    mcp_allow_write: bool = False
    # T3-06R: per-skill usage metrics. When True (default), each
    # disclosure of a skill body via skill_view / load_body records
    # one JSONL line at <profile_dir>/skill_metrics.jsonl. The
    # curator reads these to flag never-used / stale skills as
    # prune candidates; metrics inform, they don't override.
    skill_metrics_enabled: bool = True
    # T5-02R: local sandbox. Wraps the Bash tool's command in a
    # bubblewrap (bwrap) jail when enabled: read-only system root,
    # writable workspace only, no network by default. The
    # shell_policy denylist still runs FIRST as the security
    # floor; the sandbox is defense-in-depth on top. Linux-only;
    # `sandbox_fallback="warn"` lets non-Linux / no-bwrap installs
    # continue with the policy alone, `"error"` refuses commands.
    sandbox_enabled: bool = False
    sandbox_backend: str = "bwrap"
    sandbox_allow_network: bool = False
    sandbox_writable_paths: list[str] = field(default_factory=list)
    sandbox_fallback: str = "warn"  # "warn" | "error"
    # T5-03R: LSP diagnostics. When True, the `diagnose` tool (and
    # the T5-04 verified-execution gate) launches a configured
    # language server (default: pyright-langserver for Python) and
    # collects publishDiagnostics. lsp_server_command is a dict
    # `{language: ["argv", ...]}` overriding the built-in default
    # per language. lsp_timeout_s caps the per-call wait.
    lsp_enabled: bool = False
    lsp_server_command: dict[str, list[str]] = field(default_factory=dict)
    lsp_timeout_s: float = 30.0
    # T5-04: verified-execution loop. After each file write, the
    # loop diagnoses the file via LSP, optionally runs a sandboxed
    # verify_command (e.g. "pytest -q", "ruff check"), and on
    # failure either offers a `/rollback-to <id>` to the user
    # (verify_auto_rollback=False) or reverts automatically
    # (=True).  ``verify_on_write`` selects how much the loop does:
    #
    #   "off"          do nothing (legacy behaviour)
    #   "diagnose"     LSP only — fast, no subprocess
    #   "diagnose+run" LSP plus verify_command (uses sandbox if
    #                  sandbox_enabled is True)
    #
    # ``verify_auto_retry`` (off by default) lets the loop ask the
    # active provider for a one-shot revised write before falling
    # back to the rollback offer — capped at ``verify_max_retries``.
    verify_on_write: str = "diagnose"  # "off" | "diagnose" | "diagnose+run"
    verify_command: str | None = None
    verify_auto_rollback: bool = False
    verify_auto_retry: bool = False
    verify_max_retries: int = 2
    verify_run_timeout_s: float = 120.0
    # T5-05: capability broker. media_backend_prefer ("local" or
    # "any") picks how MediaRegistry breaks ties when multiple
    # backends declare a media capability. mcp_expose is a
    # whitelist of differentiated MCP tools to advertise — empty
    # tuple means "all available". When non-empty, only listed
    # tools are advertised even when other tools are available.
    media_backend_prefer: str = "local"
    mcp_expose: tuple[str, ...] = ()
    # T5-06: cross-session prompt cache. Reuses a stable prefix
    # (system prompt + pinned skills + durable context) across
    # sessions, keyed by SHA-256 of the exact prefix bytes (a
    # changed prefix → a clean miss, never a wrong hit). The
    # caching mechanism (server-side TTL cache / local KV reuse
    # / none) is chosen from the provider's T5-01 manifest. Tiny
    # prefixes (below cache_min_prefix_tokens) skip caching
    # entirely. cache_index_path defaults to
    # <profile_dir>/cache_index.json — resolved lazily at
    # session start since the profile dir depends on the
    # selected profile.
    cross_session_cache_enabled: bool = True
    cache_min_prefix_tokens: int = 1024
    cache_index_path: str | None = None
    # T5-07: /goal autonomous continuation loop. The passive goal
    # invariant (goal.txt + system-prompt block) stays — this is
    # an ADDITIVE active driver. After each real assistant turn,
    # if a goal_state is active and the loop's caps haven't been
    # hit, a synthetic continuation turn is injected. The loop
    # stops on a "GOAL ACHIEVED" sentinel, a "GOAL BLOCKED:
    # <reason>" sentinel, the turn cap, or the token cap. Ctrl+C
    # always wins (pauses the goal); real user messages and
    # /steer always preempt synthetic turns. Caps are mandatory;
    # there is no unbounded mode.
    goal_loop_enabled: bool = True
    goal_max_turns: int = 25
    goal_max_tokens: int = 200_000
    goal_continuation_prompt: str | None = None  # None = built-in default
    goal_achieved_sentinel: str = "GOAL ACHIEVED"
    goal_blocked_sentinel: str = "GOAL BLOCKED"
    # T6-01: semantic + hybrid recall. The existing FTS5
    # keyword path stays — semantic is additive. recall_default_mode
    # picks how the recall tool ranks results when no explicit
    # mode is passed:
    #   "keyword"  FTS5 only (today's behaviour)
    #   "semantic" vector cosine only
    #   "hybrid"   RRF fusion of both (default; the quality win)
    # embedding_model is optional; when omitted, the resolved
    # provider's default_embedding_model is used. vector_store_path
    # defaults to <profile_dir>/vectors.json — flat-file works at
    # athena's per-user scale.
    semantic_recall_enabled: bool = True
    recall_default_mode: str = "hybrid"
    embedding_model_prefer: str = "local"
    embedding_model: str | None = None
    vector_store_path: str | None = None
    # T6-02: social/X provider + capability routing. The provider
    # declares social_search in its manifest; the broker routes
    # `search_x` sub-tasks to it via best_provider_for({
    # "social_search"}). The primary chat model stays selected.
    #
    # OAuth specifics are vendor-dependent and isolated to
    # athena.social.oauth — set the URLs/scopes/client id at
    # build time. The client secret is read from a file at
    # social_oauth_client_secret_path (file mode should be 0o600).
    #
    # social_router_heuristic enables a phrase-detecting auto-
    # router (T6-02.4); default off — the explicit search_x tool
    # is the safe path.
    social_provider_enabled: bool = False
    social_search_max_results: int = 20
    social_router_heuristic: bool = False
    social_search_url: str | None = None
    social_search_query_param: str = "query"
    social_search_extra_params: dict[str, Any] = field(default_factory=dict)
    social_post_url_template: str = ""
    social_oauth_authorize_url: str | None = None
    social_oauth_token_url: str | None = None
    social_oauth_client_id: str | None = None
    social_oauth_client_secret_path: str | None = None
    social_oauth_scopes: list[str] = field(default_factory=list)
    social_oauth_redirect_uri: str | None = None
    # Alternate auth: app-only Bearer token (X v2 / Twitter API
    # gives you one out of the dev portal). Skip OAuth entirely
    # — the token is the single credential. Stored at the path
    # below as plain text, 0o600 (atomic-replace via
    # secure_files when athena writes it). NEVER paste the
    # token into config.toml directly — the file-on-disk model
    # is what keeps it out of cleartext config and out of any
    # backup that picks up your dotfiles.
    social_bearer_token_path: str | None = None
    # T6-03: external coding-CLI delegation. delegate_to_cli runs
    # the configured external CLI on a scoped task in an isolated
    # git worktree, captures the diff, surfaces it for review.
    # NEVER auto-merges. cli_delegate_sandbox=True wraps the
    # delegate invocation in the T5-02 bwrap sandbox.
    #
    # cli_delegate_command is the invocation template — vendor-
    # specific. Use {task} as the placeholder; the task text is
    # substituted in after shlex.split so quotes / spaces stay
    # one argv element. Example:
    #   "codex exec --quiet {task}"
    #   "aider --message {task} --yes"
    cli_delegate_enabled: bool = False
    cli_delegate_command: str | None = None
    cli_delegate_timeout_s: float = 600.0
    cli_delegate_worktree_root: str | None = None
    cli_delegate_sandbox: bool = True
    # T6-04: computer use (desktop control). CRITICAL safety
    # surface — the permission model is the entire boundary.
    # Computer use is the INVERSE of T5-02's sandbox: it points
    # the agent at the real machine on purpose. There is no
    # isolation; the gate + kill switch are all there is.
    #
    # Every default is SAFE:
    #   computer_use_enabled=False         opt-in per machine
    #   computer_permission_mode="observe_only"  no input by default
    #   computer_app_allowlist=[]          control requires explicit
    #                                       opt-in of specific apps
    #   computer_app_denylist=[...]        sensitive apps never touched;
    #                                       denylist always wins over
    #                                       allowlist and mode
    #
    # Modes:
    #   "observe_only"  athena watches + advises, never inputs (default)
    #   "per_action"    confirm every input event (safest active mode)
    #   "per_session"   confirm input once per task; destructive STILL
    #                   confirms individually in every mode
    computer_use_enabled: bool = False
    computer_permission_mode: str = "observe_only"
    computer_app_allowlist: list[str] = field(default_factory=list)
    computer_app_denylist: list[str] = field(
        default_factory=lambda: [
            # Sensible defaults — denylist wins, so even when the
            # user opts in to control they must explicitly REMOVE
            # one of these to touch it.
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
    computer_kill_hotkey: str = "ctrl+alt+k"
    computer_max_actions_per_task: int = 40
    computer_max_actions_per_sec: float = 2.0
    computer_backend: str = "auto"
    computer_dry_run: bool = False
    computer_audit_path: str | None = None  # default <profile_dir>/computer_audit.jsonl
    # T6-04.4 follow-up: screenshots are written to disk
    # (NOT inlined as base64 in the tool result — a 4K screen
    # would be ~30 MB of base64 → ~10M tokens, way beyond
    # local-model context windows). Default location is
    # <profile_dir>/screenshots/<ts>-<sha8>.bmp.
    computer_screenshots_dir: str | None = None
    # T6-04R: refuse input + destructive when the autonomous
    # /goal continuation loop is driving turns. The goal loop
    # runs in FOREGROUND origin (not BACKGROUND_REVIEW), so
    # approval_guard's background-deny alone wouldn't catch it;
    # this is the computer-use-specific extra check. Default
    # True — the autonomous loop never gets to drive the
    # desktop unless the operator deliberately disables this.
    computer_deny_during_goal_loop: bool = True
    # T6-05: native video generation. video_generate +
    # animate_image tools backed by the T5-05 media broker
    # (video_generation capability). Cost / latency guard
    # confirms before submitting any job exceeding the
    # configured thresholds — never silently spend. Outputs
    # land under video_output_dir + are hash-logged in
    # media_log.jsonl alongside.
    video_generation_enabled: bool = False
    video_backend_prefer: str = "local"
    video_confirm_over_seconds: float = 60.0
    video_confirm_over_cost: float = 1.0
    video_output_dir: str | None = None  # default <profile_dir>/videos
    video_poll_interval_s: float = 5.0
    # T6-06: auto kanban. Promotes the in-memory TaskCreate /
    # TaskUpdate / TaskList tracker to a persisted store + a
    # board view. Single backing store also receives goal-loop
    # subgoals (T5-07) as cards with goal_id set — no parallel
    # lists. task_store_path defaults to <profile_dir>/tasks/
    # tasks.json at resolve time. board_auto_maintain nudges
    # the agent in the system prompt to keep the board current;
    # off → the board is manual.
    task_persist: bool = True
    task_store_path: str | None = None
    board_auto_maintain: bool = True
    task_archive_done_after_days: float = 30.0
    # T6-07: self-update. `athena update` detects how athena was
    # installed and uses the matching upgrade path. update_source
    # forces a path ("pypi" / "git") or lets detection pick
    # ("auto"). update_channel picks stable vs pre-release.
    # update_auto_check (off by default) prints a one-line
    # notice at startup when a newer version exists — notify
    # only; never auto-installs.
    update_source: str = "auto"
    update_channel: str = "stable"
    update_auto_check: bool = False
    update_state_path: str | None = None  # default <CONFIG_DIR>/update_state.json
    # T4-01: vision_analyze. Local pixel ops (EXIF / ELA / pHash /
    # histogram / crop / metadata-strip) are gated; the
    # `describe` mode is a passthrough to the active provider's
    # vision capability and tiles the input rather than
    # downsampling it (preserves detail for forensic reads).
    # Every read is hash-logged to <profile_dir>/vision_audit.jsonl
    # (provenance trail) and crops land under vision_crop_dir.
    vision_enabled: bool = True
    # Max input pixels for local ops — bombs above this size are
    # refused before Pillow decodes them. 80 Mpx covers typical
    # camera RAW / large screenshot inputs and rejects crafted
    # 1 GB PNGs.
    vision_max_input_pixels: int = 80_000_000
    # Default ELA parameters — surfaceable via vision_analyze
    # args; per-call values override.
    vision_ela_quality: int = 80
    vision_ela_threshold: int = 15
    # Default perceptual-hash algorithm + size. phash is the
    # imagehash library's general-purpose default.
    vision_phash_algorithm: str = "phash"
    vision_phash_size: int = 8
    # Default tile cap per provider — None means "use the
    # built-in per-provider value from athena.vision.passthrough".
    vision_long_edge_cap: int | None = None
    # Output dirs (None → resolved at runtime under <profile_dir>).
    vision_crop_dir: str | None = None  # default <profile_dir>/vision/crops
    # T4-02: video_analyze. Two-layer discipline (container atom
    # ordering / encoder signals + elementary-stream codec / GOP)
    # reported separately. Frame extraction routes through ffmpeg;
    # ffprobe drives the codec / encoder / GOP modes. Atoms parser
    # is pure Python — the most useful container-tampering signal
    # remains available even on a host without ffmpeg.
    video_enabled: bool = True
    video_ffmpeg_path: str = "ffmpeg"
    video_ffprobe_path: str = "ffprobe"
    video_frames_dir: str | None = None  # default <profile_dir>/video/frames
    video_max_frames: int = 200
    video_default_extract: str = "keyframes"  # keyframes | sampled | range
    video_sampled_interval_s: float = 5.0
    # T4-03: persistent CDP browser tools (Playwright). One
    # browser context per athena session — cookies/storage
    # survive across tool calls within the session. Lazy
    # launch: ensure_started() runs on first browser tool call;
    # an unused browser pays no chromium cost. Realistic
    # desktop UA by default for legitimate public-target
    # research; capture log is the accountability surface.
    browser_enabled: bool = True
    browser_engine: str = "chromium"
    browser_headless: bool = True
    browser_user_data_root: str | None = None  # default ~/.athena/browser
    browser_capture_path: str | None = None    # default <profile_dir>/browser_capture.jsonl
    browser_screenshots_dir: str | None = None  # default <profile_dir>/browser/shots
    browser_nav_timeout_s: float = 30.0
    browser_min_interval_s: float = 1.0
    browser_block_downloads: bool = True
    browser_user_agent: str | None = None  # None → realistic desktop Chrome UA
    # T4-04: audio_analyze (transcription + optional diarization +
    # coarse content classification). Backend resolved via the
    # T5-05 broker over the `audio_transcription` capability
    # (local-preferred by default — recordings stay on-device).
    # The faster-whisper backend is the in-tree default; real
    # vendor adapters (cloud STT) land alongside one per file.
    audio_analyze_enabled: bool = True
    audio_backend_prefer: str = "local"
    # Diarization is heavier (needs pyannote.audio or similar);
    # off by default. When True, the backend that supports it
    # returns speaker labels per segment; backends without
    # diarization support return segments without the speaker
    # field (no error).
    audio_diarization_enabled: bool = False
    # Long-audio chunking: 30s is the whisper-class default
    # window. Chunks overlap by audio_chunk_overlap_s so words
    # at the seam aren't dropped; the stitch dedupes the
    # overlap region.
    audio_chunk_seconds: float = 30.0
    audio_chunk_overlap_s: float = 2.0
    # Default model for the faster-whisper backend. "base" is
    # the smallest / fastest reasonable model (~74 MB). Other
    # options: "tiny" (39 MB), "small" (244 MB), "medium" (769
    # MB), "large-v3" (1.5 GB). First use downloads the model;
    # subsequent calls reuse the cache.
    audio_whisper_model: str = "base"
    audio_whisper_device: str = "auto"  # auto | cpu | cuda
    audio_whisper_compute_type: str = "auto"  # auto | int8 | float16 | float32
    audio_output_dir: str | None = None  # default <profile_dir>/audio
    # T-MIG (hermes migration): tirith pre-Bash security scanner.
    # Wraps the external `tirith` binary (Linux / macOS) which
    # inspects shell commands for content-level threats
    # (homograph URLs, pipe-to-interpreter, terminal injection
    # via ANSI escapes, etc.) BEFORE bash runs them — defense
    # in depth on top of the approval gate. fail_open=True
    # treats unavailable / timed-out tirith as "allow" rather
    # than blocking (don't make a missing binary a hard error).
    tirith_enabled: bool = True
    tirith_binary_path: str | None = None  # default: PATH lookup
    bash_tirith_precheck: bool = False
    tirith_fail_open: bool = True
    tirith_timeout_s: float = 5.0
    tirith_shell: str = "posix"  # or "powershell"
    # T-MIG: URL safety check. Local heuristic blocklist + an
    # optional online classifier. Advisory — the tools that
    # use it ask for a verdict but don't auto-block; the
    # operator decides.
    url_safety_enabled: bool = True
    url_safety_blocklist_path: str | None = None  # newline hosts
    url_safety_fail_open: bool = True
    # T-MIG: OSV (Open Source Vulnerabilities) database lookup.
    # Read-only HTTP query to https://api.osv.dev. Rate-limited
    # by OSV's free tier but generous for typical use.
    osv_enabled: bool = True
    osv_api_url: str = "https://api.osv.dev/v1/query"
    osv_timeout_s: float = 10.0
    # T-MIG: website policy checker. Parses robots.txt + cheap
    # ToS heuristic for the T4-03 browser. Surfaces the site's
    # stated stance so the operator decides knowingly.
    website_policy_enabled: bool = True
    website_policy_user_agent: str = "athena-policy-checker/1.0"
    website_policy_timeout_s: float = 10.0
    # T-MIG: cross-platform send_message tool. Routes outbound
    # messages through whichever gateway adapter is already
    # configured. Off by default so a model can't accidentally
    # spam anyone.
    send_message_enabled: bool = False
    # T4-05: document_analyze (PDF / DOCX). Extracts clean text +
    # heading outline + tables + metadata. Scanned PDF pages (no
    # text layer) route to OCR (T4-06) when available; degrades
    # cleanly when not — pages return empty with a flagged note.
    # Embedded figures can be described via vision_analyze (T4-01)
    # when extract=full and describe_figures is on.
    document_analyze_enabled: bool = True
    document_default_extract: str = "structure"  # text|structure|tables|metadata|full
    document_ocr_fallback: bool = True
    document_describe_figures: bool = False
    # Page rasterization DPI when rendering scanned pages for OCR
    # or figures for vision. 200 is the OCR sweet spot for most
    # documents; bump to 300 for fine print, 150 for big batches.
    document_rasterize_dpi: int = 200
    document_output_dir: str | None = None  # default <profile_dir>/documents
    # T4-06: OCR — read text from images / scanned pages. The
    # broker routes the `ocr` tool to providers declaring the
    # `ocr` capability (local-preferred by default — text in
    # images stays on the machine). Consumed by T4-05
    # document_analyze for scanned PDF pages and callable from
    # T4-01 vision when "what does the text in this image say"
    # is the question (OCR reads; vision describes).
    ocr_enabled: bool = True
    ocr_backend_prefer: str = "local"
    # Languages passed to tesseract: ISO 639-2/T codes, one or
    # more (tesseract joins with '+'). "eng" is the default;
    # "eng+fra" recognises both English and French in the same
    # image. Each non-default language requires the matching
    # tessdata file installed.
    ocr_languages: list[str] = field(default_factory=lambda: ["eng"])
    # Drop blocks below this OCR-engine-reported confidence
    # (0-100). 0 keeps everything (default); 60+ is a good
    # filter for "treat noisy recognitions as 'unreadable'".
    ocr_min_confidence: int = 0
    # Path override to the tesseract binary. None → use the
    # system PATH lookup (default; works when tesseract is
    # installed via scoop / brew / apt). Set explicitly when
    # the binary isn't on PATH.
    ocr_tesseract_cmd: str | None = None


def load_config() -> Config:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    cfg = Config()
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
        # Back-compat: accept old key name and map it forward
        if "auto_approve_bash" in data and "auto_approve_tools" not in data:
            data["auto_approve_tools"] = data.pop("auto_approve_bash")
            print(
                f"warning: {CONFIG_PATH}: 'auto_approve_bash' is deprecated; "
                "rename to 'auto_approve_tools'.",
                file=sys.stderr,
            )
        for k, v in data.items():
            if hasattr(cfg, k):
                _assign_field(cfg, k, v)
    # Merge plugin enable state from the machine-managed sidecar file.
    cfg.plugins = _merge_plugin_state(cfg.plugins)
    # Env overrides. ATHENA_* is the canonical name; OCODE_* is still
    # honored for one transitional release so existing shells / dotfiles
    # don't break the day after the rename.
    if env := (os.environ.get("ATHENA_MODEL") or os.environ.get("OCODE_MODEL")):
        cfg.model = env
    if env := os.environ.get("OLLAMA_HOST"):
        cfg.ollama_host = _normalize_ollama_host(env)
    return cfg


def _assign_field(cfg: Any, key: str, value: Any) -> None:
    """Apply a top-level config entry from TOML.

    When the existing field on ``cfg`` is itself a dataclass instance
    (Config.gateway is a ``GatewayConfig`` for example), merge the
    TOML table INTO it field-by-field so unspecified options keep
    their defaults. Without this the naive ``setattr`` overwrites the
    typed dataclass with a plain dict and downstream code that reads
    ``cfg.gateway.continuity`` blows up with AttributeError.

    Plain (non-dataclass) fields are assigned verbatim. Mismatched
    types (TOML provided a string where the dataclass expects a
    dataclass instance) fall through to a plain assignment so the
    error surfaces at usage time rather than being silently
    swallowed here.
    """
    import dataclasses as _dc

    current = getattr(cfg, key)
    if _dc.is_dataclass(current) and not _dc.is_dataclass(type(value)) and isinstance(value, dict):
        # Merge TOML dict into the existing dataclass instance.
        for sub_key, sub_val in value.items():
            if hasattr(current, sub_key):
                # Recurse one level so [gateway.webhooks] (itself a
                # dataclass) gets the same treatment.
                _assign_field(current, sub_key, sub_val)
        return
    setattr(cfg, key, value)


def _normalize_ollama_host(raw: str) -> str:
    """Coerce an OLLAMA_HOST value into a client-side connect URL.

    Ollama documents ``OLLAMA_HOST`` for *server-side* binding, where
    ``0.0.0.0:11434`` means "listen on all interfaces". Users routinely
    copy that same env var into their shell for client work and hit
    ``WinError 10049 — the requested address is not valid in its
    context`` (Windows) or ``Cannot assign requested address`` (Linux)
    because ``0.0.0.0`` isn't a valid connect target. Rewrite the
    common bind-only forms to a loopback connect URL.
    """
    host = raw.strip()
    if not host.startswith("http"):
        host = f"http://{host}"
    # Replace 0.0.0.0 / :: in the authority section with 127.0.0.1.
    # We don't touch the path/query — just the netloc.
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(host)
    netloc = parts.netloc or parts.path  # `http://0.0.0.0:11434` style only
    if netloc:
        # netloc may have :port; preserve it.
        if netloc.startswith("0.0.0.0"):
            netloc = "127.0.0.1" + netloc[len("0.0.0.0") :]
        elif netloc.startswith("[::]"):
            netloc = "[::1]" + netloc[len("[::]") :]
        elif netloc.startswith("[0:0:0:0:0:0:0:0]"):
            netloc = "[::1]" + netloc[len("[0:0:0:0:0:0:0:0]") :]
    return urlunsplit(
        (
            parts.scheme or "http",
            netloc,
            parts.path if parts.netloc else "",
            parts.query,
            parts.fragment,
        )
    )


def load_plugin_state() -> dict[str, Any]:
    """Read ~/.athena/plugins_state.json. Returns an empty dict on missing/malformed."""
    if not PLUGINS_STATE_PATH.exists():
        return {}
    try:
        data = json.loads(PLUGINS_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_plugin_state(state: dict[str, Any]) -> None:
    """Persist plugin state. Caller owns merge semantics."""
    PLUGINS_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLUGINS_STATE_PATH.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _merge_plugin_state(plugins_cfg: dict[str, Any]) -> dict[str, Any]:
    """Overlay plugins_state.json onto plugin config from config.toml."""
    state = load_plugin_state()
    if not state:
        return plugins_cfg
    merged = dict(plugins_cfg)
    state_enabled = state.get("enabled")
    if isinstance(state_enabled, dict):
        existing_enabled = merged.get("enabled")
        if not isinstance(existing_enabled, dict):
            existing_enabled = {}
        merged["enabled"] = {**existing_enabled, **state_enabled}
    return merged
