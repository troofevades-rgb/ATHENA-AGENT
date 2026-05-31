"""Phase 17.5 — guard against new raw write sites in athena/.

Every agent-driven mutation should route through
:mod:`athena.safety.mutation` (which snapshots + audits). This test
holds the line at today's surface: the set of athena modules that
still call ``Path.write_text`` / ``Path.write_bytes`` / ``open(...,
"w")`` is frozen as an explicit allowlist. New code that introduces
an unblessed raw write fails this test until either the call is
routed through ``snapshot_and_record`` or the module is added to
the allowlist with a one-line justification.

When you genuinely need to add a module: prefer routing through
``snapshot_and_record``. Only add to the allowlist when the write
is a non-mutation (cache files, append-only logs, atomic config
writes that are themselves the audit substrate).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ATHENA_ROOT = REPO_ROOT / "athena"

# Modules whose raw writes are intentional and not subject to the
# snapshot+audit rule. Each entry is a path relative to the repo
# root. Frozen as of Phase 17.5 commit.
ALLOWLIST: frozenset[str] = frozenset(
    {
        "athena/__main__.py",  # CLI entry; doesn't mutate user content
        "athena/agent/checkpoints.py",  # rollback marker JSONL append + audit log append (T3-03)
        "athena/agent/core.py",  # status snapshot writer (atomic JSON view)
        "athena/cli/train.py",  # trainer dumps datasets to disk
        "athena/config.py",  # atomic config writes
        "athena/cron/delivery.py",  # cron task state journal
        "athena/curator/reports.py",  # curator emits its own report files
        "athena/gateway/platforms/imessage.py",  # platform-local message buffers
        "athena/gateway/platforms/signal.py",  # platform-local message buffers
        "athena/gateway/platforms/slack.py",  # platform-local message buffers
        "athena/goal/invariant.py",  # invariant register (append-only)
        "athena/mcp/oauth.py",  # atomic OAuth token file
        "athena/memory/providers/builtin_file.py",  # public writes routed through snapshot; helpers refresh index
        "athena/migration/config_translator.py",  # one-shot hermes->athena migration
        "athena/migration/mcp_translator.py",  # one-shot hermes->athena migration
        "athena/migration/memory_exporter.py",  # exports legacy memory to disk
        "athena/migration/report.py",  # migration report
        "athena/migration/sessions_importer.py",  # imports legacy sessions
        "athena/migration/skills_mapper.py",  # one-shot hermes->athena migration
        "athena/cache/cross_session.py",  # cross-session prefix-cache index JSON (operational metadata, not user content) (T5-06)
        "athena/goal/state.py",  # T5-07 goal_state.json — machine-managed bookkeeping for the active /goal loop (status/turns/subgoals), not user content
        "athena/recall/vector_store.py",  # T6-01 vectors.json — machine-managed embedding index (operational metadata, not user content)
        "athena/computer/audit.py",  # T6-04 computer_audit.jsonl — append-only audit log of computer-use actions (operational metadata)
        "athena/videogen/job.py",  # T6-05 media_log.jsonl append + writing the fetched video to <video_output_dir> (a generated artifact + provenance log, not an agent-driven mutation of user content)
        "athena/videogen/backends/stub_local.py",  # T6-05 stub backend writes a placeholder MP4 to the outputs dir (synthetic; same provenance trail as a real backend's fetch())
        "athena/update/apply.py",  # T6-07 update_state.json — machine-managed prior-version record for --rollback (operational metadata, not user content)
        "athena/computer/tools.py",  # T6-04.4 follow-up — screenshots written to <profile_dir>/screenshots/<ts>-<sha8>.bmp instead of inlined as base64 (the original inline path blew local model context windows; write-to-disk is the right shape)
        "athena/vision/hashlog.py",  # T4-01.2 vision_audit.jsonl — append-only provenance log over every image vision_analyze reads (mirrors computer/audit.py shape)
        "athena/browser/capture.py",  # T4-03.3 browser_capture.jsonl — append-only capture log over every browser_navigate (URL/status/title/content hash; same append shape as computer/audit.py and vision/hashlog.py)
        "athena/audio/tools.py",  # T4-04 transcript artifacts under <profile>/audio/ (transcribe_track output JSON + sidecar plaintext; same provenance shape as video frame artifacts in T4-02)
        "athena/document/tools.py",  # T4-05 parsed document artifacts under <profile>/documents/ (document_analyze output JSON; same provenance shape as audio/video artifacts)
        "athena/mcp/differentiated.py",  # T5-05.3 MCP verified_write — routed through path_security + VerifiedExecution (verified writes are the model the test is protecting)
        "athena/mcp/request_log.py",  # per-request MCP JSONL append (T3-02 audit)
        "athena/plugins/bundled/shell_audit/plugin.py",  # shell audit log (append-only)
        "athena/proxy/logging.py",  # proxy traffic JSONL append + opt-in bodies (T3-01)
        "athena/plugins/loader.py",  # plugin state file
        "athena/profiles/manager.py",  # atomic profile metadata writes
        "athena/profiles/resolution.py",  # active-profile pointer
        # R2 stage 4 -- one-shot, idempotent copy of legacy
        # ``~/.athena/projects/<slug>/memory/`` into the new
        # ``<profile_dir>/memory/legacy/<slug>/`` sub-store. Operator-
        # facing migration parallel in shape to migration/memory_exporter.py
        # above; runs at most once per (profile, workspace) pair and is
        # flag-gated (``cfg.migrate_legacy_memory``) for the dogfood
        # window.
        "athena/profiles/migration.py",
        "athena/safety/audit.py",  # the audit log itself
        "athena/safety/snapshots.py",  # the snapshot store itself
        "athena/sessions/jsonl.py",  # session transcript append
        "athena/sessions/reindex.py",  # session index rebuild
        "athena/sessions/store.py",  # session meta writes
        "athena/skills/archive.py",  # invoked by skill_delete (audited)
        "athena/skills/metrics.py",  # T3-06R per-skill metrics JSONL (operational data, not user content)
        "athena/skills/manager.py",  # the snapshot site
        "athena/skills/pin.py",  # invoked by skill_pin (foreground-only)
        "athena/skills/state_machine.py",  # skill state transitions
        "athena/tools/file_ops.py",  # foreground Read/Edit/Write tools
        "athena/tools/tool_result_storage.py",  # content-addressed blob writes + append-only JSONL index (T2-06)
        "athena/tools/patch_apply.py",  # unified-diff write with per-file backup/restore (T2-07)
        "athena/commands/save.py",  # /save slash dumps the transcript to JSON (user-driven, not an agent mutation)
        "athena/transform/dataset.py",  # training dataset exports
        "athena/transform/deploy.py",  # deployment artefacts
        "athena/transform/review.py",  # review artefacts
        "athena/transform/batch_driver.py",  # T3-05R labels sidecar rewrite (same path as review.py)
        # Per-run training state machine — atomic .athena_train_state.json
        # under <output_dir>. Machine-managed bookkeeping for resumable
        # SFT/DPO/export phases (parallel in shape to goal/state.py and
        # update/apply.py — not user content, not agent-driven mutation).
        "athena/transform/run_state.py",
        "athena/webhooks/delivery.py",  # webhook delivery journal
        # Rollback CLI is itself audited; the restore() call lives in
        # snapshots.py which is allowlisted as the substrate.
        "athena/cli/rollback.py",
        # Batch / eval / delegate runners — operational outputs
        # (envelopes, eval summaries, codex transcripts), not
        # agent-driven mutations of user content.
        "athena/batch/runner.py",
        "athena/cli/batch.py",
        "athena/cli/eval.py",
        "athena/eval/runner.py",
        # T7-Task2 agent-eval harness — same shape as eval/runner.py
        # above (operational test infrastructure that writes its own
        # report JSON, task fixtures, and mock-MCP transcripts; not
        # agent-driven mutation of user content).
        "athena/eval/agent/report.py",  # eval report serialization
        "athena/eval/agent/tasks/_mcp_helpers.py",  # writes workspace/mcp.json pointing at mock servers
        "athena/eval/agent/tasks/file_ops.py",  # eval task fixtures into tempdir workspaces
        "athena/eval/agent/tasks/mock_users_server.py",  # mock stdio MCP server transcripts
        "athena/eval/agent/tasks/shell.py",  # shell eval task fixtures
        "athena/eval/agent/tasks/structured.py",  # structured-output eval task fixtures
        # Minimal reference MCP server (stdlib only) used by integration
        # tests + as a copy-paste example. Same operational role as
        # mock_users_server.py above.
        "athena/mcp/demo_server.py",
        # Skill ingestion (dbfaa09) -- import_skill / import_archive
        # copy an external SKILL.md (or skill dir / archive) into the
        # user-global or workspace skills tree. User-driven via
        # /skill import or `athena skill add`; same provenance shape
        # as migration/skills_mapper.py already allowlisted (operator-
        # facing skill ingestion, not agent-driven mutation).
        "athena/skills/importer.py",
        "athena/delegate/codex.py",
        # T6-05 xAI video adapter — fetch() writes the downloaded
        # MP4 to out_dir, same provenance shape as stub_local.py.
        "athena/videogen/backends/xai.py",
        # /theme save writes the active theme name into config.toml
        # (one line, atomic rewrite). Config file is itself the
        # operator-facing surface, not user content.
        "athena/commands/theme.py",
        # /godmode save writes a per-config JSON file to
        # ``~/.athena/godmode/configs/<name>.json``. Operator-facing
        # config persistence, parallel in shape to /theme save above
        # -- not an agent-driven mutation of user content. The module
        # itself is gated by ATHENA_ALLOW_GODMODE=1 at import time
        # (see athena/commands/godmode.py); without the env var the
        # write site is unreachable.
        "athena/commands/godmode.py",
        # User-modeling backend writes auto-extracted facts to
        # ``~/.athena/profiles/<profile>/user_model/<id>.md`` plus
        # an INDEX.md. These are machine-managed observation
        # records (not user content), parallel in shape to the
        # session JSONL appends and curator report files already
        # allowlisted above. Mutations are confined to a dedicated
        # profile subdir and use stable IDs so re-extraction
        # overwrites cleanly rather than accumulating.
        "athena/user_model/markdown.py",
        # TUI gateway silencing — set_gateway() opens os.devnull
        # in write mode as the destination for Rich's
        # console.file while the Ink TUI owns the terminal.
        # Not a user-content write; it's a noop sink that
        # prevents Rich.Live / console.print / native fd writes
        # from colliding with the Ink subprocess's rendering.
        # File is closed and replaced with the real sys.stdout
        # on TUI shutdown.
        "athena/ui.py",
        # Crash log writer -- atomic tmp + os.replace into
        # ~/.athena/crashes/. Diagnostic-only files; never user
        # content. Routing through snapshot_and_record would
        # require the audit subsystem to be alive at crash time,
        # which is exactly when it can't be assumed -- the
        # crash_log writer must work from a sys.excepthook before
        # any other state is reachable. Bounded by
        # MAX_CRASH_RECORDS rotation so disk usage is capped.
        # See athena/crash_log.py module docstring.
        "athena/crash_log.py",
        # Event log writer -- append-only JSONL into
        # ~/.athena/logs/session-<id>.jsonl. Same diagnostic-only
        # rationale as crash_log: captures provider_error /
        # tool_error / circuit_breaker events at the moments they
        # happen, which is exactly when the audit subsystem may
        # itself be the failing surface (think: snapshot_and_record
        # raising mid-tool-error). Bounded by MAX_LOG_FILES rotation.
        # See athena/event_log.py module docstring.
        "athena/event_log.py",
        # Boot tracer -- opt-in (gated on ATHENA_BOOT_TRACE=1)
        # append-only JSONL into ~/.athena/boot-trace.jsonl for
        # debugging silent-exit / hang bugs at startup. Same
        # diagnostic-only rationale as crash_log / event_log:
        # tracing fires BEFORE any other state is reachable
        # (excepthook, agent, snapshot_and_record), so routing
        # through the audit subsystem is impossible by definition.
        # See athena/boot_trace.py module docstring.
        "athena/boot_trace.py",
    }
)


_PATTERNS = [
    re.compile(r"\.write_text\("),
    re.compile(r"\.write_bytes\("),
    re.compile(r"\bopen\s*\([^)]*['\"][wa][bt]?['\"]"),
    re.compile(r"shutil\.copy"),
    re.compile(r"shutil\.rmtree"),
]


def _iter_python_files(root: Path):
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        if p.name == "__init__.py":
            continue
        yield p


def _module_key(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def test_no_new_raw_write_sites_outside_allowlist() -> None:
    """New raw writes in athena/ must either be routed through
    ``snapshot_and_record`` or explicitly added to ALLOWLIST."""
    new_violators: set[str] = set()
    for py in _iter_python_files(ATHENA_ROOT):
        rel = _module_key(py)
        if rel in ALLOWLIST:
            continue
        text = py.read_text(encoding="utf-8")
        for pattern in _PATTERNS:
            if pattern.search(text):
                new_violators.add(rel)
                break

    assert not new_violators, (
        "New raw write sites found in athena/ that aren't in the "
        "snapshot+audit allowlist. Either route the write through "
        "athena.safety.mutation.snapshot_and_record, or add the "
        "module to ALLOWLIST in test_no_raw_writes.py with a "
        "justification.\n\n"
        "Violators:\n  " + "\n  ".join(sorted(new_violators))
    )


def test_allowlist_entries_all_exist() -> None:
    """No phantom allowlist entries — if a module was renamed or
    deleted, prune the allowlist."""
    missing: list[str] = []
    for rel in ALLOWLIST:
        if not (REPO_ROOT / rel).exists():
            missing.append(rel)
    assert not missing, "Allowlist references modules that don't exist:\n  " + "\n  ".join(
        sorted(missing)
    )
