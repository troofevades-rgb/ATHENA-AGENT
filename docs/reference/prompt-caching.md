# Prompt caching

athena supports Anthropic's prompt-caching feature to reduce
input-token costs on multi-turn sessions. When the active provider
is Anthropic (direct), OpenRouter, or Nous Portal, the agent
attaches `cache_control` markers to the outgoing messages and
Anthropic returns the cached prefix at a fraction of the normal
input-token price.

## How it works

When `cache_strategy = "system_and_3"` (default), athena attaches
`cache_control` markers to:

- the last `system` message
- the last 3 non-`system` messages

Anthropic caches the prefix up to each marker for 5 minutes
(default) or 1 hour (opt-in via `prompt_cache_ttl = "1h"`).

The 4-breakpoint layout matches Anthropic's per-request marker cap.
Hermes shipped this layout after empirically testing alternatives —
"last system + last 3 non-system" is what minimises cache invalidation
across natural conversation turns.

On a typical 5-turn session with a ~30K-token system prompt + skill
catalog, the input-token cost drops by roughly 60-75% compared to
caching disabled.

## Configuration

In `~/.athena/config.toml`:

```toml
cache_strategy = "system_and_3"  # or "none" to disable
prompt_cache_ttl = "5m"          # or "1h" for cross-session caching
```

`cache_strategy` accepts:

- `"system_and_3"` (default) — the 4-breakpoint layout described above.
- `"none"` — disable cache markers entirely. Useful while debugging
  a routing-layer issue or comparing token costs.
- `"aggressive"` — reserved for future strategies (currently aliased
  to `system_and_3`).

`prompt_cache_ttl` accepts `"5m"` or `"1h"`. The 1h variant costs
slightly more per cache write but lets a fresh session within the
hour pick up the cached prefix from the prior session, which is the
right tradeoff for repeat usage patterns.

## How to tell if it's working

Run a 2-turn conversation against an Anthropic-flavoured model.

After turn 2, run `/status` (or `athena status`). The token block
shows two cache lines when there's been a hit:

```
tokens:
  prompt:          1234
  completion:        56
  total:           1290
  cache read:      8000
  cache new:        500
  strategy:   system_and_3 (ttl 5m)
```

- `cache read` non-zero means Anthropic served part of the request
  from cache (you paid the discounted rate for those tokens).
- `cache new` is the prefix Anthropic just cached for this request.

If `cache read` stays zero across a multi-turn session against an
Anthropic-flavoured provider, debug:

- `apply_cache_markers` may not be called — check `cfg.cache_strategy`
  isn't `"none"`.
- The provider name may not be in `_CACHE_AWARE_PROVIDERS`
  (`anthropic`, `openrouter`, `nous`) — non-Anthropic backends skip
  marker application by design.
- The system prompt may be changing between turns (different `today`
  date, different skill catalog, etc.) — that ends the cacheable
  prefix at that byte.

## Provider coverage

| Provider     | Markers applied? | Native shape         |
|--------------|------------------|----------------------|
| `anthropic`  | yes              | native Anthropic     |
| `openrouter` | yes              | OpenAI-compat relay  |
| `nous`       | yes              | OpenAI-compat relay  |
| `ollama`     | no               | n/a                  |
| `openai`     | no               | n/a                  |
| `openai_compat` | no            | n/a (local servers)  |
| `google`     | no               | n/a                  |

The marker is silently ignored by non-Anthropic backends, so
`cache_strategy = "system_and_3"` is safe to leave on across a
multi-provider environment.

## Persistence

Cache markers are *request-time metadata*, not session content.
`Agent._persist_message` strips them before writing to the session
JSONL so replaying a session never sends stale markers. The
deepcopy-and-strip pattern means the in-memory message object is
unaffected.

## Limitations

- 4 markers max per request (Anthropic limit). The `system_and_3`
  layout hits this ceiling exactly.
- Cache key includes the full prefix; if you change the system
  prompt or skill catalog mid-session, the cache invalidates and the
  next turn pays full price for re-caching.
- The cache is per-API-key. Switching credentials mid-session
  invalidates.
- Only Anthropic-direct and Anthropic-via-OpenRouter/Nous-Portal
  benefit. Other providers ignore the markers.

## Implementation

- `athena/agent/prompt_caching.py` — pure-function module
  (`apply_cache_markers`, `strip_cache_markers`, `_cache_marker`,
  `_apply_cache_marker`). No Agent dependency.
- `athena/agent/core.py:Agent._messages_with_cache_markers` —
  dispatches based on `cfg.cache_strategy` and the provider's `name`.
- `athena/agent/core.py:Stats.cache_read_tokens` /
  `cache_creation_tokens` — counters populated from each provider
  call's usage chunk.
- `athena/cli/status.py:render_status` — surfaces the strategy +
  hit counters in `/status`.
