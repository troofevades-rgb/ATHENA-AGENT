# athena-coder v0.2.0 — Production Foundation

**Release date:** 2026-05-19

This is athena's first PyPI release. It bundles the Tier 1
production-readiness work — CI, distribution, security hardening,
agent-core tests, and release-notes discipline — into a single
coherent shipping artifact.

## Highlights

- **`pip install athena-coder` from PyPI.** No more `git clone` required.
  The `athena` CLI shim lands on `PATH` after install; the Python
  import name is unchanged (`import athena`).
- **CI on every PR.** Five workflows running on every push to
  `master` and every pull request: tests (Python 3.10 + 3.11 matrix
  with pytest-timeout safety net), ruff lint + format, mypy strict
  (advisory in v0.2.0; required in v0.3.0 after the T1-04 cleanup),
  coverage with a 60% floor, OSV vulnerability scanner, and
  pip-audit supply-chain check. Dependabot opens pip and
  github-actions bump PRs weekly.
- **Path-traversal sandboxing** _(landing as T1-07 ships before
  tag)._ File operations are constrained to the workspace root by
  default; writes outside the workspace require explicit approval.
- **SSRF defense on the web tool** _(T1-08)._ Cloud-metadata IPs,
  RFC1918, loopback, and link-local addresses are blocked by
  default.
- **Atomic credential file writes** _(T1-06)._ No TOCTOU window
  between file creation and `chmod 0o600`; tokens are written via
  `os.open(O_EXCL, 0o600)` from the start.
- **Agent core test coverage** _(T1-04)._ `tests/agent/` covers
  `agent/core.py:run_until_done`, `agent/fork.py:Agent.fork()`, and
  `agent/auxiliary_client.py` with a deterministic FakeProvider that
  yields scripted stream chunks — no network in any unit test.

## Notable changes

- **Renamed on PyPI to `athena-coder`.** Both `athena` and
  `athena-agent` are taken by unrelated active projects. The
  GitHub repository stays at
  [`troofevades-rgb/ATHENA-AGENT`](https://github.com/troofevades-rgb/ATHENA-AGENT)
  and the Python import name is still `import athena`.
- **Legacy `ocode` console-script alias removed.** Update any shell
  aliases or scripts that called `ocode` to call `athena` instead.
- **README MCP transport claims now match shipped code** _(T1-05)._
  Previously the README claimed stdio-only; HTTP/SSE + OAuth 2.1
  PKCE shipped in Phase 12 (see `docs/reference/` and the MCP
  Phase 12 entry in the full changelog).
- **`athena --version` flag** prints `athena-coder <version>` and
  is single-sourced via `athena.__version__`; CI gates drift
  between `pyproject.toml`'s `[project].version` and the module
  constant via `scripts/verify_version.py`.

## Tier 1 phases included

- **T1-01** CI scaffold — five workflows + dependabot
- **T1-02** PyPI distribution — trusted publishing, metadata, LICENSE
- **T1-03** Release notes (this file) and Keep-a-Changelog discipline
- **T1-04** Agent core test suite under `tests/agent/`
- **T1-05** Documentation reconciliation — README MCP claims, Modelfile
- **T1-06** Atomic credential writes — TOCTOU-safe `os.open` paths
- **T1-07** Path security module — workspace-boundary validation
- **T1-08** SSRF defense — web-tool destination allowlist

## What's next

Tier 2 of the production-readiness plan covers Anthropic prompt
caching, rate-limit header tracking, error classifier, context
compression, gateway session resume, and the foundational tooling
gaps (clarify, schema sanitizer, tool result storage, patch parser,
fuzzy match).

See [`GAP_ANALYSIS.md`](GAP_ANALYSIS.md) for the full plan and
`docs/plan/` (if shipped) for phase-by-phase execution.

## Full changelog

See [CHANGELOG.md](CHANGELOG.md) for the complete list of changes
in this release.
