# REFACTOR_PLAN.md

A staged refactor plan for the five architectural seams the cross-subsystem
audit surfaced, plus a phase-continuation proposal anchored against the
phase history documented in `CHANGELOG.md` and `CLAUDE.md`.

This document is intentionally specific (file paths, line ranges, names of new
modules) and incremental (every step is reversible; no big-bang rewrites). It
is also intentionally honest about effort and the order in which to take the
work — Refactor 5 is the cheapest, Refactor 4 the cheapest after that, and
Refactor 1 the most expensive. Skip what doesn't pay for itself.

---

## Where the phases stand

Phases 0 through 17 shipped as the `v0.2.0` release (2026-05-19, see
`CHANGELOG.md`). Post-v0.2.0 work is task-ID-driven (T1-..T7-..) rather than
phase-numbered; the `[Unreleased]` block in CHANGELOG.md is the de-facto
roadmap. Effectively **no Phase N is in flight as a numbered milestone** —
the current working surface is the audit cleanup + recent feature work
(post-Task-2, audit Rounds 1–9, /help fix, xAI provider).

The one phase-numbered item *still pending in code* is:

- **Phase 14 (memory migration)**: profiles are isolated, but `memory/__init__.py`
  and `memory/store.py` both still carry the comment "Phase 14 will migrate
  them" referring to the agent's legacy workspace-keyed memory reads. Profile
  isolation shipped; memory-API unification did not. That's the same gap
  Refactor 2 closes.

No `Phase 18` or higher is mentioned anywhere in the tree. The
phase-continuation section at the end of this document proposes what
**Phase 18 (Mechanical correctness sweep)** should cover.

---

## Refactor 5 — Retire `athena/hooks.py` in favor of plugins/

**Status:** smallest, cheapest, highest signal. Recommended first.

**Problem:** `athena/hooks.py` (Phase 0, settings.json-driven shell hooks) and
`athena/plugins/` (Phase 5, `Plugin` ABC) both fire on tool calls. CLAUDE.md
explicitly acknowledges the overlap: "Both run; plugins layer on top." There
is no guidance on which to use when; new contributors have to discover by
experiment.

**Plan:**

1. **Inventory current `settings.json` `hooks` usage.** Search `~/.athena/`
   and `<workspace>/.athena/` example fixtures for `"hooks":` blocks. Document
   each event class (`PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`)
   and what users typically wire to it.

2. **Build a `ShellHookPlugin`** under `athena/plugins/bundled/shell_hook/` that
   reads the same `settings.json` `hooks` block and runs the configured shell
   command on the equivalent plugin hook. Wire it once; it covers every event
   from the legacy module.

3. **Mark `athena/hooks.py` deprecated.** Add a one-line deprecation warning
   at module import: `warnings.warn("athena.hooks is deprecated; use plugins
   instead", DeprecationWarning)`. Keep the file shimming the load to
   `ShellHookPlugin` so existing user configs continue to work.

4. **One release later, remove `athena/hooks.py`.** The shim approach means
   no user-visible behavior change in the deprecation release.

**Files touched:**
- `athena/hooks.py` (deprecate; eventually delete; ~172 lines)
- `athena/plugins/bundled/shell_hook/plugin.py` (new, ~120 lines)
- `tests/test_hooks.py` (re-aim at plugin)
- CLAUDE.md (drop the "Both run" caveat after deletion)

**Effort:** ~3 hours. **Risk:** low — the plugin path is well-trodden; the
shim preserves backward compat for one release.

---

## Refactor 4 — Decompose `Config` into nested per-subsystem classes

**Status: Stage 1 LANDED** (commit on PR #12). SkillsConfig + BashConfig
pilot promoted; `__getattr__` shim + TOML loader handle both shapes; agent,
shell tool, and sandbox runner read through the nested dataclasses
directly. Stages 2-5 below remain to do.

**Problem:** `athena/config.py:Config` is a 40+ flat-field dataclass that's
already half-decomposed (it has `review: ReviewConfig`, `curator: CuratorConfig`,
`gateway: GatewayConfig`, `user_model: UserModelConfig` as nested dataclasses,
plus `safety: dict[str, Any]`, `providers: dict[str, Any]`, `plugins: dict[str,
Any]` as ad-hoc dicts). New subsystems just bolt another flat field on. Six
subsystems' fields are currently typed `dict[str, Any]` because formalizing
them would mean another nested dataclass and the current style is inconsistent.

**Plan:**

1. **Standardize on nested dataclasses for every subsystem.** One module per
   subsystem-config under `athena/config/` (turn the single `config.py` into a
   package). Each module owns its own dataclass. The root `Config` aggregates
   them.

   ```
   athena/config/__init__.py        # Config aggregate + load_config
   athena/config/review.py           # already-present ReviewConfig
   athena/config/curator.py          # already-present CuratorConfig
   athena/config/gateway.py          # already-present GatewayConfig
   athena/config/user_model.py       # already-present
   athena/config/safety.py           # NEW: SafetyConfig (was dict)
   athena/config/providers.py        # NEW: ProvidersConfig (was dict)
   athena/config/plugins.py          # NEW: PluginsConfig (was dict)
   athena/config/parseltongue.py     # NEW: ParseltongueConfig (was dict)
   athena/config/skills.py           # NEW: SkillsConfig (skills_autoload, ...)
   athena/config/computer.py         # NEW: ComputerConfig (computer_*, ...)
   athena/config/ocr.py              # NEW: OcrConfig (ocr_*, ...)
   athena/config/video.py            # NEW: VideoConfig (video_*, ...)
   athena/config/bash.py             # NEW: BashConfig (bash_allowlist, ...)
   ```

2. **Backward-compat shim via `__getattr__`.** For one release, `Config`'s
   `__getattr__` resolves legacy flat names: `cfg.skills_autoload` returns
   `cfg.skills.autoload`. Emits a `DeprecationWarning` so callers update.

3. **Migrate the TOML loader.** `load_config` accepts both shapes — `[skills]`
   table for the new layout, `skills_autoload = true` at root level for the
   old one. After one release, drop the flat shape.

4. **Sequence by subsystem risk:**
   1. **LANDED** -- SkillsConfig + BashConfig pilot. Single commit;
      proved the pattern (`__getattr__` shim + TOML loader mapping).
   2. **LANDED** -- SafetyConfig promotion. Replaced
      `cfg.safety: dict[str, Any]` with a real dataclass AND wired it
      through to `SnapshotStore` (the dict's keys had been advertised
      in code but never actually consulted -- the retention policy in
      the user's TOML was a promise the code didn't keep until R4
      stage 2). The duplicate `extra_denylist` key was dropped (the
      canonical one lives in `BashConfig`).
   3. **LANDED** -- ComputerConfig promotion. Twelve flat ``computer_*``
      fields promoted to a single nested dataclass. Required adding
      ``Config.__setattr__`` (alongside the read-side ``__getattr__``)
      so test fixtures' legacy ``cfg.computer_X = Y`` writes route to
      the nested instance -- without it, those writes would create flat
      shadow attributes and silently break canonical readers. Six
      production call sites migrated to ``cfg.computer.X``; eight test
      cfg helpers consolidated to the new shape.
   4. **LANDED** -- ParseltongueConfig + PluginsConfig promotions.
      Stage 4a: ``cfg.parseltongue: dict[str, Any]`` -> real dataclass;
      ``policy_from_config`` accepts dataclass + dict + SimpleNamespace.
      Stage 4b: ``cfg.plugins: dict[str, Any]`` -> PluginsConfig with
      ``enabled`` (the override map) split from ``per_plugin`` (per-plugin
      config slices). The dataclass implements ``__getitem__`` /
      ``get`` / ``__contains__`` / ``as_dict_for_loader`` shims so
      existing dict-style readers and the plugin loader's dict-shaped
      contract both keep working. ``_merge_plugin_state`` signature
      changed from ``dict -> dict`` to ``PluginsConfig -> None``
      (in-place mutation) so call sites don't need to swap a reference.
   5. OcrConfig, VideoConfig (the `ocr_*` and `video_*` prefixes;
      least-touched, smallest blast radius).
   6. ProvidersConfig (touches routing + credential pool -- leave for
      last because the routing dict has more user-visible shape than
      the other dicts).

**Files touched:**
- `athena/config.py` (904 lines) → `athena/config/` package
- ~12 callers per subsystem update their attribute path

**Effort:** ~6 hours (1 hour per nested config). **Risk:** medium — many
callers, but the `__getattr__` shim absorbs the migration window.

---

## Refactor 3 — Unify `athena/commands/` and `athena/cli/`

**Problem:** Slash commands (`athena/commands/`) and CLI subcommands
(`athena/cli/`) are parallel structures. Most commands appear in both with
different shapes; some (`athena/commands/computer.py` and
`athena/commands/board.py`) are listed in `__main__._SUBCOMMANDS` as both
surfaces simultaneously, which is the right idea but applied inconsistently.

**The right shape** is: one *handler* module per command, with two thin
adapter functions — one for the slash surface, one for the CLI surface — both
delegating to a common core. The core does the work; the adapters do
arg-parsing and output formatting.

**Plan:**

1. **Define the canonical handler shape** in a new
   `athena/commands/_handler.py`:

   ```python
   class CommandHandler(Protocol):
       name: str
       slash_help: str       # short string for SLASH_HELP
       cli_help: str         # for argparse

       def core(self, agent, **kwargs) -> CommandResult: ...
       def slash_args(self, raw: str) -> dict: ...     # parse "/foo arg" → kwargs
       def cli_parser(self, parser: argparse.ArgumentParser) -> None: ...
   ```

2. **Migrate `mcp_cmd` as the pilot.** It's already in both
   `athena/commands/mcp_cmd.py` (slash) and `athena/cli/mcp.py` (CLI) with
   essentially the same logic; consolidate into `athena/commands/mcp.py`
   following the new shape, then delete `athena/cli/mcp.py` once the
   `_SUBCOMMANDS` entry points at the consolidated module.

3. **Migrate remaining duplicates** in order of how easily they fit:
   `computer`, `board`, `update` are already in both. Then `cron`, `mcp`,
   `skill`, `memory`, `profile`, `webhook`, `status`, `snapshot`,
   `checkpoint`, `audit`, `verify`, `cache`, `recall`, `theme`.

4. **Drop `athena/cli/`** when its modules become thin
   "import-and-call" wrappers. Wire `_SUBCOMMANDS` at
   `athena/__main__.py:97-136` directly to the handler module.

5. **Slash-only commands** (`/help`, `/clear`, `/dump`, `/cost`, `/save`,
   `/plan`, `/steer`, `/queue`, `/goal`, `/subgoal`, `/loop`, `/hooks`,
   `/tools`, `/resume`, `/compact`) just don't implement `cli_parser`.

6. **CLI-only commands** (`reindex`, `import-from-hermes`, `train`, `eval`,
   `batch`, `acp`, `gateway`, `delegate`, `proxy`, `image-demo`, `wordmark`,
   `cleanup-blobs`) just don't implement `slash_args`.

**Files touched:**
- `athena/commands/_handler.py` (new, ~80 lines protocol + adapter helpers)
- ~25 handler modules updated to the new shape
- `athena/cli/` shrinks to thin wrappers; ultimately deleted
- `athena/__main__.py:97-136` `_SUBCOMMANDS` table simplified

**Effort:** ~12 hours (~30 min per command on average). **Risk:** medium —
the pilot proves the shape; subsequent migrations are mechanical.

---

## Refactor 2 — Finish Phase 14 memory migration

**Problem:** Two parallel memory APIs (legacy workspace-keyed in
`memory/__init__.py`, profile-keyed in `memory/providers/`). The agent's
system-prompt build reads via the legacy API; MCP server tools and the
`athena memory` CLI read via the new provider. Round 4 of the audit added
dual-write in `tools/memory_tools.py` to paper over the gap. CLAUDE.md says
Phase 14 will migrate; profiles shipped but the memory half did not.

**Plan:**

1. **Make `BuiltinFileProvider` the source of truth on disk.** Move the
   ~/.athena/projects/<slug>/memory/ tree into the profile dir on first
   load: `~/.athena/profiles/<profile>/memory/legacy/<workspace-slug>/`.
   Per-profile-per-workspace, properly isolated.

2. **Wire the agent's system-prompt read path through the provider.**
   `agent/core.py:793-808` (the `load_memory_index` call) currently uses
   `from ..memory import load_memory_index`. Change to
   `from ..memory.store import load_index` and pass profile + workspace as
   filter keys (provider learns the workspace dimension).

3. **Deprecate the workspace-keyed legacy functions.** `memory/__init__.py`'s
   `write_memory`, `delete_memory`, `list_memories`, `load_memory_index` each
   delegate to the provider but emit a one-line DeprecationWarning. Tools
   that still use them migrate one at a time.

4. **Drop the Round-4 dual-write** in `tools/memory_tools.py` once every
   reader is on the provider. The dual-write was always a transitional
   patch; this is the patch graduating to a real fix.

5. **Migrate the audit/snapshot infra.** `migration/memory_exporter.py`
   already targets the per-profile location; keep it untouched. The
   curator already reads via the provider.

**Files touched:**
- `athena/memory/__init__.py` (deprecate functions, ~370 lines → ~80)
- `athena/memory/store.py` (provider learns workspace dimension)
- `athena/memory/providers/builtin_file.py` (workspace key in schema)
- `athena/agent/core.py:793-808` (read via store)
- `athena/tools/memory_tools.py` (drop dual-write — net `-80` lines)
- `athena/migration/memory_exporter.py` (validate still works)
- One-shot data migration script at `athena/profiles/migration.py`

**Effort:** ~8 hours including the data migration + tests. **Risk:**
medium-high — the in-disk move is a one-way operation. Land behind a
`migrate_memory: bool = False` flag for one release; flip the default after
operator dogfooding.

---

## Refactor 1 — Split `athena/agent/core.py` (2005 lines)

**Status:** most expensive; do last. Worth doing iff Refactors 4 and 2 land
first (Config decomposition makes the split lines cleaner; memory migration
removes one of the heaviest legacy hookups).

**Problem:** `agent/core.py` is 2005 lines. `Agent.__init__` alone runs from
line 277 to line 575 — session lifecycle, history loading, browser session,
plugin hooks, cancel hooks, skill watcher init, parseltongue policy load,
system-prompt build. Touching `run_turn` requires reading the close() path;
touching close() requires reading init. Cross-cutting bugs (cancel-hook leak,
session-id detach on history-load failure) have to be surgically chased.

**Plan:**

1. **Define three classes, file-by-file:**

   - `agent/lifecycle.py` (~600 lines): `AgentLifecycle` — owns `__init__`,
     `close`, `reset`, `reload_goal`, `reload_skills`, `_build_system`,
     `_build_plugin_hooks`, `_run_session_start_hooks`,
     `_init_cross_session_cache`. Pure setup + teardown. No `run_turn`,
     no streaming, no cancel.

   - `agent/runtime.py` (~900 lines): `AgentRuntime` — owns `run_turn`,
     `run_until_done`, `_run_turn_inner`, `_stream_one`, `_handle_tool_call`,
     `_persist_message`, `_maybe_compress_context`, `_maybe_fire_review`,
     `_wait_for_background_review`, `_messages_with_cache_markers`,
     `_start_progress_ticker`, `_fire_stop`. The hot loop and everything
     it touches.

   - `agent/core.py` (~300 lines after split): `Agent` — composes
     `AgentLifecycle` and `AgentRuntime` via inheritance OR composition. The
     thin glue + public surface (`Agent.fork`, `Agent.last_assistant_message`,
     `Agent.tool_call_trace`, `Agent.write_status_snapshot`).

2. **Choose inheritance vs composition.** Inheritance is easier for the
   migration (no method-call rewiring), but composition is the right
   long-term shape (lifecycle and runtime become independently testable).
   Pilot with inheritance; switch to composition once everything compiles.

3. **Move `_cancel_in_flight` to lifecycle** (it's a setup-time hook
   registration, not a runtime call). Move `_persist_goal_state` to
   `agent/goal_integration.py` so the goal subsystem owns its own
   persistence.

4. **Preserve every public method on the `Agent` namespace** so external
   callers (gateway, CLI, tests) don't have to change. The split is purely
   internal organization.

5. **Migrate tests in place.** `tests/agent/` already mirrors the split
   (`test_core.py`, `test_fork.py`, etc.); add `test_lifecycle.py` and
   `test_runtime.py` that target the new modules directly. Existing tests
   keep passing through the composed `Agent`.

**Files touched:**
- `athena/agent/core.py` (2005 → ~300 lines)
- `athena/agent/lifecycle.py` (new, ~600)
- `athena/agent/runtime.py` (new, ~900)
- `athena/agent/goal_integration.py` (new, ~100)
- `tests/agent/` adds two test files

**Effort:** ~16 hours (the largest of the five). **Risk:** medium — every
caller talks to `Agent`, not its internals, so the public surface stays
identical. Risk is in subtle ContextVar / threading interactions that the
current monolithic init carefully orchestrates.

---

## Phase continuation

The phase line went 0 → 17 ending with "mechanical safety." Post-v0.2.0 work
moved to task-IDs (T1-..T7-..). The natural next phase number is **Phase
18 — Mechanical correctness**, which captures the audit cleanup the recent
PR landed plus the architectural debt this refactor plan addresses.

### Phase 18 — Mechanical correctness (proposed)

A consolidation phase: pay down the architectural debt the v0.2.x audits
surfaced before the next user-visible feature cluster. Three workstreams:

- **18.1 Architectural seams** — the five refactors above, in order
  Refactor 5 → 4 → 3 → 2 → 1.
- **18.2 Audit cleanup** — finish the audit items deliberately skipped during
  Rounds 1–9: `_is_goal_loop_active` fail-open documentation (verify the
  pinning test is correct), `SessionRouter.resolve` SQLite to_thread (the one
  that broke `test_burst_to_same_session_merges_into_pending`; needs a
  different approach), webhook `threading.Lock` → `asyncio.Lock` migration
  (if the lock contention ever becomes a measured problem).
- **18.3 README.md drift** — wrong default model, deprecated
  `auto_approve_bash`, references to `athena/agent.py` (file moved to
  `agent/core.py`), incomplete slash-command list. Substantial voice/structure
  work; needs operator review.

### Phase 19 (speculative) — Provider broker generalization

`providers/__init__.py:best_provider_for(needs, prefer)` already exists but
isn't used for runtime routing — it's only consulted by `T6-02 social
routing`. The provider broker could become the default model resolver,
making `cfg.model = "ollama/troofevades-q35"` truly mean "I prefer this; fall
back according to capability." Sketch: introduce `cfg.model_intent` (a set of
capabilities the agent needs this turn — `{"tool_calls", "vision"}`); the
broker picks the cheapest provider that covers the intent. Useful once
multimodal turn-by-turn switching is a real workflow.

### Phase 20 (speculative) — Curator as a continuous loop

Today the curator is a 7-day batch pass. Phase 20 could promote it to an
event-driven loop watching the background_review fork's outputs in real
time, consolidating skills/memories the moment the review identifies a
candidate. The watcher infrastructure exists (`skills/watcher.py`); the
plumbing would be `review/orchestrator.py` posting events to a `curator/
queue.py`.

---

## Suggested execution order

If the operator green-lights the plan, the sequence I'd take is:

1. **Refactor 5** (hooks → plugins). ~3 hr. Lowest risk, immediate
   conceptual clarity, unblocks "where do I write a custom audit hook?"
   for future contributors.

2. **Refactor 4 stage 1** (SafetyConfig, BashConfig, SkillsConfig,
   ComputerConfig). ~3 hr. Establishes the pattern; subsequent nested
   configs follow mechanically.

3. **Refactor 3 pilot** (mcp_cmd consolidation). ~1 hr. Proves the
   handler shape.

4. **Refactor 2** (memory migration). ~8 hr. Highest-impact correctness
   win; closes the dual-write loop from Round 4.

5. **Refactor 3 rollout** (remaining ~24 handlers). ~11 hr. Mechanical.

6. **Refactor 4 stage 2** (remaining nested configs). ~3 hr.

7. **Refactor 1** (agent/core.py split). ~16 hr. Save for last;
   benefits from the cleaner Config + memory shapes.

Total: ~45 hours of focused work, spread across 6–8 weeks of operator-
review cadence. Every step is independently shippable.

---

## What this plan does NOT cover

- **README.md drift.** Substantial voice/structure work; better done as a
  dedicated docs pass after Phase 18.3.
- **Test infrastructure rework.** The current pytest layout is good; nothing
  here changes how tests are organized.
- **Performance hotspots.** The audit's responsiveness fixes (Rounds 2–4)
  covered the immediate bottlenecks. A deeper performance pass belongs in
  its own phase (Phase 21?) once the architectural surface is stable.
- **Provider broker generalization** (Phase 19) and **continuous curator**
  (Phase 20) — speculative; depend on user-facing signals that the current
  designs are bottlenecks.

---

*Drafted from the cross-subsystem audit conducted during the
`parseltongue-and-resumability` branch work, PR #12.*
