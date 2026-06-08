---
description: Write decisions down so future-you and the team can revisit the reasoning
name: decision-record
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Decision Record

Disciplined practice of writing decisions down. The premise: most
"why is the code like this?" archaeology happens because the original
decision was made verbally or in a thread that's now lost. A short
written record at decision time saves hours of reconstruction later.

## When to use this skill

Use when making a decision that will affect the codebase or product
for more than a week and that someone might reasonably question
later:

- Choice of dependency / library / framework
- Choice of pattern that's not obvious (e.g., "we cache in process,
  not Redis, because...")
- Trade-off explicitly made (perf vs simplicity, flexibility vs
  guardrails)
- Reversal of a previous decision
- Policy / process change

Skip for:
- Obvious choices ("we used JSON because it's the codebase standard")
- Local refactors with no design implication
- Personal preferences with no team impact

## The minimal template

Every ADR is one markdown file in ``docs/decisions/`` (or wherever
your project keeps them), four sections:

```markdown
# ADR-NNNN: <Short title in imperative or descriptive form>

Status: proposed | accepted | superseded by ADR-XXXX
Date: 2026-05-26

## Context

What's the situation that demands a decision? Two or three sentences.
What constraint or question are we answering?

## Decision

What did we choose? One paragraph. Be explicit — name the chosen
option AND the alternatives that were on the table.

## Consequences

What follows from this decision? Both positive and negative.

- We gain: ...
- We accept: ...
- We close off: ...
- We'll need to revisit if: ...
```

That's it. Two to three pages MAX. Brevity is a feature — if it
sprawls, nobody re-reads it.

## What goes in "Context"

The constraints that forced the choice. Real examples:

- "Our prod database is single-writer; we can't add a read replica
  this quarter."
- "The compliance team requires audit logs for any write touching
  PII."
- "The bundled web framework is unmaintained and the maintainer has
  archived the repo."

Future-you needs to know what world the decision was made IN, because
the world will be different next quarter.

## What goes in "Decision"

The choice. State it concretely:

> "We will use SQLite for the local task store rather than DuckDB or
> a JSON file. SQLite is already a transitive dep, has indexable
> primary keys we need, and survives concurrent reads from the
> board TUI's refresh thread."

Name the alternatives you considered and rejected. The alternatives
list is often the most valuable part — it tells future-you what
options EXIST and why each was ruled out.

## What goes in "Consequences"

Concrete, not aspirational:

- "We accept that schema migrations now require a tool (currently
  ``alembic``). New columns won't be a one-line code change."
- "We close off the option of having external scripts write to the
  task store concurrently — they must go through our API."
- "We'll need to revisit if task store size crosses ~100k rows
  (SQLite handles it but query performance degrades)."

The "revisit if" line is gold. It's the tripwire that tells future-
you when the decision needs to be re-examined.

## The supersede pattern

Decisions don't get edited — they get superseded. When you reverse a
decision:

1. The OLD ADR stays in the repo. Its status flips to:
   ``Superseded by ADR-NNNN``.
2. The NEW ADR explicitly references the old: "This decision
   supersedes ADR-0042 because [reason]."

Why preserve old ADRs? Because the reasoning at the time was valid
under the constraints at the time. Future-you might face the same
constraints again and benefit from seeing the original logic.

## Anti-patterns

- **ADR for everything**: not every choice needs a record. If it's
  obvious, skip.
- **The 12-page ADR**: nobody reads it. Two to three pages, max.
- **Editing an accepted ADR**: amend in a NEW ADR with the supersede
  pattern. Don't rewrite history.
- **Vague decisions**: "We'll use the appropriate caching strategy."
  Be specific — name the strategy.
- **No alternatives section**: makes the decision look uncontested,
  which it usually wasn't. Show the work.

## How to start in an existing codebase

Don't try to retroactively document every decision. Start NOW:

1. Add ``docs/decisions/0000-record-decisions.md`` — an ADR that
   declares you're going to write ADRs from this point forward.
2. Number sequentially from there.
3. When archaeology forces you to dig up an old decision, write a
   late-arriving ADR for it (mark the date as "retroactively
   documented YYYY-MM-DD").

The point isn't completeness. The point is that NEW decisions are
written down so future-you isn't dependent on memory or chat history.
