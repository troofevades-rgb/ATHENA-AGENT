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
