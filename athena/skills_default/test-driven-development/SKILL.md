---
description: RED → GREEN → REFACTOR loop — let failing tests drive the design
name: test-driven-development
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Test-Driven Development

Disciplined RED → GREEN → REFACTOR loop for greenfield code. The
premise: writing the test BEFORE the implementation produces
better-shaped APIs, smaller scope, and a regression suite that
came for free.

## When to use this skill

Use for new code where the contract is clear: a new function with
a defined input/output, a new endpoint with a defined response
shape, a new tool implementation. Skip for exploratory work where
the design itself is the question (use [[spike]] for that), and
skip for one-off scripts.

Pairs with [[test-writing-discipline]] (what makes a good test)
and [[refactor-safely]] (the third phase of the loop).

## The cycle

### RED: write a failing test

Write a test that exercises the behavior you're about to
implement. Run it. Watch it fail.

- The failure must be MEANINGFUL — if the test fails because
  the function doesn't exist yet ("NameError"), that's fine; if
  it fails because of a typo in the test, fix the typo and re-run
- The failure message should tell you what's broken — if it says
  "AssertionError" with no detail, beef up the assertion to be
  more specific

This step is mandatory. A test that's never seen RED is a test
that might be silently broken — passing accidentally even with
buggy code.

### GREEN: minimum code to pass

Write the SIMPLEST implementation that makes the test pass.
Possibly stupid-simple:

```python
# test
def test_double(): assert double(2) == 4

# green — yes, really
def double(n): return 4
```

Then write another test that breaks this:

```python
def test_double_three(): assert double(3) == 6
```

Run. Watch the new test fail. Update the impl:

```python
def double(n): return n * 2
```

This "triangulation" forces the impl to be general only as much as
the tests demand. You never accidentally write speculation.

### REFACTOR: clean up with tests as a safety net

Now that the tests are green, restructure for clarity. Tests must
stay green at every micro-step.

- Rename for readability
- Extract helpers where the function does too much
- Remove duplication

See [[refactor-safely]] for the discipline here. The cardinal
rule: refactor changes structure, not behavior. Tests are your
guarantee of "no behavior change."

## What good test design unlocks

Done well, TDD produces:

- **Smaller, more focused functions** — because each test
  documents one behavior, the function tends to do one thing
- **Cleaner APIs** — writing the test first means you're using
  the API as a consumer before you've committed to its shape;
  ugly APIs become obvious immediately
- **Confidence to refactor** — the tests are a safety net for
  every subsequent change
- **Living documentation** — the test file is a more readable
  spec than most prose docs

## Limits and adaptations

TDD isn't a religion. It works best when:

- The contract is clear up front
- The unit is small enough that one test = one behavior
- Iteration is cheap (fast test suite)

It struggles when:

- The behavior is emergent (UI/UX, ML inference quality, complex
  layout) — for those, write *behavioral specs* you can verify by
  hand, then add automated tests after the design stabilizes
- The dependency surface is huge (legacy code with no seams) —
  add characterization tests first (capture existing behavior),
  THEN TDD new code on top

## Anti-patterns to refuse

- **Tests that follow the impl**: writing the test after the code,
  then claiming TDD. Useful tests, not TDD. The whole value of
  TDD is letting the test shape the design.
- **Big-bang RED**: writing 20 tests, then 200 lines of impl, then
  hoping it all goes GREEN. The cycle works one test at a time.
- **Skipping REFACTOR**: code piles up GREEN with growing
  duplication. Skip refactor once, you can; skip it ten times,
  you have a mess.
- **TDD-shaped procrastination**: writing tests for everything
  including framework code. Test YOUR logic; trust the framework.
- **No assertion specificity**: ``assert result is not None``
  passes even when ``result`` is garbage. Assert the value, the
  shape, the count — something concrete.

## When the test is hard to write

A test that's painful to write is a signal: the code under test
is poorly shaped. Common shapes:

- Too many dependencies (use dependency injection, mock at the
  boundary per [[test-writing-discipline]])
- Too many responsibilities (split the function)
- Hidden globals or singletons (parameterize)
- Stateful surprises (make state explicit in args / return values)

Don't fight the painful test by writing complex setup. Fix the
code shape and write a simpler test.
