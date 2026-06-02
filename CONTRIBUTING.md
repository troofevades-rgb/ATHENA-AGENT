# Contributing to athena

This document describes the development loop, the CI surface, and what
to expect when filing a PR. Keep it short and accurate -- the rest
lives in `ATHENA.md` and `CLAUDE.md`.

## Quick start

```bash
git clone https://github.com/troofevades/athena
cd athena
pip install -e ".[dev]"

# Verify the install
athena doctor                 # health check across config / providers / Ollama / TUI
athena --version
pytest -q                     # ~5300+ tests, runs in 5-6 min
ruff check athena tests       # lint
```

`athena doctor` is the canonical "is anything obviously broken" probe.
Run it before reporting a bug; the WARN/FAIL lines tell you where to
look first.

If athena dies mid-session, a JSON crash record lands at
`~/.athena/crashes/crash-<ts>-<uuid>.json` (secrets scrubbed,
conversation content excluded). Attach that file to bug reports.

## CI pipeline

Every push to `master`/`main` and every PR triggers six GitHub Actions
workflows under `.github/workflows/`. Each runs in its own job so a
slow / flaky one doesn't gate the others.

| Workflow | What it gates | Notes |
|---|---|---|
| `tests.yml` | Test suite on Linux, Python 3.10 + 3.11 | 3.12 / 3.13 disabled pending pytest-asyncio fixture cleanup (tracked in `tests.yml` comment block). |
| `lint.yml` | `ruff check`, `ruff format --check`, `mypy`, version-sync | `ruff` runs on Ubuntu + Windows + macOS (the platform matrix catches Windows-specific path / encoding regressions). `mypy` is advisory (`continue-on-error: true`) -- ~283 known violations in `strict = true` mode tracked in T1-04. `version-sync` enforces `pyproject.toml` ↔ `athena.__version__` parity. |
| `coverage.yml` | `--cov-fail-under=65` | Coverage threshold; global athena ~75%, agent/ subtree ~62%. |
| `osv-scanner.yml` | OSV vulnerability scan against dependencies | Currently pinned to `google/osv-scanner-action@v2.3.8`. |
| `supply-chain.yml` | Lockfile drift, dependency integrity | |
| `publish.yml` | PyPI release on tag push | Manual trigger; production-gated. |

What the auditor's "no CI pipeline" claim missed: every one of these
runs on every PR. The visible PR checks include "tests / 3.10",
"tests / 3.11", "lint / ruff (ubuntu)", "lint / ruff (windows)", "lint
/ ruff (macos)", "lint / mypy", "lint / version-sync", "coverage /
coverage", "supply-chain", and "OSV-Scanner". Drift here belongs in a
separate PR that updates this file alongside the workflow change.

### When CI is RED

1. **lint failure** -- run `ruff check athena tests` locally; `ruff
   check --fix athena tests` autofixes most. `ruff format athena
   tests` rewrites code style.
2. **test failure** -- `pytest tests/<path> -q --tb=short` reproduces.
   Most failures stem from a missing dev extra (`pip install -e
   ".[dev,gateway,observability,vision]"` covers everything the
   suite imports at collection time).
3. **mypy is advisory** -- failures don't gate merge. Fix them
   incrementally as you touch the affected file.
4. **coverage drop** -- the 65 threshold has buffer; a real drop means
   you added uncovered branches. Add a focused test rather than
   bumping the threshold down.
5. **OSV / supply-chain failure** -- dependency CVE or lockfile drift.
   Update the offending dep + re-run locally before pushing.

## Repository layout

`ATHENA.md` at the repo root has the full subpackage map and convention
list. Skim it first for any non-trivial change.

The TL;DR:

- `athena/` -- the package. Subdirs roughly map 1:1 to subsystems
  (`agent/`, `providers/`, `gateway/`, `commands/`, `cli/`,
  `tools/`, etc.).
- `tests/` -- mirrors `athena/` directory structure. ~5300+ tests.
- `ui-tui/` -- the Ink TUI subprocess. Built via `bun run build`
  in that directory.
- `.github/workflows/` -- CI (see table above).
- `scripts/` -- dev scripts (`verify_version.py`, etc.). Not shipped
  to PyPI.

## PR expectations

- One concern per PR. Multiple unrelated fixes -> multiple PRs.
- Tests for every behavior change. The pin-as-you-go discipline is
  what's keeping the audit's "drift" findings at bay -- new code
  arrives WITH the regression-pins.
- Stale doc detection: if you change behavior, search the codebase
  for any comment, docstring, or `ATHENA.md` line that described the
  old behavior. Update it in the same commit.
- Don't add to the `_LOAD_CONFIG_ALLOWLIST` or
  `_ACTUAL_INLINE_REPL_COMMANDS` exceptions without a comment
  justifying the exception.
- Commit messages: imperative subject ≤ 72 chars, then a blank line,
  then a body explaining the WHY. The recent commits under `master`
  are the style reference.

## Filing a bug

Three things make a bug report actionable:

1. **`athena doctor` output** -- paste the text or `--json` blob.
2. **The crash record** if one exists -- `ls -lt ~/.athena/crashes/`
   and grab the newest. Secrets are scrubbed; conversation content is
   never included.
3. **Reproduction steps** -- exact `athena` invocation and slash
   commands typed.

The audit / dogfood discipline that closes out the regression-pin
gaps lives in `MEMORY.md` (your local notes) and the commit history.
Treat the commit log as the changelog until 0.3.0 ships.
