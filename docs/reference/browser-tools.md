# Persistent CDP browser tools

Playwright-backed browser automation that **persists across tool
calls within a session**. Cookies, localStorage, and open pages
survive — multi-step web workflows reason over the same browser
state instead of relaunching per call.

## Tools

| Tool                       | Purpose                                                    |
|----------------------------|------------------------------------------------------------|
| `browser_navigate`         | Navigate to URL; capture log + per-domain throttle         |
| `browser_screenshot`       | Save PNG; optional `analyze_prompt` routes via `vision_analyze` |
| `browser_extract_text`     | Visible text from page or selector                         |
| `browser_extract_links`    | All `<a href>` as `[{href, text}]`                         |
| `browser_click`            | Click selector                                             |
| `browser_fill`             | Fill input by selector                                     |
| `browser_wait_for`         | Wait for selector (default 10 s)                           |
| `browser_get_cookies`      | Cookies for the current context                            |
| `browser_close`            | Tear down the session browser (user-data dir persists)     |

All under `toolset="browser"`.

## The persistence model

**One Chromium context per athena session.** The first
`browser_*` tool call launches Chromium; every subsequent call
reuses the same context. Cookies set on navigation A are still
present on navigation B. Open pages, localStorage, and any
session-bound state survive across the multi-step chain.

Per-session user-data dir lives at
`<browser_user_data_root>/<session_id>/` (defaults to
`~/.athena/browser/<session_id>/`). Two concurrent athena
sessions don't share cookies — they get distinct user-data
dirs. The dir persists after `browser_close()` so a future
session resume can reattach to the same cookie jar (wiring to
T2 resume is a small follow-up).

## Lazy launch

Constructing a `BrowserSession` (which happens at every athena
session start, regardless of whether the agent uses browser
tools) does **not** launch Chromium. Only the first
`browser_*` tool call triggers `ensure_started()`. An athena
session that never touches browser tools pays no Chromium
cost. Pinned by `test_unused_browser_never_launches` — the
test patches `sync_playwright` to `AssertionError` and runs a
full construct → bind → close cycle.

## Capture log (accountability surface)

Every `browser_navigate` appends a JSONL row to
`<profile_dir>/browser_capture.jsonl`:

```json
{"ts":"2026-05-20T13:42:00.123456Z","session_id":"s-1234",
 "url":"https://crt.sh/?q=example.com",
 "final_url":"https://crt.sh/?q=example.com",
 "status":200, "title":"crt.sh | example.com",
 "screenshot_path":"", "content_sha256":"abcd…"}
```

The page bytes themselves are not stored — only a SHA-256 of
the served content. Same calculus as the T4-01 vision hash-log
and T6-04 computer audit: provenance over volume.

This log is the accountability surface. The tool isn't a
covert-research aid; it captures what an analyst's browser
would see on a public page, with the trail to prove it.

## Politeness throttle

Per-domain minimum interval between navigations (default
`cfg.browser_min_interval_s = 1.0`). The persistent browser
lets the agent navigate fast; without the throttle, "search →
click result → click another result" hammers a single site.

Cross-domain navigations don't trigger a sleep — each domain
has its own "last seen" timestamp. The throttle's in-memory
map doesn't survive restarts (intentional — a fresh session
shouldn't pay last session's wait penalty).

Set to `0` to disable. Reasonable for trusted internal targets.

## Realistic fingerprint, NOT access-control evasion

The default User-Agent is a current desktop Chrome string
(`Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...
Chrome/124.0.0.0 Safari/537.36`). This avoids trivial
bot-blocks on legitimate research targets that serve different
HTML to stock Playwright UAs.

**It is NOT** a CAPTCHA solver. **It is NOT** a login-wall
bypass. If a target requires authentication, the operator
provides credentials explicitly via `browser_fill` on the
login form. The tool isn't built to defeat anti-bot systems —
it's built to behave like a normal browser on pages the
analyst is authorized to visit.

`robots.txt`: the tool does not currently parse it. Add a
respectful surface in a follow-up if needed.

## Screenshot → vision (the multiplier)

`browser_screenshot(analyze_prompt="describe this page")`
does the screenshot AND runs T4-01's `vision_analyze` in
describe mode on the result, in one call:

```json
{
  "path": "/profile/browser/shots/sess/shot_20260520_134300_001234.png",
  "bytes": 84512,
  "analysis": "The page shows a certificate transparency search interface..."
}
```

A lot of sites render data into the DOM in ways that are
painful to extract as text but trivial for a multimodal model
to read off a screenshot. This combo is the fast path for
"just tell me what this page shows."

## Tool result shape

Every tool returns JSON (str). Success path carries the
operation-specific keys (e.g. `{"clicked": "#go",
"final_url": "..."}`). Failure path always carries
`{"error": "<message>", ...}`. The tool layer never raises
into the model loop — Playwright exceptions become structured
JSON the model can reason about.

When the operator has disabled browser tools
(`cfg.browser_enabled = false`), every call returns
`{"error": "browser_enabled=False; ...", "available": false}`
without touching Playwright.

## Configuration

```toml
# ~/.athena/config.toml — defaults shown
browser_enabled = true
browser_engine = "chromium"
browser_headless = true
browser_user_data_root = ""             # "" → ~/.athena/browser
browser_capture_path = ""               # "" → <profile>/browser_capture.jsonl
browser_screenshots_dir = ""            # "" → <profile>/browser/shots
browser_nav_timeout_s = 30
browser_min_interval_s = 1.0            # politeness throttle
browser_block_downloads = true          # footgun guard
browser_user_agent = ""                 # "" → realistic desktop Chrome UA
```

## Dependencies

External: Chromium browser binary. Install via:

```bash
pip install -e ".[browser]"
playwright install chromium
```

Pure-Python `[browser]` extra: `playwright>=1.40`. Without
Chromium installed, every browser tool returns the
"Playwright is not installed" install-hint error.

## Non-goals

- **CAPTCHA solving.** Out of scope. The tool is for public
  pages an analyst is authorized to read.
- **Login-wall bypass.** Out of scope. Credentials are
  operator-provided via `browser_fill`.
- **Headed automation in headless deployments.** The
  `cfg.browser_headless` switch is yours; the tool doesn't
  spawn a window unless you ask.
- **Cross-session sharing.** Per-session user-data dirs are
  isolated. Sharing a cookie jar between athena sessions is a
  deliberate design choice — opting in would need explicit
  config.

## Reference

- Session manager + ContextVar: `athena/browser/session.py`
- Capture log + throttle: `athena/browser/capture.py`
- Tool surface: `athena/browser/tools.py`
- Agent lifecycle wiring: `athena/agent/core.py` (constructor +
  `Agent.close`)
