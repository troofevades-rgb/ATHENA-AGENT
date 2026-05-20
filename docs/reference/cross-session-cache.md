# Cross-session prompt caching

T2-01 reused a session's prompt prefix on its follow-up turns.
T5-06 extends that reuse **across sessions** — a stable prefix
(system prompt + pinned skills + durable project / memory
context) cached in one session is the cached prefix for the
next session in the same workspace + provider.

This is table stakes for cost + latency on multi-session work;
it's kept deliberately simple — correctness first, no fancy
multi-tier eviction policy.

## The correctness guarantee

The single failure mode that matters is a **wrong hit** —
serving a stale prefix as if it were the current one. Athena's
defence is a SHA-256 content hash:

| Prefix change                | Hash change | Result                |
|------------------------------|-------------|-----------------------|
| identical bytes              | no          | hit (within TTL)      |
| one character added/removed  | yes         | clean miss, re-record |
| skill edited                 | yes         | clean miss            |
| system prompt updated        | yes         | clean miss            |
| memory file edited           | yes         | clean miss            |

A changed prefix **can't** match an old entry. TTL bounds
staleness; the hash bounds correctness.

## What's cached

Only the **stable prefix**:

- the system prompt
- pinned skill bodies (folded into the system prompt by
  `_build_system`)
- durable project context (`ATHENA.md`, memory index)

What's **never** cached:

- the conversation tail (recent turns)
- tool results
- anything that changes with the dialogue

The boundary is conservative — when in doubt, treat as
volatile.

## The caching mechanism

The provider's T5-01 capability manifest decides *how* athena
caches:

| Manifest                                                | Mode       | What happens                              |
|---------------------------------------------------------|------------|-------------------------------------------|
| `prompt_caching=True` + `cache_ttls_seconds=(...,)`     | `server`   | server-side cache; largest declared TTL   |
| `kv_cache_reuse=True`                                   | `kv_reuse` | local KV reuse; backend does the actual work |
| neither                                                 | `none`     | no caching; prefix sent normally          |

For server mode (Anthropic, OpenAI), the actual cache lookup is
the provider's job — athena's existing T2-01 `cache_control`
headers already replay the same prefix bytes; when the prefix
is byte-stable across sessions in a workspace, the provider's
server cache naturally hits. T5-06's index is athena's
observation surface — "yes, this prefix was sent at T with TTL
S, the provider's cache should still be alive".

For KV reuse mode (Ollama / llama.cpp), the local inference
backend does the actual KV-cache reuse. Athena's job is to keep
the prefix byte-stable across sessions (the index confirms
that) and signal reuse. The TTL for KV reuse defaults to 1h
since the manifest doesn't declare a TTL for that mode.

## Invalidation

**Automatic via hash change.** Edit a skill, change the system
prompt, update memory → the prefix hashes differently in the
next session → the old index entry simply isn't matched. The
provider's server cache (if any) also misses on the new prefix
and creates a new entry there. No manual coordination required.

**Manual via `athena cache clear`.** For forced resets when:

- A backend cache id has gone stale unexpectedly
- Switching providers and starting fresh
- Debugging cache behaviour

## Configuration

```toml
# Enable / disable the cross-session index. Default true.
cross_session_cache_enabled = true

# Skip caching for prefixes whose 4-bytes-per-token estimate
# is below this number. Default 1024 (~4 kB). The bookkeeping
# isn't worth it for tiny prefixes.
cache_min_prefix_tokens = 1024

# Override the index location. None → <profile_dir>/cache_index.json.
cache_index_path = "/path/to/my/cache_index.json"
```

## CLI: status and clear

```bash
# List every entry, ALIVE or EXPIRED.
athena cache status

# JSON shape for tooling integration.
athena cache status --json

# Inspect a non-default profile.
athena cache status --profile other

# Or point directly at an index file.
athena cache status --index-path /tmp/inspect.json

# Force a clean slate.
athena cache clear
```

`athena cache status` output:

```text
2 cache entries in /home/me/.athena/profiles/default/cache_index.json:
  [ALIVE]   /home/me/proj  anthropic  hash=a1b2c3d4e5f6…  age=42s  ttl=3600s
  [EXPIRED] /home/me/old   openai     hash=9f8e7d6c5b4a…  age=9999s  ttl=60s
```

## What's NOT in the cache file

- The cached PAYLOAD. For server mode the provider owns the
  bytes; for KV reuse the local backend does. The index
  records only the metadata: "this hash was sent here at T
  with this TTL".
- Per-call usage stats. T2-06 / observability surfaces handle
  those.
- Anything from the conversation tail.

## Smoke

```bash
# Start a session in workspace W; ask a question; quit.
# Start a new session in W → the prefix matches → the provider's
#   server cache (or local KV) reuses; cold-start tokens / latency
#   are lower.
athena cache status                            # see the entry

# Edit a pinned skill — the system prompt now folds the new body.
# Start a new session → cache miss (different hash) → new entry
#   recorded, proving the hash invalidates correctly.

athena cache clear                              # force reset
```

## Related

- [Prompt caching](prompt-caching.md) — in-session strategy (T2-01)
- [Provider capabilities](provider-capabilities.md) — the manifest
  the plan reads
