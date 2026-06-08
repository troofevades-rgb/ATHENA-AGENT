---
description: Refactor without breaking behavior or smuggling in feature changes
name: refactor-safely
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Refactor Safely

Disciplined approach to refactoring so the change preserves behavior
and the diff stays reviewable. The premise: refactors that fail almost
always fail because the developer quietly bundled in a behavior change
or fix while moving the code around.

## When to use this skill

Use when restructuring existing code: renaming, extracting functions,
splitting modules, changing internal APIs without changing external
ones. Skip for greenfield work or for refactors that are explicitly
part of a behavior change.

## The cardinal rule

> **A refactor changes structure. It does not change behavior.**

Behavior changes go in SEPARATE commits, BEFORE or AFTER the refactor,
never inside it. Violations of this rule are the single largest cause
of refactor regressions.

## The five-step protocol

### 1. Verify the safety net

Before touching anything, run the tests covering the code you'll
refactor. They must be green and they must actually exercise the
behavior you want to preserve. If coverage is thin: ADD tests first
(separate commit), then refactor.

### 2. Refactor in tiny steps

Each step should be small enough that you can describe it in one
sentence and verify it via a fast test run. Examples:

- "Rename ``foo`` to ``bar`` (no signature change)"
- "Extract lines 40–60 into ``_compute_x()``"
- "Move ``Config`` dataclass from ``module_a`` to ``shared/types.py``"

Big bang refactors fail in confusing ways. Tiny refactors fail in
isolated ways you can pinpoint immediately.

### 3. Tests pass after each step

After every step, the tests are green. Not "I'll fix the tests at the
end" — green NOW. If the tests can't be green after a step, the step
is too big. Decompose.

### 4. The mechanical-change test

Look at your diff. Ask: "Could this diff have been produced by a
purely mechanical transformation?" If yes, you're refactoring. If
no — if the diff contains logic changes, new branches, new defaults,
new edge-case handling — you've drifted into behavior change. STOP.
Roll back the behavior change to a separate commit.

### 5. Commit small, often

Each refactor step is a separate commit with a clear message:

```
refactor: extract _compute_x from foo()
refactor: rename foo→compute_x at call sites
refactor: move Config dataclass to shared/types
```

Small commits give you cheap rollback. They also make code review
trivial — reviewers can verify each step independently.

## Common drift patterns

These are signals that your refactor is sneaking in behavior changes:

- "While I'm here, let me fix this bug" — pull it OUT into a separate
  commit, ideally a separate PR.
- "While I'm here, let me add this validation" — same, separate.
- "While I'm here, let me improve this error message" — same.
- "This function would be cleaner without the legacy default" —
  removing or changing a default IS a behavior change. Separate.

The "while I'm here" pattern is how a clean refactor becomes a 500-line
PR that reviewers can't follow and that breaks production.

## When the refactor IS the change

Some refactors expose intentional behavior changes (e.g., extracting
a function intentionally makes a behavior visible/swappable). That's
fine — but be EXPLICIT in the commit message: "refactor + behavior:
extract X to allow Y to override its default." Reviewers now know to
look for the behavior change.

## Rollback strategy

If the refactor goes sideways and tests fail in unexplained ways:

1. ``git stash`` or branch — preserve the in-progress work
2. Bisect the steps you committed to find where green→red
3. Read that one step's diff carefully

If you can't find the breaking step in 15 minutes: roll back the whole
refactor and start over with smaller steps. The cost of starting over
is usually less than the cost of fighting through.
