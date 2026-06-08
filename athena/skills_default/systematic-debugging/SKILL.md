---
description: Four-phase root-cause debugging — understand the bug before fixing it
name: systematic-debugging
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Systematic Debugging

Disciplined approach to non-trivial bugs. The premise: most "I'll
just try X" debugging burns hours and ships fragile fixes. The
right move is slower upfront and faster overall — understand the
bug fully before changing anything.

## When to use this skill

Use for bugs that aren't obvious from reading the stack trace, bugs
that reproduce intermittently, and bugs in unfamiliar code. Skip for
typos, obvious one-line fixes, and bugs where the stack trace points
at the exact line.

## The four phases

Run in order. Each phase has a clear exit condition. If you don't
hit the exit condition, you're not ready for the next phase.

### Phase 1: Reproduce reliably

You can't fix what you can't reproduce.

Goal: a SHORT command or set of steps that reliably triggers the
bug. Not "sometimes when I do X" — every time.

- Capture the exact inputs (request body, env vars, file contents,
  timing)
- Pin the conditions (OS, language version, dependency versions,
  cwd)
- Reduce the repro: keep stripping inputs until the bug just barely
  still happens. The minimal repro is the bug's fingerprint.

**Exit condition**: you can fail-on-demand. Often you discover the
bug is actually two bugs while reducing — that's a win.

If you genuinely can't reproduce: stop. Add observability first
([[observability-baseline]]), wait for it to happen again, then
return here.

### Phase 2: Locate

You know the bug fires. Where in the code does it actually go
wrong?

- Read the stack trace top-to-bottom — what's the FIRST frame in
  your code (not framework/library code)?
- Add prints / log lines AT key decision points and run the repro
  again
- Use the debugger if available: ``python -m pdb`` /
  ``node --inspect`` / IDE breakpoints
- Bisect: if the bug is recent, ``git bisect`` finds the commit
  that introduced it cheaply

**Exit condition**: you can point at the EXACT line where the
program first does something wrong. Not "somewhere in the
checkout module" — line 247 of ``checkout/totals.py``.

### Phase 3: Understand

You found WHERE. Now figure out WHY.

Build a one-paragraph explanation:

> "When the user submits a checkout with > 10 items, the
> ``compute_subtotal`` function iterates the list in
> ``checkout/totals.py:247``. The accumulator is reset inside the
> loop instead of before it (added in commit abc123 last Tuesday
> as part of the discount rewrite). For ≤ 10 items the bug is
> masked because [reason]. For > 10 items the totals truncate
> after item 10."

If you can't write that paragraph, you don't understand the bug
yet. Common gaps:

- You located the SYMPTOM, not the CAUSE
- The bug spans multiple functions and you only looked at one
- A timing / concurrency aspect you haven't traced

Don't proceed to fix without the paragraph.

### Phase 4: Fix

Now — and only now — fix.

- The fix should be SMALL. If it's huge, you're either fixing the
  wrong thing or smuggling in unrelated changes.
- Add a regression test that fails BEFORE the fix and passes
  AFTER. This is non-negotiable for non-trivial bugs.
- Verify the fix by re-running the repro from phase 1.
- Check adjacent code for the same pattern — a bug in one place
  often hides in three.

**Exit condition**: repro no longer triggers, regression test
green, adjacent code reviewed.

## Anti-patterns

- **Shotgun debugging**: change five things at once to "see what
  works." Even if it works, you don't know which change fixed it.
  Now you can't reproduce the bug to verify the fix.
- **Stack-trace blindness**: reading only the top line of a stack
  trace. The middle frames often hold the answer.
- **"Probably the cache"**: hand-waving at a likely culprit
  without checking. The cache is almost never the bug; if you
  think it is, prove it.
- **Premature optimization of the fix**: rewriting the function
  while you're in there. Refactor in a separate commit, see
  [[refactor-safely]].
- **Skipping phase 3**: jumping from "found the line" to "wrote
  the fix" without articulating WHY. Often produces fixes that
  paper over the symptom.

## When to stop and ask

After 30 minutes in phase 1 with no reliable repro: stop, ask the
user / on-call / oracle.

After 30 minutes in phase 2 with no clear location: same.

In phase 3, if you find yourself thinking "this code can't
possibly be doing what I'm seeing": it's almost always doing
exactly what it's doing, and you have a wrong assumption. Either
prove the assumption with a test, or ask someone to read the code
with fresh eyes.

Asking is faster than thrashing. The discipline is knowing when.
