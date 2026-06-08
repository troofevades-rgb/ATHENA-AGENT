---
description: Author SKILL.md files that athena loads well — frontmatter, structure, voice
name: athena-skill-authoring
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Athena Skill Authoring

Meta-skill: how to write skills for athena that the agent will
actually load and use well. The premise: a skill is a thin slice
of procedural memory — write it tight enough to load on demand,
specific enough to act on.

## When to use this skill

Use when:
- Authoring a new skill from scratch
- Reviewing an existing skill for clarity
- Splitting a too-broad skill into focused pieces

Skip if you're just consuming skills, not writing them.

## Skill anatomy

A skill is a single ``SKILL.md`` file in a named directory:

```
~/.athena/skills/<kebab-case-name>/SKILL.md
```

The file has YAML frontmatter and a markdown body.

### Frontmatter

```yaml
---
description: One-line summary, ~60 chars, used in the catalog list
name: kebab-case-name
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
```

Rules:

- ``description`` is what the agent reads when deciding whether
  to LOAD the skill. Make it specific — "OSINT research on
  social platforms" beats "research skill"
- ``name`` matches the directory name. Kebab-case. Verb-noun
  ("review-pr"), domain-task ("data-cleaning"), or
  domain-discipline ("focus-session")
- ``state`` is ``active`` (default), ``archived`` (won't load),
  or ``draft`` (visible but not auto-loaded)
- Don't set ``use_count`` manually — athena tracks it
- Don't set ``last_activity_at`` manually beyond authoring time
  — athena updates on use
- ``pinned: true`` only for skills you want ALWAYS loaded —
  defaults to false

### Body structure

A good skill body has these sections, in this order:

```markdown
# <Title — Title Case>

<One-paragraph intro: what this skill is, the premise / belief
that makes it useful. Often phrased as "the premise: X is true,
so do Y.">

## When to use this skill

<Trigger conditions. Specific. When NOT to use it too.>

## <Workflow steps OR core principles>

<The actual content — numbered steps, named principles, or
checklist format. Match the format to the content.>

## Anti-patterns

<What this skill warns against. Often the most-read section
because it tells the agent what NOT to do.>
```

That's the minimum. Optional additions:

- **Examples** — concrete short examples after each principle
- **Tooling** — specific tools, commands, libraries that
  support the skill
- **Cross-references** — ``[[other-skill]]`` links to related
  skills

## Writing voice

### Tight, opinionated, falsifiable

Skills are short. ~80-150 lines is the sweet spot. <60 lines is
usually too thin; >200 is usually too much.

The voice is opinionated, not academic. Don't hedge. Take a
position:

- Good: "Always set a time-box for spikes."
- Bad: "It may be helpful in some cases to consider a time-box
  when conducting spikes."

The opinionation comes with a cost: be ready to revise when
proven wrong. Skills are living docs.

### Concrete, not abstract

Every principle gets a concrete example:

- Good: "Mock at the boundary. e.g. mock ``fetch_user(id)``, not
  ``httpx.get()``."
- Bad: "Mock at appropriate boundaries."

When the body is mostly abstract advice, the agent will struggle
to act on it. Add examples.

### Imperative, not descriptive

- Good: "Run the seven-question pass. Write three sentences."
- Bad: "There is a seven-question pass that some practitioners
  use, which involves writing three sentences."

You're telling the agent what to DO. Tell it directly.

## Scoping a skill

The hardest authoring decision is scope. Some guidelines:

### A skill answers ONE question well

If you can't write the skill's central question in one sentence,
it's too broad:

- Good: "How should I review a PR before approving it?"
  → ``code-review-workflow``
- Bad: "How should I work with code?"
  → too broad, split into multiple skills

### Adjacent skills cross-link

When two skills naturally cooperate, link them with ``[[name]]``:

```markdown
After EDA ([[data-exploration]]), clean the data
([[data-cleaning]]) before modeling.
```

This lets the agent load only what's needed but follow the chain
when context warrants.

### Don't pre-emptively author for completeness

The ANTI-pattern is "let me create skills for every domain in
case the user asks." Skills authored without a real use case in
mind are usually too abstract.

Better: author when you encounter a recurring workflow worth
codifying. Athena itself notes "I keep doing X" — that's the
signal to create a skill for X.

## Frontmatter gotchas

### Description quality matters MORE than body quality

The description is what athena reads at every skill-discovery
moment. The body only gets read when the description matches a
trigger.

If your skill is rarely loaded despite being relevant — the
description is the bug, not the body.

### Don't lie in created_at

If you backdate, retrieval / metrics get confused. Use today's
date in ISO 8601 UTC: ``'2026-05-27T00:00:00Z'``.

### Don't pin without reason

``pinned: true`` makes the skill always-on. Reserve for skills
you want loaded EVERY session (your style guide,
project-specific conventions). Default off — pinning everything
is the same as pinning nothing.

## Iteration

After a skill has been used 5+ times, review it:

- Did the agent skip parts? Tighten those.
- Did the agent miss the skill when it should have loaded? Fix
  the description.
- Did the agent load it for the wrong reason? Make the "when to
  use" tighter.
- Are there patterns the skill should mention but doesn't?

Skills get BETTER with use. The first draft is rarely the final
form.

## Anti-patterns

- **The encyclopedia entry**: 500-line skill covering every
  edge case. Split into focused skills.
- **The vague principle**: "Code should be clean." Says nothing
  the agent can act on.
- **The TODO skill**: empty body with "TODO: write workflow."
  Either write it or delete it; the half-skill is worse than
  none.
- **The skill that's a doc**: long prose explanation with no
  action. If it's reference material, put it in a doc — skills
  are for procedural memory.
- **Duplicating an existing skill**: check ``/skills`` first.
  If it exists, edit; don't shadow.
- **Skill named after a tool, not a task**: ``skill: pytest`` is
  worse than ``skill: test-writing-discipline``. Tools come and
  go; tasks endure.

## A note on dialect

Athena's skill style (this skill is itself an example):

- Headings in Title Case ("When To Use This Skill")
- Code blocks tagged with language (``python``, ``bash``, ``json``)
- Bullets prefer ``-`` over ``*``
- Cross-refs use ``[[name]]``
- Tone: opinionated, calm, specific

That dialect makes athena's skill collection feel coherent. New
skills should match it.
