---
description: Time-boxed throwaway experiment to validate an idea before committing
name: spike
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Spike

Disciplined throwaway experiment to answer ONE specific question
before committing to a design. The premise: when you don't know if
an idea will work, days of upfront design are wasted if the idea
turns out infeasible. A 90-minute spike resolves the uncertainty
cheaply.

## When to use this skill

Use when facing a decision with technical uncertainty:

- "Can our DB handle this query pattern at production scale?"
- "Does this library actually have feature X with the constraints
  we need?"
- "Is approach A or approach B more performant for our case?"
- "What's the actual shape of this API's response?"

Distinct from [[focus-session]] — that's discipline for finishing
something concrete. Spike is discipline for LEARNING something fast.

## The spike contract

Before starting:

### 1. Write the question

In one sentence:

> "Can we render the full owl in <50ms on a cold start with
> no native deps?"

NOT "let me explore rendering approaches." Specific enough that
the spike has a clear pass/fail.

### 2. Time-box

Set a hard limit. 30 min / 90 min / 4 hours. Stick to it.

The point of a spike is to bound the learning cost. An unbounded
spike turns into the thing the spike was supposed to prevent —
days of investment in an idea that might not work.

### 3. Declare it throwaway

Spike code is NOT production code. Write it sloppy. Hardcode
things. Skip tests. Use the worst library if it's fastest.

Throwaway-ness is the SOURCE of speed. The moment you start
writing production-quality code in a spike, you've lost the
benefit.

Mark the branch clearly: ``spike/owl-render-perf``. Mark the
files: comments at the top saying "SPIKE — do not merge." Make
it obvious to future-you and reviewers that this isn't real.

## The spike workflow

### Execute

Build the minimum thing that answers the question. If the
question is "does library X work for use case Y?", import library
X and try use case Y. Don't build a wrapper, don't add tests,
don't worry about the surrounding system.

If you hit secondary questions ("how should I configure X?"),
write them down and answer with whatever's cheapest — read the
docs, ask, guess. Don't fork into a secondary spike unless the
answer matters to the primary question.

### Capture

When the spike ends — either you have the answer or the
time-box expired — write a one-page summary:

```
SPIKE: owl-render-perf
Date: 2026-05-27
Question: Can we render the full owl in <50ms cold start
          with no native deps?
Time spent: 90 min (full budget)

Answer: Yes, with Pillow. 38ms on the test machine for a
        64x32 quadrant render. Tested with: <inputs>

Caveats:
  - Pillow add ~1.5MB to the bundle
  - Quadrant rendering quality degrades below 32x16
  - Did NOT test on Windows or ARM macOS

Implications for design:
  - Pillow is the right choice; rejected raw PIL-less approach
  - Want to confirm Windows behavior before final commit
```

This summary IS the deliverable. Future-you and the team need
the answer, not the spike code.

### Discard

Delete the spike branch. Drop the code. Keep only the summary.

If the spike was a success, the next session implements the
idea PROPERLY, with tests, in production-quality code. The spike
code does NOT get adapted into prod — that's how you end up
shipping hardcoded constants and no tests.

If the answer is "this won't work," the team has saved days of
investment. Worth it.

## When NOT to spike

- The question is purely a design choice (no technical
  uncertainty) — make the decision with [[decision-record]],
  don't waste time prototyping
- The question is answerable by reading docs or code — read first,
  spike only if the answer isn't there
- The cost of doing the real thing is comparable to the spike —
  if real takes 2 hours and a spike takes 1, just do real

## Anti-patterns

- **The infinite spike**: "I'll just keep poking at this." Set
  the time-box and HONOR it. If you blow through, declare it,
  re-budget, or kill it.
- **The graduated spike**: starting throwaway, slowly adding
  tests and structure, eventually trying to merge. Either commit
  to throwaway OR commit to real — switching halfway burns the
  benefit of both.
- **The skipped summary**: shipping the answer in your head and
  not writing it down. Three months later nobody remembers.
- **Multiple primary questions**: a spike answers ONE question.
  If you have three, run three spikes (sequentially), each with
  its own time-box.

## A note on shape

A good spike often produces ugly code that proves a point AND
a clean paragraph of prose that captures the point. The prose
is the part that survives. The code dies.
