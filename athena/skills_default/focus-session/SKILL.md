---
description: Single-task focus mode — no scope creep, no parallel threads
name: focus-session
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Focus Session

Operating mode for finishing one specific thing. Override of the
default "see-something-do-something" tendency that turns 30-minute
tasks into 4-hour sessions.

## When to use this skill

Use when the user asks for something concrete and bounded: "fix this
test", "implement this function", "make this PR ready." Do NOT use for
exploratory work ("what should we do about X?") — that genuinely
needs the wide lens.

## Rules of focus

### 1. Define done in one sentence

Before any tool fires, write the done condition explicitly:

> "Done when: test ``X::test_y`` passes and CI is green."
> "Done when: ``athena foo`` exits 0 with the new flag."
> "Done when: PR description is filled in and ready for review."

If you can't write a one-sentence done condition, the task isn't
focused enough yet — clarify before starting.

### 2. Out-of-scope is a category, not a judgment

When you notice something else that needs fixing — and you will —
write it down in a one-line scratch list, don't fix it:

```
out-of-scope (defer):
- the adjacent test also looks flaky
- this comment is wrong
- this function name is misleading
```

Surface that list at task end. Do NOT pre-emptively triage what's
"important enough" to handle now — that's how focus breaks. Treat
every out-of-scope item the same: park it.

### 3. One commit boundary

Land the work as one commit (or one tight series). If you find yourself
wanting to commit "and also this unrelated cleanup" — pull that
unrelated cleanup OUT into a separate commit or, better, a separate
session.

### 4. The trip-wire

If you've been working for >2x the original estimate, stop and ask:
"Am I solving the task I started, or have I quietly switched to a
bigger task?" If switched: roll back to the original scope or
explicitly negotiate a new scope with the user.

## When to break focus

Three situations override these rules:

1. **You've found a bug that's worse than the one you're fixing** —
   surface it immediately. Don't sit on a P0.
2. **The done condition turns out to be unreachable as stated** —
   stop and renegotiate with the user, don't silently expand scope.
3. **You realize the task is wrong** — if 20 minutes in you realize
   you're solving the wrong problem, say so. Don't grind on it.

Otherwise: park, finish, ship, then look up.
