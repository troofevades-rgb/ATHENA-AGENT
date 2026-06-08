---
description: Systematic code-review pass before claiming a change is done
name: code-review-workflow
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Code Review Workflow

A disciplined self-review pass between "the code compiles + tests pass"
and "ship it." Catches the class of bugs that pass tests because tests
were never written for them.

## When to use this skill

Use before reporting a non-trivial change complete: feature work,
refactors of >50 lines, anything touching control flow, persistence,
or external surfaces. Skip for one-line typo fixes.

## The five-pass review

Run these in order. Each pass is a different lens — don't merge them
or you'll catch fewer issues.

### 1. Diff hygiene

```bash
git diff --stat
git diff
```

- Any file in the diff that shouldn't be there? (`.env`, lockfiles you
  didn't mean to touch, generated artifacts, IDE configs)
- Any deletions you can't explain in one sentence?
- Any "fix typo"-sized changes mixed into a feature commit?

### 2. Boundary check

For every new branch, ask: what's the input range that gets here?

- Empty collection, single-element collection, very large collection
- ``None`` / null / undefined
- The unicode case (non-ASCII, RTL, zero-width)
- The race case (concurrent writers, partial failure)
- The "user is mid-edit" case (stale state)

Don't add error handling for impossible cases — but write down one
example input for each branch and prove it works.

### 3. Reversibility audit

For every action the new code can take:

- If it fails partway, is the system in a recoverable state?
- Is there a retry loop, and does it have a backoff + a cap?
- Is there a write that needs ``fsync`` / atomic-replace?
- Is there a destructive operation that needs a confirmation guard?

### 4. The "next person" pass

Read your own code as if you opened the file cold tomorrow:

- Are the names ones a stranger would understand?
- Is there a comment explaining *why* the non-obvious choice was made?
  (not *what* — the code shows what)
- Could a one-line example in the docstring save 5 minutes for the
  next reader?
- Is there dead code or commented-out code left behind?

### 5. Verification

- Run the tests you wrote.
- Run the tests *adjacent* to what you changed (one directory up).
- If UI: actually click through the change in the browser.
- If CLI: actually invoke the command, with at least one edge-case arg.

Type-checking and a green suite verify *correctness of code*. The five
passes verify *correctness of feature*. They're different things.
