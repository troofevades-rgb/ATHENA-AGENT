# Recall

Athena's recall has two layers:

1. **Keyword recall** (SQLite FTS5) — exact-token matching over
   prior session turns. Fast, deterministic, no external
   dependencies. The default path before T6-01.
2. **Semantic recall** (embeddings) — meaning-based matching
   over the same turns plus memory entries. Resolves an
   embeddings provider via the T5-01 capability manifest,
   local-preferred for offline-capability.

A **hybrid ranker** (reciprocal-rank fusion) combines both, so
recall surfaces both exact-token hits *and* paraphrased hits.
That's the default mode.

## Modes

The `search_sessions` tool now takes a `mode` argument:

| Mode       | Ranker           | When it wins                                              |
|------------|------------------|-----------------------------------------------------------|
| `keyword`  | FTS5 only        | Exact tokens — function names, error codes, log strings   |
| `semantic` | Vector cosine    | Pure paraphrase — "the auth bug" finds "credential issue" |
| `hybrid`   | RRF fusion of both | Default; best on real queries that mix both signals     |

The default is `cfg.recall_default_mode` (set to `"hybrid"`).
Passing an explicit `mode=` on the tool call overrides per-call.

## The RRF fusion

Reciprocal-rank fusion is a parameter-light fuser:

```text
score(doc) = Σ_lists 1 / (k + rank_in_list + 1)
```

- A doc appearing in **both** lists scores higher than a doc in
  either alone — the "found by two different signals" win.
- A doc absent from a list contributes 0 from that list.
- `k` (default 60) smooths rank decay; smaller `k` → top-ranked
  docs dominate; larger `k` → lists weighed more equally.

No score normalisation between rankers — RRF only sees ranks.
This is robust in practice and the one knob that matters.

## Embeddings via the manifest

`athena/recall/embeddings.py:resolve_embedder(cfg=...)` consults
`athena.media.MediaRegistry.backend_for("embeddings")` to pick
the provider. Selection follows the broker's
`media_backend_prefer` setting:

- `"local"` (default) — Ollama embeddings if registered → recall
  runs **offline** with a local embedding model. No bytes about
  past conversations leave the machine.
- `"any"` — alphabetical; a hosted embedder may win.

When no provider declares the embeddings capability,
`resolve_embedder` returns `None` cleanly. The recall path then
degrades to keyword-only. **Never a hard dependency** — the
keyword path always works.

## Model-versioned vectors

Each stored vector carries the `model_id` of the embedding model
that produced it. Search **always** filters on `model_id` —
silently mixing vectors from different embedding spaces would be
the worst-case failure mode (nonsense ranks served as if
authoritative). When you switch embedding models:

- Old vectors are simply not matched by the new embedder's
  queries (different `model_id`).
- They sit dormant; consume disk but no correctness risk.
- `athena recall clear` drops them; `athena recall backfill`
  rebuilds with the new model.

## Incremental embedding on write

Each new user / assistant turn is embedded automatically when
written to the session store. The hook lives in
`Agent._persist_message` and calls `record_turn(...)` — a
best-effort path that swallows recall-side exceptions so a
recall bug never breaks a session write.

Memory entries embed on write too (via `record_memory_entry`)
when wired in at the memory provider seam.

Tool-result turns (`role="tool"`) are **not** embedded — they're
rarely standalone-recall-worthy and the model already sees them
with the call that produced them.

## Backfilling existing history

For sessions written before semantic recall was enabled, or
after a model swap:

```bash
athena recall backfill              # current profile
athena recall backfill --profile X  # a specific profile
```

The backfill is **idempotent**. It walks
`<profile_dir>/sessions/*.jsonl` + `<profile_dir>/memory/**.md`
and embeds only doc IDs not already in the index. Re-running is
a no-op (no duplicate work, no duplicate vectors).

## Admin

```bash
# Show vector counts (total + by-model + by-workspace).
athena recall status

# JSON for tooling.
athena recall status --json

# Drop the index entirely. Next backfill rebuilds.
athena recall clear
```

## Configuration

```toml
# Enable / disable the semantic + hybrid paths. Keyword stays on
# regardless.
semantic_recall_enabled = true

# Default recall mode when search_sessions is called without an
# explicit `mode` argument.
recall_default_mode = "hybrid"        # "keyword" | "semantic" | "hybrid"

# How MediaRegistry picks the embedder when multiple providers
# declare embeddings. "local" keeps things offline; "any" falls
# back to alphabetical.
embedding_model_prefer = "local"

# Explicit model id override. None → provider's
# default_embedding_model.
# embedding_model = "nomic-embed-text"

# Index location. None → <profile_dir>/vectors.json
# vector_store_path = "/path/to/my/vectors.json"
```

## What's NOT in the vector store

- The **payload** — only the embedding and a 200-char text
  preview. The full turn lives in the session JSONL; the full
  memory entry lives in its markdown file.
- **Tool-result turns** — see above.
- **Cross-session totals** or **provider usage stats** — those
  live in their own surfaces (T2-06 / observability).

## Smoke

```bash
# Bring an existing history online with semantic recall.
athena recall backfill

# In a later session:
> recall when we set up the retry logic
  # hybrid mode → both FTS5 (matches "retry" if it was written
  # that way) and semantic (matches the meaning either way)
  # combine via RRF. The right turn surfaces regardless of
  # whether the original used the word "retry".

# Offline test (with a local embedding model installed):
#   1. Disconnect the network.
#   2. recall <a paraphrased query>
#   3. Hits surface — semantic path works offline.
```

## The self-update path is unchanged

`write_memory` (the existing self-updating memory tool) writes
memory entries the same way it always did. T6-01 doesn't change
the write path; it just makes those entries semantically findable
too — via the same memory directory the existing tool already
maintains.

## Related

- [Provider capabilities](provider-capabilities.md) — the
  manifest the embedder is resolved from
- [Capability broker](capability-broker.md) — the routing rules
- [Sessions](sessions.md) — the underlying transcript store
