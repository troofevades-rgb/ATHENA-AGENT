---
description: Systematic literature / prior-art survey before tackling a hard problem
name: literature-survey
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Literature Survey

Disciplined prior-art search before tackling a non-trivial technical
or research problem. The premise: most "novel" problems are 80%
solved upstream by someone you haven't read yet, and the marginal
cost of a 30-minute survey is much smaller than rediscovering their
mistakes.

## When to use this skill

Use when the user asks you to solve a problem that's a CLASS of
problem rather than a one-off bug: a new algorithm, a system design,
a research question, a domain you don't already know cold. Skip for
implementation tasks where the design is already decided.

## The survey pass

### 1. Frame the question precisely

Write the question in one sentence. Two examples:

- Bad: "I want to do user modeling."
- Good: "I want to extract durable facts about a user from a long
  conversation transcript and recall them in future sessions without
  growing the prompt indefinitely."

The precision shapes every subsequent search.

### 2. Three search lenses

Run searches under three different framings — each catches different
prior art:

- **Engineering / practitioner**: "<problem> github", "<problem>
  production", "<problem> blog post" → real systems shipping today
- **Academic / theory**: "<problem> arxiv", "<problem> survey",
  "<problem> paper" → formal treatment, theoretical limits
- **Adjacent fields**: who else faces a structurally similar problem
  but calls it something different? (Cache eviction ≈ working memory;
  recommender systems ≈ context retrieval; epidemiology ≈ tracing)

### 3. The three-references rule

Before settling on an approach, identify THREE existing references
that span the design space:

1. A widely-deployed simple solution (the baseline)
2. A sophisticated state-of-the-art solution (the ceiling)
3. A weird/unusual solution from an adjacent field (the wild card)

Read enough of each to write a paragraph summarizing its core trick
and its main tradeoff. If you can't summarize at that level, you
haven't read enough.

### 4. Position your approach

Now articulate where your planned approach sits:

> "I'm building closer to (1) the baseline because [reason], but
> borrowing [specific idea] from (2). I'm explicitly NOT going (3)'s
> route because [reason]."

That paragraph alone gives the reviewer / future-you enormous
context. It also catches the "I just reinvented X poorly" failure
mode before you've written any code.

### 5. Bookmark the references

Keep a short references file in the project (``REFERENCES.md`` or
similar). Future-you and collaborators will need them. One line per
reference: title, link, one-sentence summary of what it gave you.

## When to skip this skill

If you've worked in the domain for 5+ years and the question is in
your wheelhouse: skip the formal survey, just write the design.
Surveys are most valuable when you're new to a domain or when the
stakes (system design, public commitment) are high.
