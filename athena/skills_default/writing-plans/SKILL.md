---
description: Write implementation plans in bite-sized tasks with paths and code
name: writing-plans
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Writing Plans

Disciplined approach to writing implementation plans before
starting non-trivial work. The premise: a 15-minute plan front-
loads decisions that would otherwise be made under time pressure
mid-implementation, where they get made worse.

## When to use this skill

Use for work that will take >1 hour or touch >3 files. Skip for
tight bug fixes, single-function changes, and exploratory work
(use [[spike]] for that).

Distinct from [[decision-record]] — that's about WHY a choice was
made. A plan is about WHAT to do and IN WHAT ORDER. Both are
short docs; they answer different questions.

## The plan template

A plan is a single markdown file, ideally <3 pages, with these
sections:

```markdown
# <Title>

## Context

What's the problem? What constraints frame the work? Two or three
sentences. If a reviewer can't understand the WHY in this section,
they can't evaluate the HOW.

## Design

What's the approach? Block diagram or short prose. Name the
specific functions, classes, modules, or files that will change.
Name the trade-off being made and why this side of the trade-off.

## Files touched

Bulleted list:
- **New**: ``athena/foo/bar.py``, ``tests/foo/test_bar.py``
- **Edited**: ``athena/baz.py`` (function ``frobnicate`` and its
  callers in ``athena/qux.py``)
- **Removed**: none (or list)

If you can't enumerate the files, the design isn't concrete
enough yet.

## Steps

Bite-sized, ordered. Each step is small enough that you can
verify it independently:

1. Add empty ``athena/foo/bar.py`` with the module docstring
2. Implement ``compute_x`` per the design
3. Add unit tests for ``compute_x`` covering [edge cases]
4. Wire ``compute_x`` into the existing pipeline at ``baz.py:142``
5. Update ``test_pipeline`` to assert the new behavior
6. Run the full suite; expect 3 new tests passing, no regressions

## Test plan

Specific tests that need to exist and pass. Beyond unit tests:

- Manual verification: ``python -m athena foo --bar`` works
- Integration: the existing ``test_e2e_pipeline`` still passes
- If touching UI: actually click through; what should happen

## Out of scope

Bullets of things you noticed but are NOT doing in this work.
Saves the reviewer the question "why didn't you also fix X?"

## Verification

Specific commands the user can run to confirm the work is done.
```

## Why bite-sized steps matter

Each step in the plan is something you can stop after. If you're
interrupted, you finish the current step and have a clean stopping
point. If you make a mistake, you roll back at most one step.

Bad plans have step #4 = "implement the whole feature." Good plans
break that into 6 things you can verify independently.

## The "is this the right thing to do?" check

Before writing code, re-read the plan and ask:

- **Right size?** If steps span days, sub-divide. If steps are
  trivial, you might be over-planning — combine.
- **Right order?** Should anything later happen earlier (e.g.,
  add tests before changing behavior)?
- **Anything missing?** Migration step? Rollout? Documentation?
- **Anything extra?** Cleanup that should be a separate plan?

Half the value of writing the plan is the rethink-the-plan moment.
Re-reading your own design with fresh eyes catches the gotchas.

## Plan formats

### Inline (for small work)

In an issue comment or PR description, 5-15 lines. No file.

### Repo file (for medium work)

``docs/plans/<short-name>.md`` or wherever your project keeps
them. Lives in the repo so reviewers can comment.

### External (for cross-team or strategic work)

A doc tool with comment threads (Notion, Coda, Google Docs).
The plan becomes a discussion artifact.

Pick the lightest format that fits — over-formalizing is its own
anti-pattern.

## Anti-patterns

- **Plan as fiction**: writing what you wish the work were like.
  Plans need to reflect the ACTUAL shape of the code, including
  the messy parts.
- **Plan without files**: "I'll refactor the auth module."
  Which file? Which function? Without that level, the plan
  doesn't help the implementer.
- **Plan with no test plan**: shipping plan without verification
  means you ship the wrong thing more often.
- **Plan you never re-read**: written, then never opened again
  during implementation. The plan is the work product, not just
  the kickoff artifact.
- **Plan instead of work**: 4-hour planning sessions for 2-hour
  tasks. The plan is a tool, not a deliverable.

## When the plan changes mid-implementation

It will. New facts emerge from the code. Decisions get revisited.

When it changes meaningfully:

1. Update the plan IN-PLACE (don't quietly drift)
2. Note WHY in the plan ("step 4 became 4a, 4b because X turned
   out harder than expected")
3. If the change is large enough to affect the design: tag a
   reviewer

Plans are living docs during implementation, frozen artifacts
after merge. The frozen version is your record of what shipped
and why.
