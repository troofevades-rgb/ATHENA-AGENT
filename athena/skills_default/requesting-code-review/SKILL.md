---
description: Pre-submit gates and review-readiness checks before asking a human to review
name: requesting-code-review
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Requesting Code Review

Disciplined pre-submit pass to make a code review fast and
focused. The premise: the reviewer's time is the bottleneck. Every
trivial issue they catch is one fewer real issue they have
attention for.

## When to use this skill

Use BEFORE marking a PR ready-for-review, before pinging a
reviewer, before submitting to a code-review tool or merge queue.
Skip for trivial fixes (typos, comment-only changes).

Pairs with [[code-review-workflow]] — that's discipline for the
person DOING the review; this is discipline for the person
REQUESTING one.

## The seven-gate checklist

Run all seven before clicking "ready for review."

### 1. Self-diff

```bash
git diff main...HEAD
```

Read your own diff top to bottom AS IF you were the reviewer.
Look for:

- Lines that need a comment (the "why" comment, not the "what")
- Debug code left in (``console.log``, ``print``, ``// TODO
  remove``)
- Unrelated changes you didn't mean to include
- Files in the diff that shouldn't be there

If you find these, fix them now. The reviewer shouldn't be the
one to spot them.

### 2. Tests run locally

Don't rely on CI. Run the relevant test files locally:

```bash
pytest tests/foo/  # the directory you changed
```

If any test fails, you're not ready. Fix or skip-with-justification
explicitly.

For UI changes, manually click through. Type checking is not the
same as feature checking.

### 3. Linter / formatter passed

```bash
ruff check athena tests
black --check athena tests
```

(Or whatever your project uses.) Style nits are the SMALLEST type
of review feedback you can prevent for free.

### 4. Scope is one thing

The PR does ONE thing. If the description needs "and also..." in
it, split.

Acceptable: "Add user-modeling factory + the config wiring it
needs."
Not acceptable: "Add user-modeling factory + unrelated typo fix +
cleanup of adjacent module."

Split via:

```bash
git checkout main
git checkout -b chore/typo-fix
git cherry-pick <typo-commit>
# new PR for the cherry-pick
```

### 5. PR description tells the story

Reviewer should understand without reading the code:

```
## Summary
What this changes. 1-3 sentences.

## Why
The motivation. Link the issue, the design doc, the user
request — whatever makes this a meaningful change.

## How
The approach in one paragraph. Name the key trade-off if
there is one.

## Testing
What you did to verify. Manual steps + which tests cover this.

## Notes for reviewer
- I'm unsure about [X]; would appreciate eyes there
- [Y] is out of scope but I noticed it; tracked in #1234
```

The "notes for reviewer" section is gold. It tells them where to
spend their attention.

### 6. CI is green (or will be)

If CI is already green on your branch — great. If CI hasn't run
yet but you've run the tests locally — fine. If CI is RED and
you're hoping the reviewer will figure it out: stop. Fix CI
first.

### 7. Branch is up to date with main

```bash
git fetch origin
git rebase origin/main
```

(Or merge, per your project's convention.) Reviewers shouldn't
have to mentally subtract changes that have happened on main
since you branched.

If rebase produces conflicts, resolve them now — the reviewer
shouldn't have to.

## When to request a SPECIFIC reviewer

Not every reviewer fits every PR. Tag intentionally:

- Touched the auth module → tag the auth owner
- Crossed a team boundary → tag the affected team
- Architectural change → tag the senior person who'll catch
  long-term implications
- Easy / docs / small → don't waste senior time; round-robin

Default to one primary reviewer + one optional second. Three
reviewers means three sources of bikeshedding and a slower
merge.

## When the review will be slow

If you know the reviewer is on vacation, in a different time
zone, or just busy — say so in the PR:

> "@reviewer is OOO; tagging @backup. Not blocking on @reviewer's
> input — feel free to ship if @backup approves."

This avoids the PR sitting in their queue for a week.

## During the review

When feedback arrives:

- **Don't get defensive.** The reviewer is helping you ship
  better code, not personally attacking you.
- **Respond to every comment** — either "fixed in commit X" or
  "discussed: keeping current approach because Y."
- **Resolve threads as you address them** so the reviewer can see
  what's left.
- **If you disagree**: discuss in the thread; ESCALATE if
  unresolved (tag a third party). Don't ignore feedback you
  disagree with.

## After merge

Brief retrospective with yourself:

- What did the reviewer catch that the seven-gate check could
  have caught?
- Add that to your personal pre-submit checklist for next time.

This is how the personal checklist improves over time, which
shrinks the reviewer's burden, which makes the team faster.
