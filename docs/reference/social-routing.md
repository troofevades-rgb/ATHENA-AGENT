# Social/X provider + capability routing

A social model is just another provider — registered via the
T5-01 manifest, picked by the T5-05 broker, no provider-name
special-casing anywhere in the codebase. The model the user
selected stays the primary; **only the social-search sub-task**
goes to the social provider, and the result folds back into the
primary's tool result.

## The capability

`Capabilities.social_search: bool = False` (T6-02.1) is the
field the broker queries. The default is False (the
manifest's conservative-default pattern); only providers that
declare it become candidates.

```python
from athena.providers import best_provider_for
best_provider_for({"social_search"})   # → "social" when registered
```

When no provider declares the capability, the `search_x` tool
degrades cleanly to `{"available": false, "reason": "no
social-search provider configured"}`. The agent gets a
structured payload and moves on; nothing crashes.

## The provider plugin

`athena.providers.social.SocialProvider` is the first
capability-only provider in athena's registry. It declares
`social_search=True` and honestly **declines chat**
(`tool_calls=False`, `streaming=False`). Trying to chat with it
raises `NotImplementedError`; the chat-parity test skips it via
a `_NON_CHAT_PROVIDERS` set.

Surface:

| Method | Returns |
|---|---|
| `static_capabilities()` (classmethod) | `Capabilities(social_search=True)` |
| `is_available()` | `True` iff a valid OAuth token is on disk |
| `social_search(query, *, max_results)` | list of normalised posts |

Normalised post shape — what the primary model sees:

```json
{
  "author": "alice",
  "text": "the post text",
  "timestamp": "2026-05-19T10:00:00Z",
  "url": "https://example.test/alice/status/1",
  "metrics": {"like_count": 42}    // optional
}
```

## OAuth

`athena.social.oauth.SocialOAuth` handles the
authorization-code + refresh flow. Tokens persist via
`athena.safety.secure_files` at `0o600` with the same
atomic-replace + fsync semantics every other credential file in
athena uses. The token file lives at
`<profile_dir>/social/social_token.json`.

**Token safety — the load-bearing property:**

- `TokenStore.__repr__` / `__str__` redact: `access_token=<redacted>`,
  `refresh_token=<set>|<none>`. Any third-party logger that
  f-strings a `TokenStore` doesn't leak the secret.
- `_redact_for_log(token)` is the only function permitted to
  format token info for logs. Returns "Ns remaining" / "(no
  token)" / "(no expiry recorded)".
- A pytest test (`test_token_never_in_logs`) captures every
  log at DEBUG across a full exchange + access cycle and
  asserts the secret tokens never appear.

**Refresh leeway**: tokens within 60 seconds of expiry are
pre-emptively refreshed on `access_token()` so callers don't
hit a use-then-fail-then-refresh race.

**Auto-clear semantics**: a refresh that fails with non-200
raises `RuntimeError` (no silent fall-through); an expired
token with no `refresh_token` also raises with a clear "re-run
authorize" message. `clear()` is idempotent.

### Vendor specifics live in config

```toml
social_oauth_authorize_url        = "https://..."
social_oauth_token_url            = "https://..."
social_oauth_client_id            = "..."
social_oauth_client_secret_path   = "/path/to/secret-file"  # 0o600
social_oauth_scopes               = ["tweet.read", "users.read"]
social_oauth_redirect_uri         = "http://localhost:9876/callback"
social_search_url                 = "https://.../v1/search"
social_search_query_param         = "query"
social_post_url_template          = "https://example.test/{author}/status/{id}"
```

A vendor change is a config edit + a possible edit to
`SocialProvider._normalise_response` if the response JSON
shape differs. Nothing else in athena needs to know.

## The `search_x` tool

The explicit, model-callable tool that triggers social-search
routing. Aliased as `social_search`.

```python
search_x(query: str, max_results: int | None = None) -> str  # JSON payload
```

Returns a JSON-formatted text result:

```json
{
  "available": true,
  "provider": "social",
  "results": [ { "author": "...", "text": "...", ... }, ... ],
  "reason": null
}
```

`available=false` shapes (graceful-when-absent):

| Condition | `reason` |
|---|---|
| No provider declares `social_search` | "no social-search provider configured" |
| Provider declared but not ready (no OAuth token, etc.) | same — wrapped at the not-available branch |
| Provider's `social_search` raised | the exception text + which provider |
| Empty / whitespace query | `"empty query"` |

The switch is **visible**:

- `ui.info(f"searching X via {provider_name}")` — printed to the
  user / operator so the backend is never silent
- `logger.info("search_x: routing query=%r to provider=%r", ...)`
  — the routing decision lands in the journal

The **primary chat model is unchanged** throughout. `search_x`
is a tool call, the social provider is a side-channel, the
result folds back as the tool's return value. The primary
keeps running on whatever model the user selected.

## Optional router heuristic (off by default)

For users who don't want to require an explicit `search_x` call
in every social-search turn, `athena.social.router` adds a
phrase detector:

```python
from athena.social.router import should_route, extract_query
should_route("search X for the merger", cfg=cfg)   # True iff opt-in
extract_query("search X for the merger")            # "the merger"
```

Off by default. `cfg.social_router_heuristic = True` opts in.
The heuristic is **conservative** — patterns are anchored at
line start, and a long list of negative tests pins shapes that
**don't** misfire (programming queries that mention "search" /
"tweets" incidentally, user statements about social as a
subject rather than a query).

Recognised shapes:

- `search X|Twitter|tweets|posts|social for|about <query>`
- `look up X for|about <query>`
- `what's on X about <query>`
- `what is X saying about <query>`
- `any tweets|posts about|on <query>`
- `latest tweets about <query>` / `latest on X about <query>`
- `find tweets about <query>`

Misfires are worse than misses here: an unwanted social call
costs a token AND leaks the user's query to a third-party API
they didn't expect. The explicit `search_x` tool is always
available as the safe fallback.

## What this delivers

This is the cash-in on T5-01 + T5-05. Adding a provider is
routine — the same `@register_provider` decorator pattern the
other seven providers use. The value is that a social-search
sub-task transparently uses the right backend while the user's
selected model stays primary. "Search X for X about Y" works
regardless of which model is in the chat — that's
capability-routing paying off.

## Smoke test

(Requires build-time OAuth credentials configured.)

```bash
athena providers       # social listed; social_search ✓; no token shown
athena                 # primary = some other model, e.g. claude-sonnet-4-6
> what are people saying on X about <topic>?
  # → "searching X via social"
  # → results fold into the primary model's answer
  # → primary model unchanged throughout
```

When no social provider is configured:

```bash
athena
> search X for athena
  # primary calls search_x as a tool
  # search_x returns {"available": false, "reason": "no social-search provider configured"}
  # primary reasons "I don't have access to X" and continues
```

## Related

- [Provider capabilities](provider-capabilities.md) — the T5-01
  manifest the `social_search` field lives on
- [Capability broker](capability-broker.md) — `best_provider_for`
  routing
- [Recall](recall.md) — `search_x` is in the `recall` toolset
  alongside `search_sessions`
