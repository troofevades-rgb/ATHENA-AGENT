# T6-04R recon — computer use over approval_guard

Before code: confirm the contracts so the refactor doesn't fight
the rest of the system.

## (a) `request_approval` — the exact call

`athena/safety/approval_guard.py`:

```python
async def request_approval(
    resource_id: str,
    prompt: Callable[[str], Awaitable[bool]],
    *,
    auto_approve_in_background: bool = False,
) -> bool
```

Behavior:

| Context | Cache hit? | Action |
|---------|-----------|--------|
| FOREGROUND, `resource_id` in grants | yes | return cached bool, no prompt |
| FOREGROUND, miss | no | `await prompt(resource_id)` → cache + return |
| not FOREGROUND, `auto_approve_in_background=True` | — | return True immediately |
| not FOREGROUND, otherwise | — | raise `ApprovalDeniedInBackground` |

Grants live in `_approval_grants: ContextVar[dict[str, bool]]`.
`scope_fresh_approvals()` returns a Token; `reset_approvals(token)`
restores. `current_grants()` is a read-only snapshot.

### sync vs async tension

`request_approval` is **async**. athena's tool dispatch is
**sync** (every `@tool` function returns `str`; the dispatcher
calls them as plain functions). Calling async code from sync
via `asyncio.run` works *only* when no event loop is already
running on this thread — which is exactly the case some of the
time (gateway / ACP paths run in a loop).

**Resolution.** Add a sync sibling `request_approval_sync` to
`approval_guard.py` that shares `_approval_grants` and the
write-origin gate, but accepts a sync `prompt: Callable[[str],
bool]`. Same ContextVar means a grant cached via either path
short-circuits the other. This is the only safe shape — pull
this lever once at the safety boundary, never inside the gate.

## (b) Active approval callback

`athena/safety/approval_callback.py`:

```python
ApprovalFn = Callable[[str, dict], str]   # → "allow" | "deny"
```

Default: `_interactive_approval(tool_name, args)` calls
`ui.confirm`. Forks install `AUTO_DENY` at thread entry (warns
on every prompt — so a runaway fork is visible).

The callback ContextVar is `_approval`; get via
`get_approval_callback()`, set via `set_approval_callback(fn)`,
unset via `reset_approval_callback(token)`.

**Bridge.** The computer-use gate's prompt argument to
`request_approval_sync` is going to be a one-liner that calls
`get_approval_callback()` and converts the "allow" / "deny"
string into a bool. This way:

  - Interactive sessions reach `_interactive_approval` → `ui.confirm`
  - ACP / gateway runs reach whatever was bound for the session
  - Forks reach `AUTO_DENY` — and `request_approval_sync` raises
    `ApprovalDeniedInBackground` *before* the callback fires
    (cheaper and safer than relying on `AUTO_DENY`)

## (c) Background-denial confirmation

`request_approval` (and the planned sync sibling) call
`get_current_write_origin()`. Origins that count as background:

  - `BACKGROUND_REVIEW` (per-turn review fork)
  - `CURATOR` (skill-curator fork)
  - `MIGRATION` (one-shot import)
  - `SYSTEM` (internal lifecycle)

Set inside `athena/agent/fork.py:178` —
`set_current_write_origin(write_origin)` at fork entry,
restored in finally. So a fork running tools cannot call
`request_approval` without raising `ApprovalDeniedInBackground`.

### Gap to flag: the **goal-loop continuation** runs in FOREGROUND

T5-07's autonomous continuation loop (`/goal active`) does NOT
set a non-FOREGROUND origin — it injects synthetic continuation
turns into the *same* agent context. That means
`request_approval` alone wouldn't deny goal-loop turns.

Two reasonable answers, picking the second:

  **(i)** make the goal loop set a new "AUTONOMOUS" origin
       before each continuation turn. Heavy: would change
       behaviour of every other tool that consults
       `request_approval`, and we'd want to think about whether
       e.g. memory writes should count as background under
       /goal active. Out of scope here.

  **(ii)** computer-use gate adds its *own* check on top of
       approval_guard: a configurable
       `computer_deny_during_goal_loop` (default True) that
       refuses input/destructive when an active goal state
       indicates the loop is driving turns. Background check
       still comes free from approval_guard for forks; the goal-
       loop check is the computer-use-specific belt-and-braces.

Picking **(ii)** keeps the change scoped to computer use and
documents the gap explicitly. Status of the goal loop is
readable via `athena/goal/state.load_state(profile_dir)` — if
`state and state.status == "active"`, treat as background.

## (d) Vision resolution for the screenshot path

`athena/media/registry.py:MediaRegistry.backend_for("vision")`
returns the provider *class* that declares `vision=True` in its
T5-01 capability manifest, preferring `is_local=True` when
`cfg.media_backend_prefer == "local"`. Returns `None` if no
provider on this host declares the capability.

Already consumed in the existing T6-04 `computer_observe` tool
(`athena/computer/tools.py:265`) and in T4-01's
`vision_analyze` describe mode. The T6-04R refactor keeps that
path unchanged — observe tier needs no approval, so the
existing vision routing already does the right thing.

## (e) Existing computer-use surface (what stays vs. what changes)

Files already in `athena/computer/`:

| File | Disposition |
|------|-------------|
| `contract.py` (`Action`, `Screenshot`, `DesktopBackend`) | keep as-is |
| `backends/windows.py` + `detect.py` | keep as-is |
| `audit.py` (`ActionAuditLog`) | keep — audit row gains a `tier` + `approval_via` field but shape compatible |
| `permission.py:classify` + `_DESTRUCTIVE_HINTS` + `_DESTRUCTIVE_KEYS` | **keep** — this is the classifier the gate consults |
| `permission.py:PermissionGate(cfg, confirm)` | **refactor**: replace the bespoke `confirm` callback path with `request_approval_sync`-backed approval; preserve denylist + allowlist + observe_only short-circuits |
| `killswitch.py` | keep — augment with `reset_approvals` call so a panic also drops grants |
| `loop.py:computer_do` | unchanged at the call site; the gate inside changes |
| `tools.py` | unchanged at the @tool registration site; the gate inside changes |

## Refactor plan

**T6-04R.2** — observe tier verification (no code change beyond
a regression test). Pin: `computer_screenshot` / `computer_observe`
do NOT consult any approval surface; calling them under
`AUTO_DENY` and under `set_current_write_origin(BACKGROUND_REVIEW)`
still succeeds.

**T6-04R.3** — the gate refactor. Two concrete changes:

1. `athena/safety/approval_guard.py` gains
   `request_approval_sync(resource_id, prompt: Callable[[str], bool],
   *, auto_approve_in_background: bool = False) -> bool`.
   Mirrors the async version. Same ContextVar.

2. `athena/computer/permission.py:PermissionGate` is rewritten:
   - `__init__` no longer takes `confirm`; reads the active
     approval callback at check time.
   - `check(action)` consults `classify(action)`, then dispatches:
     - observe → return True
     - denylisted / not-allowlisted / observe_only → return False
       (no approval call — config-driven refusals shouldn't burn
       a user prompt)
     - destructive → call `request_approval_sync` with a
       resource_id that **encodes the specific action** (e.g.
       `f"computer_destructive::{sha256(action.describe())[:16]}"`)
       so the cache never hits and every destructive action
       freshly prompts
     - input → call `request_approval_sync` with a stable
       resource_id (`"computer_input"`) so the grant caches
       per turn / per scope
   - `goal_loop_active(cfg)` check via `load_state` — if the
     loop is active and `cfg.computer_deny_during_goal_loop`
     (default True), treat as background → refuse input/
     destructive with a clear message.
   - `reset_session()` becomes a wrapper around
     `reset_approvals(token)` — same intent, real machinery.

3. Add `computer_use_panic(cfg)` that:
   - sets a process-wide disable flag the gate consults
     (`_panic_engaged`)
   - calls `reset_approvals(scope_fresh_approvals())` to drop
     every cached grant
   - logs at WARNING

**T6-04R.4** — input tools route through the new gate. Existing
tools.py already dispatches via `permission.PermissionGate` in
the loop, so this is mostly a no-op verification — pin "no
backend bypass": all backend writes go through the gate (the
single-callsite invariant from T6-04.5).

**T6-04R.5** — docs + changelog, leading with the safety model.

## Open questions resolved during recon

1. **Should observe tools become async too?** No — observe tier
   has no approval call, so there's nothing to await. Keep them
   sync.

2. **Does the existing `ConfirmFn` signature need to stay for
   back-compat?** No — `PermissionGate` is internal to athena,
   no external callers. Remove it.

3. **Should we deprecate `approval_callback.py` in favor of
   `approval_guard.py`?** Out of scope. `approval_guard`'s
   prompt parameter can call back into `approval_callback`'s
   `get_approval_callback()` — both keep working.

## Verifying T4-01 (vision) is present

Vision module + tool ship in T4-01 (already on master,
commit `21cee7e`). `pytest tests/vision -q` is green.
`athena/vision/analyze.py` registers `vision_analyze` and
`athena.media.registry.MediaRegistry` answers
`backend_for("vision")` with Ollama in the default install.

Prereq satisfied. Proceeding to T6-04R.2.
