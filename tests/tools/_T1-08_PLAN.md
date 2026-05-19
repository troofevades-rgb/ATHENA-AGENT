# T1-08 plan — web.py inventory and migration map

Pre-implementation surface map for the SSRF-defense phase.

## Public surface of `athena/tools/web.py`

| Function | Arg | Method | Follows redirects | URL source |
|---|---|---|---|---|
| `WebFetch` | `url` | GET | yes | **agent / user** (must validate) |
| `WebSearch` | `query` | dispatches to one of three backends below | — | — |

## Private search backends

| Function | URL | Source | Migration |
|---|---|---|---|
| `_search_duckduckgo` | `https://html.duckduckgo.com/html/` | hard-coded | Optional. Run through `validate_url` to gain DNS-rebinding defense on the public endpoint. |
| `_search_brave` | `https://api.search.brave.com/res/v1/web/search` | hard-coded | Same as above. |
| `_search_searxng` | `f"{ATHENA_SEARXNG_URL}/search"` | **env var** (operator-controlled, may point at a private host) | Must validate; the env var can legitimately be a private IP for a self-hosted SearxNG, which means it will trigger the approval callback / `allow_external_urls`. |

## HTTP client

`httpx` (`httpx.Client(timeout=_TIMEOUT, follow_redirects=True)`) is used
in every fetch site. `follow_redirects=True` means a 30x response with
a `Location:` header is followed automatically — redirects must be
re-validated to defeat redirect-based SSRF.

## Internal callers (`grep -rln 'tools.web' athena/`)

The `WebFetch` and `WebSearch` tools are exposed through the registry
and called by the agent loop. No direct internal callers outside the
tool registration itself.

## Test surface that fetches private addresses

`grep -rn 'localhost\|127\.0\.0\.1\|192\.168' tests/ --include="*.py"` —
results that exercise `web.py`:

- None observed at the tool layer. Existing `tests/tools/` test
  files do not appear to spin up a local HTTP server and hit
  `WebFetch` against it.

However, `tests/mcp/` and other suites may set up local HTTPish
servers — those are already gated behind a different code path
(MCP HTTP transport, not `web.py`), so they don't need
`allow_external_urls()`.

## Migration plan recap

T1-08.2 creates `athena/safety/url_safety.py`.
T1-08.3 tests it.
T1-08.4 migrates `web.py` (this inventory's purpose).
T1-08.5 migrates whatever test fixtures fail.
T1-08.6 verification grep + CHANGELOG + docs.

## Key adaptation note

The T1-08 design doc skeleton assumes the project's approval callback
is `(prompt: str) -> bool`. The actual project signature is
`(tool_name: str, args: dict) -> "allow"|"deny"` (same as T1-07).
`url_safety.validate_url` adapts: it calls
`callback("url_safety", {url, blocked_ips})` and treats any non-`"allow"`
return as denial. Tests use the same `_allow_cb`/`_deny_cb` helpers as
`tests/safety/test_path_security.py`.
