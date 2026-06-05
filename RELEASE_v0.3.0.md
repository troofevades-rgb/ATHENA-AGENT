# athena-coder v0.3.0 — Reliability, Reach, and Polish

**Release date:** 2026-06-05

The second PyPI release. Where v0.2.0 laid the production foundation
(CI, distribution, security, release discipline), v0.3.0 is about making
athena **reliable on local models**, **reachable from everywhere**, and
**pleasant to live in** — plus a round of startup-hardening and TUI fixes.

Install / upgrade:

```bash
pip install -U athena-coder
athena --version          # → athena-coder 0.3.0
```

## Highlights

- **Reliability for small / local models.** Automatic context compression
  at a token watermark; provider error classification with retry + backoff
  and credential rotation; preemptive rate-limit throttling; Anthropic
  prompt caching (4-breakpoint, ~60–75% input-token savings); a tool-call
  argument sanitizer that recovers malformed JSON; recovery when the model
  narrates an action without calling a tool; and opt-in struggle-based
  escalation to a stronger model.

- **athena as a server.** `athena mcp serve` exposes a curated, read-mostly
  tool + resource surface to peer MCP clients (Claude Desktop / Code,
  Cursor). `athena proxy serve` is a local OpenAI-compatible endpoint with
  OpenAI ↔ Anthropic translation, so any OpenAI client can route through
  athena's providers, caching, and retry machinery.

- **Multimodal tools.** Vision, OCR, `document_analyze` (PDF/DOCX with a
  scanned-page OCR fallback), plus video and audio analysis — all behind a
  consistent "unavailable ≠ error" graceful-degrade contract.

- **Headless, batch, and eval.** `athena -p "<task>" --json` emits a stable
  `RunResult` envelope; `athena batch <tasks.jsonl>` iterates it (serial or
  parallel, resume-safe); `athena eval <cases.jsonl>` scores runs against a
  labeled set with baseline regression diffs — the closed training loop is
  finally testable head-to-head.

- **Conversation checkpoints.** `/checkpoint` + `/rollback-to` (and the
  `athena checkpoint` CLI) capture message log, file snapshots, and skill /
  memory state, and revert all of it atomically — with the rollback itself
  undoable.

- **Polished TUI.** Native terminal scrolling, a `⏺ Tool(args)` / `⎿ output`
  call tree, syntax-highlighted markdown, a live context-window gauge,
  `Ctrl+O` to toggle model reasoning, and sub-agent tool calls rendered
  nested + dimmed.

## Startup hardening (this cycle)

- A hung or unreachable **MCP server** can no longer brick launch — each
  connect is bounded by a configurable `startup_timeout` (default 10s) with
  progress feedback and skip-on-timeout.
- An unreachable **`OLLAMA_HOST`** can no longer hang the startup probe for
  the full request timeout — connect is bounded short while read / write
  stay generous for long generations.

## Notable fixes

- Background curator / review forks no longer leak their tool calls into the
  foreground transcript.
- The `<think>` reasoning trace no longer dumps a literal
  `_(thought collapsed)_` marker into the transcript.
- Parallel same-tool calls get a unique per-call id, fixing lane
  mis-attribution and mass-eviction under concurrent dispatch.

## Compatibility

- Python 3.10+; Ollama remains the default, air-gapped-by-default provider.
- The config key `auto_approve_bash` is deprecated in favor of
  `auto_approve_tools` (auto-migrated with a warning).
- The full per-change history is in [CHANGELOG.md](CHANGELOG.md) under
  `## [0.3.0]`.
