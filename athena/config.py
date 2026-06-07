"""Configuration loading. Reads ~/.athena/config.toml; falls back to defaults."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found,unused-ignore]


from .config_sections import (
    BashConfig,
    ComputerConfig,
    CuratorConfig,
    GatewayConfig,
    OcrConfig,
    ParseltongueConfig,
    PluginsConfig,
    ProvidersConfig,
    ReviewConfig,
    SafetyConfig,
    SkillsConfig,
    UserModelConfig,
    VideoAnalysisConfig,
    VideoGenerationConfig,
    WebhookServerConfig,
)

_PRIMARY_HOME = Path.home() / ".athena"


CONFIG_DIR = _PRIMARY_HOME
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
class Config:
    model: str = "troofevades-q35:athena"
    ollama_host: str = "http://127.0.0.1:11434"
    # Ollama keep_alive: how long the model stays resident after a request.
    # None lets Ollama use its default (5 min). The voice path overrides this
    # to a longer window so the voice model isn't reloaded between spoken
    # turns. Forwarded as a top-level field by OllamaProvider.stream_chat.
    ollama_keep_alive: str | None = None
    # Per-request timeout (seconds) for the Ollama HTTP client. This is
    # the stall detector: httpx applies it as the max wait for the next
    # chunk, so a healthy token stream never trips it — only a wedged
    # daemon or a model stuck in prompt-eval does. The historical 600s
    # default means a stalled local call hangs ~10 min before failing
    # (then retries); lower it to surface stalls faster on slower setups
    # / chat transports. Keep it above your worst-case time-to-first-
    # token (big-context prompt-eval can take minutes on partial offload).
    ollama_timeout_s: float = 600.0
    # TUI color palette. One of: ``phosphor`` (classic CRT lime,
    # default), ``dusk`` (amber + deep blue), ``nord`` (cool blue/
    # slate), ``dracula`` (purple + cyan + pink), ``synthwave``
    # (hot pink + ice cyan), ``cyber`` (neon green + glitch
    # magenta). Switch live via ``/theme set <name>`` then persist
    # via ``/theme save``.
    theme: str = "phosphor"
    # Profile name under ~/.athena/profiles/<profile>/. Sessions, memory, and
    # per-profile config live here. Multiple profiles let a user keep work
    # contexts (default / personal / client-foo) separated without juggling
    # ATHENA_HOME values.
    profile: str = "default"
    # R2 stage 4: opt-in one-shot migration of legacy workspace-keyed
    # memory at ``~/.athena/projects/<slug>/memory/`` into the new
    # profile-keyed location at
    # ``<profile_dir>/memory/legacy/<workspace-slug>/``. Off by default
    # for a release so operators dogfood; flip to True in config.toml
    # to opt in. Idempotent (skips if target exists), per-workspace
    # (only migrates the active workspace's slug per session). Removal:
    # default flips to True at R2 stage 5; flag retires together with
    # the legacy ``athena.memory`` module.
    migrate_legacy_memory: bool = False
    review: ReviewConfig = field(default_factory=ReviewConfig)
    curator: CuratorConfig = field(default_factory=CuratorConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    user_model: UserModelConfig = field(default_factory=UserModelConfig)
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
    # Per-command elevation (Windows). When True, the system prompt tells the
    # agent it may prefix a single admin-needing command with `sudo` (Windows
    # 11 inline sudo) — each elevation pops a UAC prompt the user approves at
    # the machine, and output is captured back. Requires Windows `sudo` to be
    # enabled separately (Settings → System → For developers → Enable sudo →
    # Inline). Default off (standard, non-elevated).
    shell_allow_elevation: bool = False
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
    # 0.3.0 godmode: operator-supplied text appended to the end of the
    # built system prompt (after the /goal block). Mirrors the
    # hermes-agent ``agent.system_prompt`` knob and the G0DM0D3
    # reference's ``custom_system_prompt`` plumbing. Set by
    # ``/godmode apply`` to inject a jailbreak strategy; cleared by
    # ``/godmode clear``. Empty / None means no append. The env var
    # ``ATHENA_EPHEMERAL_SYSTEM_PROMPT`` wins over this config value
    # so an operator can override on-the-fly without editing config.toml.
    agent_system_prompt_append: str | None = None
    # 0.3.0 godmode: path to a JSON file of ephemeral prefill messages
    # injected into every API call after the system message and before
    # conversation history. Mirrors the hermes-agent
    # ``agent.prefill_messages_file`` knob. Messages are NEVER appended
    # to ``self.messages``, NEVER persisted to JSONL, and NEVER appear
    # in ``/save`` transcripts -- they exist only inside the provider's
    # ``stream_chat`` invocation. The model sees them as prior
    # conversation context establishing a pattern of compliance.
    #
    # Format: a JSON list of ``{"role": "user"|"assistant", "content": str}``
    # entries. Relative paths resolve against ``~/.athena/``; absolute
    # paths and ``~`` expansion are honored.
    agent_prefill_messages_file: str | None = None
    # Bash gate config (Phase 17 ShellPolicy). Nested per Phase 18.1
    # R4; legacy flat names ``bash_allowlist`` / ``bash_extra_denylist``
    # still resolve via ``Config.__getattr__`` with a deprecation
    # warning.
    bash: BashConfig = field(default_factory=BashConfig)
    # Skills subsystem config. Nested per Phase 18.1 R4; legacy flat
    # names ``skills_autoload`` / ``skills_autoload_interval`` still
    # resolve via ``Config.__getattr__`` with a deprecation warning.
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    # [safety] subsystem config. Promoted from dict[str, Any] to a
    # real dataclass in Phase 18.1 R4 stage 2. Until that promotion
    # this dict's keys were advertised in code but never consulted
    # (the SnapshotStore used its own hardcoded defaults); the
    # dataclass is now actually wired through to SnapshotStore in
    # agent/core.py + cli/snapshot.py.
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    # Hard cap on tool-call rounds per user turn. Stops runaway loops.
    max_turn_steps: int = 25
    # 0.3.0 circuit breakers -- bound the OTHER ways a turn can burn
    # tokens / money without the step cap firing:
    #
    #   * ``max_consecutive_provider_errors`` -- if the provider
    #     returns an error (provider_error chunk, transport failure,
    #     400/429/5xx after retries) N times in a row, halt the
    #     turn. The audit ticket called this out: hosted-model 400s
    #     burn input tokens on every attempt; without this guard,
    #     a misconfigured key or a model deprecation can drain a
    #     budget before the operator notices.
    #   * ``max_identical_tool_calls`` -- if the model invokes the
    #     same ``(tool_name, args)`` pair N times in a row, halt.
    #     Catches the stuck-loop pattern where the model can't
    #     interpret a tool's result and keeps calling it. Distinct
    #     calls (different args OR different tool) reset the
    #     counter, so a legitimate iterative pass (e.g. Read on
    #     three files with different paths) is unaffected.
    #
    # Set either to 0 to disable that breaker individually.
    # ``_fire_stop`` records ``circuit_breaker:provider_errors`` or
    # ``circuit_breaker:identical_tool_calls`` as the stop reason
    # so /status and the on-disk snapshot surface the trip.
    max_consecutive_provider_errors: int = 3
    max_identical_tool_calls: int = 3
    # Seconds to wait for each MCP server's startup handshake before
    # giving up and proceeding WITHOUT it. A non-responsive server must
    # never brick the whole CLI launch (it used to: the connect was
    # synchronous with a 30s-per-server stall and no feedback). Each
    # server is isolated and skipped on timeout; a per-server
    # ``startup_timeout`` key in mcp.json overrides this default for a
    # server that legitimately boots slowly.
    mcp_startup_timeout: float = 10.0
    # Narrate-without-act recovery: when a turn makes ZERO tool calls and
    # the model signs off on a future-tense intent ("I'll run the tests")
    # instead of doing it, nudge it this many times to emit the actual
    # tool call before accepting the turn as complete. A common
    # small/local-model failure that otherwise wastes the turn. 0 disables
    # (warn-only, the prior behaviour).
    narrate_reprompt_attempts: int = 1
    # Struggle-based model escalation (OFF by default). When the local
    # model gets stuck — the identical-tool-call circuit breaker would
    # trip — escalate the rest of the turn to ``routing_escalation_model``
    # instead of halting, then revert to the base model on the next turn
    # (local-first). Escalating to a hosted model sends context
    # off-machine, so this is strictly opt-in; an empty escalation model
    # is a no-op even when enabled.
    routing_enabled: bool = False
    routing_escalation_model: str = ""
    # Auto-recall (OFF by default): at the start of each turn, retrieve
    # the most semantically-similar past turns / memory entries for the
    # prompt and inject them as an ephemeral "[recalled context]" system
    # note — cross-session continuity despite a small context window.
    # Fully local (on-disk index + local embeddings), so no off-machine
    # concern; no-op without an embeddings backend. Conservative: only
    # matches at/above recall_auto_min_score are injected, capped at
    # recall_auto_k, and the note is replaced each turn (never persisted).
    recall_auto: bool = False
    recall_auto_k: int = 3
    recall_auto_min_score: float = 0.6
    # Phase 18.2 stage 3: max worker threads for parallel tool
    # dispatch. ``1`` (default) keeps the pre-Phase-18.2 serial
    # behaviour -- every tool call in a round runs one after the
    # other on the foreground thread. Set ``>1`` to opt into parallel
    # dispatch of contiguous parallel-safe batches (see
    # :attr:`athena.tools.registry.Tool.parallel_safe`); the actual
    # pool size for any given batch is
    # ``min(len(batch), parallel_tool_workers)`` so single-call
    # batches never spin up a pool. Non-parallel-safe and
    # confirmation-required tools always stay serial regardless.
    parallel_tool_workers: int = 1
    # Plugin enable map + per-plugin config slices. Promoted from
    # dict[str, Any] to PluginsConfig in Phase 18.1 R4 stage 4b. The
    # dataclass implements __getitem__ / get / __contains__ so existing
    # dict-style readers keep working without modification.
    plugins: PluginsConfig = field(default_factory=PluginsConfig)
    # Parseltongue: context-aware inference param policy. Promoted
    # from dict[str, Any] to a real dataclass in Phase 18.1 R4 stage
    # 4. See athena/agent/param_policy.py for the policy classes.
    parseltongue: ParseltongueConfig = field(default_factory=ParseltongueConfig)
    # Provider configuration (Phase 8). Promoted from dict[str, Any] to
    # ProvidersConfig in Phase 18.1 R4 stage 6. Sub-keys (now attributes
    # / per_provider slices):
    #   providers.routing     {model_name: provider_name} explicit overrides
    #   providers.<name>.host base URL for ollama / openai_compat
    #   providers.<name>.fallback  ordered list of provider names to try
    #                              when the primary's credentials are exhausted
    # The dataclass implements get/__getitem__/__contains__ so existing
    # ``(cfg.providers or {}).get(...)`` readers keep working unchanged.
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
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
    # Obsidian integration: the model-facing tools (obsidian_write /
    # obsidian_read / obsidian_append / obsidian_search / obsidian_daily)
    # operate directly on the vault as a plain folder of .md files — no
    # external CLI or plugin required. The tools are only advertised to
    # the model when obsidian_vault_path is set AND points at an existing
    # directory (a check_fn gate), so they stay invisible until configured.
    # Daily-note path is <vault>/<daily_folder>/<date>.md.
    obsidian_vault_path: str | None = None
    obsidian_daily_folder: str = ""  # subfolder for daily notes ("" = vault root)
    obsidian_daily_date_format: str = "%Y-%m-%d"
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
    # T-GOAL-VERIFY: optional shell command run after the model emits
    # GOAL ACHIEVED. Exit 0 → accept the claim; non-zero / timeout /
    # spawn failure → refuse, keep the goal active, and feed the
    # verifier's stdout+stderr back into the next synthetic turn so
    # the model has actionable feedback. Examples:
    #   goal_verifier_command = "pytest -q"
    #   goal_verifier_command = "pytest -q && mypy && ruff check ."
    # None disables the gate (default — model self-declared
    # achievement is honoured as before).
    goal_verifier_command: str | None = None
    goal_verifier_timeout_s: float = 120.0
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
    # T6-02.5: user lookup + timeline (OSINT). The user-lookup URL
    # resolves a username to a user ID + profile; the timeline URL
    # fetches that user's posts. Both use the same bearer / OAuth
    # token as social_search.
    social_user_lookup_url: str | None = None
    social_user_timeline_url: str | None = None
    social_user_timeline_max_results: int = 50
    social_user_timeline_extra_params: dict[str, Any] = field(default_factory=dict)
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
    # Computer-use subsystem config (T6-04 + T6-04R). Promoted to a
    # nested dataclass in Phase 18.1 R4 stage 3. The legacy flat
    # ``computer_*`` names still resolve via Config.__getattr__ +
    # __setattr__ shims for one release; new code should read
    # ``cfg.computer.use_enabled`` etc.
    computer: ComputerConfig = field(default_factory=ComputerConfig)
    # T6-05: native video generation. video_generate +
    # animate_image tools backed by the T5-05 media broker
    # (video_generation capability). Cost / latency guard
    # confirms before submitting any job exceeding the
    # configured thresholds — never silently spend. Outputs
    # land under video_output_dir + are hash-logged in
    # media_log.jsonl alongside.
    # Video generation broker config (T6-05). Phase 18.1 R4 stage 5
    # promoted the seven ``video_generation_*`` / ``video_backend*`` /
    # ``video_confirm_over_*`` / ``video_output_dir`` / ``video_poll_*``
    # flat fields into VideoGenerationConfig. The legacy names still
    # resolve through Config.__getattr__ + __setattr__.
    video_generation: VideoGenerationConfig = field(default_factory=VideoGenerationConfig)
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
    # Video analysis config (T4-04). Phase 18.1 R4 stage 5 promoted
    # the seven ``video_enabled`` / ``video_ffmpeg_path`` /
    # ``video_ffprobe_path`` / ``video_frames_dir`` / ``video_max_frames``
    # / ``video_default_extract`` / ``video_sampled_interval_s`` flat
    # fields into VideoAnalysisConfig. Legacy reads/writes resolve
    # through Config.__getattr__ + __setattr__.
    video_analysis: VideoAnalysisConfig = field(default_factory=VideoAnalysisConfig)
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
    browser_capture_path: str | None = None  # default <profile_dir>/browser_capture.jsonl
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
    # Text-to-speech (Discord-voice design, Phase 1). ``tts_backend``
    # pins a registered TTS backend by name (e.g. "tts_piper_local",
    # "tts_stub"); "" lets the resolver pick the first available local
    # backend. ``tts_voice`` is the backend-specific voice — for
    # tts_piper_local it's the path to a Piper ``.onnx`` voice model.
    # Both empty by default → TTS is "unavailable" until a voice is set,
    # and the synthesis path degrades gracefully.
    tts_backend: str = ""
    tts_voice: str = ""
    # Kokoro (tts_kokoro_local) — a far more natural neural voice, still
    # on-device. Unlike Piper, the "voice" is a NAME, not a file path:
    # af_heart, af_bella, am_michael, bf_emma, ... (af_/am_ = American
    # female/male, bf_/bm_ = British). Model + voice-pack files default to
    # ~/.athena/voices/{kokoro-v1.0.onnx,voices-v1.0.bin}; override only to
    # relocate them. Backend stays "unavailable" until both files exist.
    kokoro_voice: str = "af_heart"
    kokoro_model_path: str | None = None
    kokoro_voices_path: str | None = None
    # Discord-voice: optional per-voice chat model override. Empty → voice
    # turns use the main ``model``. Set to a fast *non-thinking* Ollama
    # model (e.g. "troofevades:latest", "glm4:9b") to keep spoken replies
    # snappy: a thinking model emits a <think> block before every answer,
    # which is stripped from speech but still costs ~12-20s of generation.
    # Same provider as ``model`` → the swap is just the model string
    # (cf. athena/commands/model.py:_switch_model). The coding agent keeps
    # using ``model`` unchanged.
    voice_model: str = ""
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
    # OCR subsystem (T4-06). Phase 18.1 R4 stage 5 promoted the five
    # ``ocr_*`` flat fields into OcrConfig. Legacy reads/writes
    # resolve through Config.__getattr__ + __setattr__.
    ocr: OcrConfig = field(default_factory=OcrConfig)

    def __post_init__(self) -> None:
        """Coerce legacy dict-shape inputs into their promoted dataclass
        forms.

        Test fixtures and a long tail of historical call sites build
        ``Config(providers={"routing": {...}, "<name>": {...}})`` --
        i.e. they pass a plain dict where the dataclass-generated
        ``__init__`` would otherwise store it verbatim, leaving the
        runtime resolver (which now does attribute access) staring at
        the wrong type. Convert on the spot so the field-type
        annotation stays accurate.
        """
        if isinstance(self.providers, dict):
            # Bypass __setattr__ so we don't trip the legacy-map shim
            # on something that is plainly not a legacy flat name.
            object.__setattr__(self, "providers", ProvidersConfig.from_dict(self.providers))

    def __getattr__(self, name: str) -> Any:
        """Resolve legacy flat field names to their new nested locations.

        Phase 18.1 R4 promoted several subsystems' flat fields into
        nested dataclasses (``cfg.bash_allowlist`` -> ``cfg.bash.allowlist``,
        ``cfg.skills_autoload`` -> ``cfg.skills.autoload``, etc.). For one
        release the legacy names keep working but emit a deprecation
        warning so callers can update at their own pace.

        Important: ``__getattr__`` is only called when normal attribute
        lookup fails, so this never shadows the actual nested dataclass
        attributes (``cfg.bash``, ``cfg.skills``) -- those resolve via the
        dataclass-generated ``__init__`` normally and never reach here.
        """
        mapping = _LEGACY_FIELD_MAP.get(name)
        if mapping is None:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        import warnings as _warnings

        nested_name, sub_name = mapping
        _warnings.warn(
            f"Config.{name} is deprecated; read cfg.{nested_name}.{sub_name} "
            "instead (Phase 18.1 R4 nested-config migration).",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(getattr(self, nested_name), sub_name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Route legacy flat-name writes to their new nested locations.

        Test fixtures commonly mutate Config via
        ``cfg.computer_use_enabled = True`` etc. After the R4 promotion
        those flat names no longer correspond to fields; without this
        shim such writes would create *new* attributes on the Config
        instance, shadowing the nested dataclass and silently breaking
        canonical readers that go through ``cfg.computer.use_enabled``.

        Unlike :meth:`__getattr__`, this DOESN'T warn -- once a caller
        emits a deprecation warning on read, double-warning on every
        corresponding write is noise. The plain read-side warning is
        enough signal.
        """
        mapping = _LEGACY_FIELD_MAP.get(name)
        if mapping is not None:
            nested_name, sub_name = mapping
            nested = self.__dict__.get(nested_name)
            if nested is not None:
                setattr(nested, sub_name, value)
                return
            # Nested instance not yet constructed (e.g. during the
            # dataclass-generated __init__, before all fields are set).
            # Fall through to the normal setattr so the bookkeeping
            # works; the dataclass __init__ will populate the nested
            # instance shortly.
        super().__setattr__(name, value)


# Deprecation surface moved to athena/config_deprecations.py 2026-06-01
# as part of the consolidation pass. The legacy-field map, dedup state,
# emit helper, and public reader functions all live there now. The
# names are re-exported here so callers importing from athena.config
# (the existing public surface) keep working without churn.
from .config_deprecations import (
    _DEPRECATION_WARNED as _DEPRECATION_WARNED,
)
from .config_deprecations import (
    _LEGACY_FIELD_MAP as _LEGACY_FIELD_MAP,
)
from .config_deprecations import (
    _emit_deprecation as _emit_deprecation,
)
from .config_deprecations import (
    reported_deprecations as reported_deprecations,
)
from .config_deprecations import (
    reset_deprecation_dedup as reset_deprecation_dedup,
)

# Sections that legitimately accept arbitrary sub-keys (plugin names,
# provider names, routing maps) — never flag their contents.
_FREE_FORM_SECTIONS: frozenset[str] = frozenset({"plugins", "providers"})


def _find_key_line(path: Path, section: str, key: str) -> int | None:
    """Best-effort: line number where ``key =`` appears under
    ``[section]`` in the raw TOML (tomllib doesn't expose positions)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    header = re.compile(r"^\s*\[([^\]]+)\]\s*$")
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
    in_section = False
    for i, line in enumerate(lines, 1):
        m = header.match(line)
        if m:
            in_section = m.group(1).split(".")[0].strip() == section
            continue
        if in_section and key_re.match(line):
            return i
    return None


def _validate_section_placement(data: dict[str, Any], cfg: Config, path: Path) -> None:
    """Guard the TOML "twice-hit" footgun.

    A bare key written AFTER a ``[section]`` header is folded into that
    section by TOML — so::

        [skills]
        autoload = true
        model = "..."   # <- this is skills.model, NOT top-level model

    silently drops the value the user meant to set at top level. Detect
    a known TOP-LEVEL Config field appearing inside a known fixed-schema
    section (where it isn't a valid field of that section) and raise a
    clear, located error instead of ignoring it. Free-form sections
    (``[plugins]`` / ``[providers]``) accept arbitrary sub-keys and are
    skipped.
    """
    top_level = {f.name for f in fields(cfg)}
    for section, table in data.items():
        if not isinstance(table, dict) or section in _FREE_FORM_SECTIONS:
            continue
        sec_default = getattr(cfg, section, None)
        if not is_dataclass(sec_default):
            continue  # unknown / free-form table — not ours to police
        sec_fields = {f.name for f in fields(sec_default)}
        misplaced = [k for k in table if k in top_level and k not in sec_fields]
        if misplaced:
            key = misplaced[0]
            line = _find_key_line(path, section, key)
            loc = f"{path}:{line}" if line else str(path)
            raise ValueError(
                f"{loc}: '{key}' is a top-level setting but appears under "
                f"[{section}] — TOML folds any key written after a [section] "
                f"header into that section, so the value is lost. Move "
                f"'{key}' ABOVE the first [section] header (or delete it from "
                f"[{section}] if it was meant to be a {section} setting)."
            )


def load_config() -> Config:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    cfg = Config()
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
        # Catch the section-header footgun on the user's raw structure
        # before any back-compat folding mutates it.
        _validate_section_placement(data, cfg, CONFIG_PATH)
        # Back-compat: accept old key name and map it forward
        if "auto_approve_bash" in data and "auto_approve_tools" not in data:
            data["auto_approve_tools"] = data.pop("auto_approve_bash")
            _emit_deprecation(
                CONFIG_PATH,
                "auto_approve_bash",
                f"warning: {CONFIG_PATH}: 'auto_approve_bash' is deprecated; "
                "rename to 'auto_approve_tools'.",
            )
        # Phase 18.1 R4: legacy flat keys (skills_autoload, bash_allowlist,
        # ...) are accepted with a one-line stderr note and folded into
        # their new nested home. ``[skills]`` and ``[bash]`` tables take
        # precedence when both shapes appear -- explicit new-shape wins.
        for legacy_key, (nested_name, sub_name) in _LEGACY_FIELD_MAP.items():
            if legacy_key not in data:
                continue
            nested_block = data.get(nested_name)
            already_set_in_new_shape = isinstance(nested_block, dict) and sub_name in nested_block
            if already_set_in_new_shape:
                data.pop(legacy_key)
                continue
            data.setdefault(nested_name, {})[sub_name] = data.pop(legacy_key)
            _emit_deprecation(
                CONFIG_PATH,
                legacy_key,
                f"warning: {CONFIG_PATH}: '{legacy_key}' is deprecated; "
                f"move to [{nested_name}] table with key '{sub_name}'.",
            )
        # Phase 18.1 R4 stage 4b: PluginsConfig needs custom TOML
        # translation. The block has two layers -- a fixed ``enabled``
        # sub-table (plugin_name -> bool) plus arbitrary ``<name>``
        # sub-tables (per-plugin config slice). Translate it explicitly
        # here BEFORE the generic _assign_field loop so the loop's
        # dataclass-merge logic doesn't try to setattr() arbitrary
        # plugin names onto the PluginsConfig dataclass.
        plugins_block = data.pop("plugins", None)
        if isinstance(plugins_block, dict):
            enabled_block = plugins_block.pop("enabled", None)
            if isinstance(enabled_block, dict):
                cfg.plugins.enabled.update({k: bool(v) for k, v in enabled_block.items()})
            for plugin_name, plugin_cfg in plugins_block.items():
                if isinstance(plugin_cfg, dict):
                    cfg.plugins.per_plugin[plugin_name] = dict(plugin_cfg)
        # Phase 18.1 R4 stage 6: ProvidersConfig translation -- same
        # shape pattern as PluginsConfig. ``[providers.routing]`` is
        # a fixed sub-table of {model: provider_name}; any other
        # ``[providers.<name>]`` sub-table is a per-provider slice.
        # Translate explicitly here BEFORE the generic _assign_field
        # loop so it doesn't try to setattr() arbitrary provider names
        # onto the ProvidersConfig dataclass.
        providers_block = data.pop("providers", None)
        if isinstance(providers_block, dict):
            routing_block = providers_block.pop("routing", None)
            if isinstance(routing_block, dict):
                cfg.providers.routing.update(
                    {
                        k: v
                        for k, v in routing_block.items()
                        if isinstance(k, str) and isinstance(v, str)
                    }
                )
            for provider_name, provider_cfg in providers_block.items():
                if isinstance(provider_cfg, dict):
                    cfg.providers.per_provider[provider_name] = dict(provider_cfg)
        for k, v in data.items():
            if hasattr(cfg, k):
                _assign_field(cfg, k, v)
    # Merge plugin enable state from the machine-managed sidecar file.
    _merge_plugin_state(cfg.plugins)
    if env := os.environ.get("ATHENA_MODEL"):
        cfg.model = env
    if env := os.environ.get("OLLAMA_HOST"):
        cfg.ollama_host = _normalize_ollama_host(env)
    # Apply the configured TUI theme so the banner + every subsequent
    # ``ui.*`` call render in the user's chosen palette. Done here
    # instead of at import-time so a bad theme name surfaces at
    # config-load (clearer error) rather than partway through a
    # session. Unknown theme falls back silently to ``phosphor``.
    if cfg.theme and cfg.theme != "phosphor":
        try:
            from . import ui as _ui

            _ui.set_theme(cfg.theme)
        except (KeyError, ImportError):
            pass  # invalid theme name; keep default
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


def _merge_plugin_state(plugins_cfg: PluginsConfig) -> None:
    """Overlay plugins_state.json onto the PluginsConfig in place.

    R4 stage 4b: signature changed from ``dict -> dict`` to
    ``PluginsConfig -> None`` (mutation). The sidecar file is
    machine-managed by ``athena plugins {enable,disable}``; merging
    it in place keeps every caller's reference to ``cfg.plugins``
    valid without any swap-the-reference dance.
    """
    state = load_plugin_state()
    if not state:
        return
    state_enabled = state.get("enabled")
    if isinstance(state_enabled, dict):
        plugins_cfg.enabled.update({k: bool(v) for k, v in state_enabled.items()})
