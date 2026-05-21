# Computer use (desktop control)

Athena can observe your screen and (with explicit consent) drive
mouse/keyboard input. Two modes:

| Mode | What it does | Risk |
|---|---|---|
| **observe-only** (default) | Screenshots + a vision model describes what's there. Athena answers questions about your screen. NO input ever. | Low. Nothing happens to your machine. |
| **active control** | After the permission gate approves an action, athena clicks / types / presses keys / scrolls. | This is the inverse of the sandbox. There is no isolation. |

Off by default. Opt in per machine via `computer_use_enabled = true`.

## ⚠ Read this first

Computer use is the **inverse of T5-02's sandbox**. The sandbox
isolates code *away from* your machine; computer use points the
agent *at* your machine on purpose.

**There is no isolation here.** A click is a real click; a typed
character lands in whatever window has focus; a `Delete` press is
a `Delete` press. The permission model is the **only** safety
boundary.

That's not a flaw — it's the deal you accept when you ask an
agent to operate your computer. This page documents what the
boundary actually catches and what it doesn't.

## What the permission model catches

Every proposed input action is classified into one of three
tiers:

| Tier | Examples | Default behaviour |
|---|---|---|
| **observe** | screenshot, describe, locate | Always allowed, no prompt |
| **input** | click on a labeled button, type into a search box, scroll | Gated by mode + allow/denylist |
| **destructive** | click "Delete" / "Send" / "Pay" / "Confirm" / "Discard"; press Alt+F4 / Cmd+W / Delete; click an *unreadable* button (we don't know what it does); type `sudo` / `rm -rf` | **Always confirms, in every mode, every session, no exception** |

The classifier is **conservative by default** — an unknown or
unreadable target is treated as destructive. Better to ask an
extra time than to auto-execute something we can't describe.

What the gate decides, in order:

1. **observe-tier** → allowed; no prompt.
2. **Denylisted app** → refused; **no prompt**. The denylist
   always wins, even over the mode and even over destructive
   confirmation.
3. **App not in the allowlist** → refused. The allowlist is the
   user's explicit list of apps athena may control.
4. **`observe_only` mode** → every input refused. No prompt.
5. **destructive tier** → confirm callback fires. Asked every
   time, in every mode. Cannot be batched.
6. `per_action` mode + input tier → confirm fires once per
   action.
7. `per_session` mode + input tier → confirm fires once per
   task; the decision (yes OR no) persists for the rest of
   that task. Destructive **still** confirms each time.

## The kill switch — always available

A global halt with two trigger paths:

- **Ctrl+C** (always available once a computer-use task is
  active) — SIGINT-driven. Engages the switch and raises
  `KeyboardInterrupt` so athena's existing turn-cancel paths
  fire.
- **Hotkey** (default `ctrl+alt+k`) — best-effort. Requires
  the optional `pynput` package; when absent, Ctrl+C remains
  the active path.

The loop checks the switch at the **top** of every iteration. A
halt during a rate-limit sleep or during a vision call is
honoured on the next iteration; a halt during a `perform` call
lands via the SIGINT path immediately.

Engagement is **always logged** — the audit row carries the
reason ("Ctrl+C" / "hotkey ctrl+alt+k") so an operator can
correlate a halt with what athena was about to do.

## Safe defaults — what you get out of the box

| Knob | Default | Why |
|---|---|---|
| `computer_use_enabled` | `false` | Opt-in per machine. |
| `computer_permission_mode` | `"observe_only"` | No input until you explicitly switch modes. |
| `computer_app_allowlist` | `[]` | Empty → no app may be controlled. Mode change alone isn't enough; you must allowlist the apps you want athena to drive. |
| `computer_app_denylist` | `["1password", "bitwarden", "lastpass", "keychain", "keepass", "banking", "wallet", "ledger live", "metamask"]` | Sensible out-of-box guards for password managers + finance apps. The denylist always wins. |
| `computer_kill_hotkey` | `"ctrl+alt+k"` | Plus Ctrl+C, always. |
| `computer_max_actions_per_task` | `40` | Cap; loop stops at this many performs even when the model never says done. |
| `computer_max_actions_per_sec` | `2.0` | Rate limit. Prevents runaway click storms. |
| `computer_dry_run` | `false` | Set true → loop runs but `backend.perform` is never called. |
| `computer_backend` | `"auto"` | Picks by platform. Explicit values: `"windows"`, `"macos"`, `"linux"`, `"noop"`. |
| `computer_audit_path` | `None` → `<profile_dir>/computer_audit.jsonl` | The audit log. |

Every default is the safe one. To get athena to actually click
anything, you have to:

1. Set `computer_use_enabled = true`.
2. Add at least one app to `computer_app_allowlist`.
3. Switch `computer_permission_mode` from `observe_only` to
   `per_action` or `per_session`.

These are three deliberate steps. If you only do (1), athena
can still describe your screen but cannot click; if you only do
(1) + (3), no app is allowlisted so nothing controls anyway.

## The audit log

Every action — observe AND input, allowed AND denied — gets a
JSONL row in `<profile_dir>/computer_audit.jsonl` (or
`cfg.computer_audit_path`).

Each row carries:

```json
{
  "ts": "2026-05-20T13:42:00.123456Z",
  "type": "click",
  "target_desc": "Tab 2",
  "coords": [842, 310],
  "app": "VS Code",
  "tier": "input",
  "confirmed": true,
  "executed": true,
  "screenshot_sha256": "abcd...",
  "result": "ok"
}
```

The screenshot **bytes** never land in the log — only the
SHA-256. The bytes can be megabytes per capture and would grow
the log unboundedly. The hash is enough to correlate an action
back to "what athena was looking at" if you re-capture later.

## The tools

### Observe (no input)

| Tool | What it does |
|---|---|
| `computer_screenshot` | Capture the screen. Returns the image as base64 + geometry + audit row. |
| `computer_observe(question)` | Capture + route the screenshot to a vision-capable provider (T5-01 — local-preferred → offline-capable). The agent runtime performs the multimodal dispatch; the tool surfaces the routing decision + the image payload. |

### Input (gated)

Each input tool reaches `backend.perform` **only** after the
permission gate returns True. Without a real confirmation UI
wired in, the gate's default callback refuses everything — the
agent runtime supplies the real confirm via REPL or ACP.

| Tool | What it does |
|---|---|
| `computer_click(x, y, target_desc, button)` | Click left / right / double at `(x, y)`. `target_desc` is what's there ("Tab 2" / "Send"). Missing `target_desc` → destructive tier. |
| `computer_type(text, target_desc)` | Type into the active focus. Payloads with destructive verbs (`sudo`, `rm -rf`) → destructive. |
| `computer_key(key, target_desc)` | Press a single key or chord (`Return`, `ctrl+c`, `alt+f4`). Sensitive chords → destructive. |
| `computer_scroll(direction, target_desc)` | Scroll the active window. |

### The orchestrator (observe-act loop)

`computer_do(task)` (not yet a standalone tool — invoked by the
agent runtime) runs the loop:

```
loop:
  poll kill switch                   (engaged → halt)
  check actions-per-task cap         (hit → max_actions)
  screenshot                         (observe; never gated)
  no-op detection                    (4 unchanged → stuck)
  vision proposes next action
  if done → done
  classify(action)
  gate.check(action)
  audit.log(...)
  if not allowed → continue
  backend.perform(action)            ← THE ONLY CALL SITE
  rate-limit sleep                   (kill-switch-aware)
```

`backend.perform` is **the only** call site in athena's entire
codebase. It's reached **only** when the gate returns True. The
loop has tests pinning that contract — gate denial → zero
performs.

## `athena computer status`

```
athena computer status [--tail N]
```

Shows:

- Whether computer use is enabled
- Current permission mode + allowlist + denylist
- Kill hotkey + caps
- Active backend (and which backends the codebase knows about)
- Audit-log path + the last N rows with colour-coded results

This is your "what is athena set up to do" inspection surface.
Read-only — use config to change anything.

## Subprocess vs accessibility-tree classification

The classifier reads two signals per proposed action:

1. The **target description** the model surfaces from the
   screenshot (e.g. "click the *Delete* button"). If the
   target's text matches a destructive-verb pattern
   (`delete | send | pay | discard | sudo | …`), tier
   escalates to destructive.

2. The **accessibility tree** when the platform exposes one
   (UIAutomation on Windows, AX API on macOS, AT-SPI on
   Linux). Athena's current Windows backend returns `None`
   from `accessibility_tree()` — the classifier degrades to
   target-only reading.

The conservative-default rule fills the gap: when there's no
readable target *at all*, a click is classified destructive.
Adding a real a11y tree (a future optional dep) makes the
classifier more precise — fewer false-positive destructive
prompts — without changing the safety contract.

## Cross-platform support

| Platform | Observe | Input | Status |
|---|---|---|---|
| Windows | screenshot (ctypes + GDI), active app (GetForegroundWindow) | SendInput for click/type/key/scroll | shipped |
| macOS | — | — | backend skeleton; not implemented |
| Linux (X11 / Wayland) | — | — | backend skeleton; not implemented |

The contract is platform-agnostic. Adding macOS / Linux backends
is a new file in `athena/computer/backends/` implementing the
`DesktopBackend` protocol; the loop, gate, classifier, and
audit log are platform-independent.

## What this does not do

- **Doesn't auto-merge tabs of windows.** Computer use clicks
  the buttons you tell it to.
- **Doesn't bypass OS permissions.** On macOS the user has to
  grant Screen Recording + Accessibility to athena (or its host
  Python); on Wayland Linux, screen capture and synthetic input
  go through the desktop's portal/compositor APIs.
- **Doesn't share screenshots with a remote model unless you
  route it that way.** With a local vision model installed,
  screenshots stay on-device — the local-first stance applied
  to the most privacy-sensitive input.
- **Doesn't have an "always allow" mode.** Per-session is the
  loosest mode, and destructive still confirms each time.
- **Doesn't catch every dangerous action.** The classifier is
  conservative but it's not omniscient. Treat the audit log as
  your second source of truth — what athena actually did is
  what's in the log.

## How safe is this, really

The honest answer:

- **Observe-only** is genuinely low-risk. It's looking at your
  screen with a vision model. Local-vision keeps the bytes
  on-device.
- **Active control** is exactly as safe as the permission model
  + the kill switch make it. Tests pin the invariants:
  destructive always confirms; denylist always wins; gate
  denial → zero performs; kill switch always halts. But the
  classifier can still mis-classify a benign button as input
  (in which case `per_session` would auto-execute it) and
  there's no second line of defence if it does.

The right mental model: **treat the agent as a careful
collaborator with a mouse, not as a sandboxed process.** Per-
session is fine for narrow tasks where you've reviewed the
plan; per-action is the default for anything you wouldn't hand
the mouse to. Observe-only is the right answer when you just
want "see my screen, help me."

## Smoke test

```bash
# 1. Status (works regardless of enabled/disabled).
athena computer status

# 2. Observe (with enabled + observe_only):
#    ~/.athena/config.toml:
#      computer_use_enabled = true
#      computer_permission_mode = "observe_only"
athena
> what app is on my screen right now?
  # captures + routes to vision; describes the window;
  # NO input fires regardless of what the model wants

# 3. Active control (with per_action + an allowlisted app):
#      computer_app_allowlist = ["editor", "TextEdit", "VS Code Editor"]
#      computer_permission_mode = "per_action"
athena
> open the editor and type 'hello'
  # → "Click in editor at (...) on 'Window'? [y/N]"   ← per-action prompt
  # → after click approved: "Type 'hello' in editor? [y/N]"
  # → each input prompts; clicking a "Delete" control PROMPTS
  #   even mid-session

# 4. Kill switch:
#    During a multi-step task, press Ctrl+C (or the hotkey).
#    Loop halts at the top of the next iteration; audit log
#    records "halted by Ctrl+C".
```

## Related

- [Sandbox](sandbox.md) — what computer use is the **inverse**
  of
- [Provider capabilities](provider-capabilities.md) — the
  `vision` capability that local-preferred observe uses
- [Goal loop](goal.md) — Ctrl+C semantics are shared
