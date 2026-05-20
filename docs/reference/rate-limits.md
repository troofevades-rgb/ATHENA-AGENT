# Rate-limit tracking

athena captures `x-ratelimit-*` response headers from every provider
call and uses them to:

- Preemptively throttle when approaching the limit (configurable).
- Surface live state via `/status`.
- Inform the upcoming error classifier's retry decisions (T2-03).

## How it works

After each successful response, the provider parses the rate-limit
headers into a `RateLimitTracker` and stores it keyed by the
credential's `...<last-4>` suffix.

Before the next request, the provider consults the most recent
tracker for that credential. If `should_throttle(threshold=...)`
returns `True`, the provider `time.sleep`s for
`throttle_seconds()` — the time until the soonest reset, capped at
60 s.

## Configuration

In `~/.athena/config.toml`:

```toml
rate_limit_throttle_threshold = 0.95
```

- `0.95` (default) — throttle when within 5 % of the limit.
- Lower values throttle earlier (more conservative; fewer 429s, more
  sleep time).
- `1.0` disables proactive throttling entirely (reactive-only on 429).

## What's tracked

### Standard 12-header schema

Used by Nous Portal, OpenRouter, OpenAI direct, OpenAI-compat local
servers.

| Field                     | Header                              |
|---------------------------|-------------------------------------|
| RPM limit / remaining     | `x-ratelimit-{limit,remaining}-requests` |
| RPH limit / remaining     | `x-ratelimit-{limit,remaining}-requests-1h` |
| TPM limit / remaining     | `x-ratelimit-{limit,remaining}-tokens` |
| TPH limit / remaining     | `x-ratelimit-{limit,remaining}-tokens-1h` |
| Reset (seconds)           | `x-ratelimit-reset-{requests,tokens}{,-1h}` |

Reset values are relative seconds; the tracker converts them to
absolute Unix timestamps at parse time so downstream throttle math
stays simple.

### Anthropic schema

Anthropic uses `anthropic-ratelimit-*` with ISO 8601 reset
timestamps. The tracker handles the conversion to Unix seconds
internally.

| Field                  | Header                                 |
|------------------------|----------------------------------------|
| Requests limit / left  | `anthropic-ratelimit-requests-{limit,remaining}` |
| Tokens limit / left    | `anthropic-ratelimit-tokens-{limit,remaining}` |
| Requests reset (ISO)   | `anthropic-ratelimit-requests-reset` |
| Tokens reset (ISO)     | `anthropic-ratelimit-tokens-reset` |

Input-specific and output-specific token limits
(`anthropic-ratelimit-{input,output}-tokens-*`) are recognised but
collapsed to the combined `tokens` figure — that's what the throttle
logic needs.

## Provider coverage

| Provider           | Tracker schema | Notes |
|--------------------|----------------|-------|
| `anthropic`        | `anthropic`    | Per-credential. |
| `openai`           | `generic`      | Per-credential. |
| `openai_compat`    | `generic`      | Per-credential; local OpenAI-shaped servers often omit the headers (no-op). |
| `openrouter`       | `generic`      | Per-credential. |
| `nous`             | `generic`      | Per-credential. |
| `ollama`           | none           | Local-only; no rate-limit semantics. |
| `google`           | none           | Schema differs; not yet wired. |

Providers without rate-limit headers silently produce no tracker;
nothing else in the path notices.

## Viewing state

Run `/status` (or `athena status`):

```
rate limits:
  ...abcd: RPM: 47/50 (reset in 12s)  TPM: 28,440/30,000 (reset in 12s)
```

The redacted `...<last-4>` matches the credential's display form in
`athena providers list`, so a row here corresponds to one credential
in the pool.

## Persistence

Rate-limit state is in-memory only. After a restart the trackers
are empty until the first response of the new session repopulates
them. Cooldown state on the credential pool (the `mark_429`
stamp) DOES persist — that's a separate concern, handled by the
existing `credentials.json` writer.

## Limitations

- Cap at 60 s sleep per throttle. Some providers report hour-level
  resets in the minute-reset field; the cap prevents an accidental
  hour-long sleep.
- One tracker per credential per provider. Multi-region or
  multi-organisation accounts that surface different rate buckets
  through the same key aren't currently disambiguated.
- The 5 % threshold default is conservative. Workloads with bursty
  but tightly-spaced calls may want `0.90` or lower to avoid
  trip-and-recover oscillation against the limit.
