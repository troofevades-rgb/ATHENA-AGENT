# T3-06R recon — skill disclosure hook + curator consumption

## (a) The single disclosure / "used" hook

A skill is *used* when its `SKILL.md` body is materialised into the
agent's context. There are two paths today, both ending in one
loader function:

- `athena/tools/skill_tools.py:skill_view` — the tool the agent
  calls to pull a skill on demand. Delegates to
  `athena.skills.manager.skill_view(name, workspace)`.
- `athena/skills/loader.py:load_body(name, workspace)` — the
  programmatic entry. Used by the auxiliary client + future
  agentic loaders.

Both ultimately read `<skill_dir>/SKILL.md`. The simplest "view"
signal is to hook `manager.skill_view` (which the `skill_view`
tool already calls) plus `loader.load_body` (for non-tool reads).
That covers both surfaces with one increment-on-success call.

The progressive-disclosure catalog
(`athena/skills/progressive_disclosure.py:build_catalog`) lists
skills in the system prompt but doesn't disclose bodies — it
shouldn't increment views (the model hasn't *seen* the skill
yet, just its one-liner description).

## (b) Where `skill_view` records today

It doesn't. There's no view counter, no last-used field, no
session correlation. Phase-16 observability tracks *tool* calls
(`tool_call_count` per tool name) so it sees that the `skill_view`
*tool* fired, but it can't tell which skill was loaded — the
`tool_name` attribute is `"skill_view"`, the skill argument is
not surfaced.

T3-06R fills the gap: a per-skill metrics file with views,
last-used, and session-correlation.

## (c) Curator decision inputs

`athena/curator/orchestrator.py` forks an agent with the
`CURATOR_REVIEW_PROMPT` text + `enabled_toolsets=["skills"]`. The
fork itself walks the skills directory, decides KEEP / DELETE /
ABSORB per skill, and emits a YAML report. The orchestrator
hands the YAML to `curator/reconciliation.py:reconcile` (compares
claim-vs-state) and `curator/reports.py:write_run` (persists
run.json + REPORT.md).

Two places to feed metrics in:

1. **Prompt addendum** — append a "Recent usage signal" section to
   `addendum` in `orchestrator.maybe_run_curator` so the fork's
   model sees per-skill view counts before making its decisions.
   Metrics *inform* the model; the existing hard rules (untouchable
   write_origin=foreground, pinned, migration-origin) still
   override.

2. **Report enrichment** — `reports.write_run` already builds a
   `summary` dict from the parsed YAML. Pull metrics in there
   (or in a sibling section of REPORT.md) so the user can see
   "skill X was never viewed in 60 days; curator decided KEEP"
   as a flag.

Both are non-invasive. Neither auto-deletes; the curator's
existing rules + the model's decision stay in charge.

## (d) Report assembly point

`athena/curator/reports.py:write_run` is the single function that
builds `summary` and writes `run.json` + `REPORT.md`. Adding a
"Usage" section there is mechanical — read the metrics file (if
present), pair each YAML decision with its `views` / `last_used`,
and append a markdown section that surfaces "never viewed" and
"stale (>30 days)" rows.

## (e) Where the user sees metrics directly

`athena/cli/skill.py` already exists with `athena skill {diff,
rollback}`. Extend with `athena skill metrics` for direct
inspection (top / stale / never-used, with `--json` for tooling).

## Plan

1. `athena/skills/metrics.py` — `SkillMetric` dataclass +
   `SkillMetricsStore` with `record_view`, `record_outcome` (opt),
   `get`, `all`, `top`, `stale`. Persist under
   `<profile_dir>/skill_metrics.jsonl` — the same path the T3-05R
   suggestion enhancer already reads.
2. Hook `manager.skill_view` and `loader.load_body` to call
   `record_view(name, session_id)` on success. Gate via
   `cfg.skill_metrics_enabled`.
3. Curator: append "Recent usage signal" to the prompt addendum;
   append a Usage section to `REPORT.md`.
4. CLI: add `athena skill metrics` subcommand.

## Cross-phase note

The metrics file format is the same one T3-05R's
`build_suggestion_fn` already reads
(`<profile_dir>/skill_metrics.jsonl`, JSON-line with `skill_name`,
`good`, `bad`, `preference_pair`). T3-06R adds the `views` /
`last_used_at` / `sessions_used_in` fields alongside; the
T3-05R reader tolerates unknown fields. No format break.
