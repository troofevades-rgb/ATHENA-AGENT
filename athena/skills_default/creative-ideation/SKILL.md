---
description: Generate project / feature / problem ideas using creative constraints
name: creative-ideation
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Creative Ideation

Disciplined idea generation using constraints, not brainstorming.
The premise: unconstrained "let's brainstorm" produces wide,
shallow lists. Constrained generation produces deep, surprising,
USABLE ideas because the constraints force you out of obvious
paths.

## When to use this skill

Use when the user asks for ideas: project ideas, feature ideas,
solution approaches, content angles, design directions. Skip for
problems where the answer space is small and well-known (use
[[literature-survey]] for those).

## The constraint frame

Pick THREE constraints from different categories. Generate against
the intersection.

### Constraint categories

**Audience constraints** — who is this FOR?
- A specific persona (a 60-year-old new programmer)
- A specific situation (someone debugging at 3 AM)
- A specific need (offline-only, accessibility-first, kid-safe)
- A specific size (solo, 5-person team, 1000-person org)

**Technical constraints** — what TOOLS / SHAPES?
- One specific tech (must use only POSIX shell)
- One specific shape (must be a single static HTML file)
- One specific surface (must work in a terminal, no GUI)
- One specific scale (must run on a Raspberry Pi)

**Aesthetic constraints** — what FEELING?
- One specific era (must feel like 1994 web)
- One specific mood (calm, urgent, playful, austere)
- One specific reference (must remind you of X)

**Resource constraints** — what BUDGET?
- One specific time budget (must be buildable in a weekend)
- One specific cost budget (must be free to operate at <100 users)
- One specific code-size budget (must fit in 1000 lines)

### Example combinations

- *Audience: developer at 3 AM* × *Technical: only POSIX shell* ×
  *Aesthetic: calm* → an oncall command palette that reads like a
  Zen koan
- *Audience: kid learning to code* × *Technical: single static
  HTML file* × *Resource: weekend project* → a typing-game where
  the keys play sounds and color-blocks build a generative
  landscape
- *Audience: 5-person research team* × *Aesthetic: 1994 web* ×
  *Resource: free at <100 users* → a paper-discussion tool that
  feels like a BBS

The constraints generate the idea space. The ideas surface from
the friction between constraints, not from "what's a good idea?"

## The 10-idea floor

For any single combination, generate AT LEAST 10 ideas before
evaluating any of them. The first 3 are obvious; ideas 4-7 require
real thinking; ideas 8-10 force the creative leap.

```
audience: developer at 3 AM
technical: only POSIX shell
aesthetic: calm

ideas:
1. zen-grep: grep that returns one match per page with a koan
2. slow-cat: cat that types out at 60wpm (forces a reread pace)
3. silence: a CLI tool that does nothing for N seconds (forced break)
4. one-thing: prompt that asks "what's the ONE thing?" before scripting
5. exhale: a breath-pacing script for the terminal
6. tea: a timer that asks if your tea is steeping
7. dawn: a status line that gets brighter as you near sunrise
8. echo-back: every command repeats once, slower, before running
9. last-light: 10 PM cutoff that asks if you really need this
10. shore: a tide-pattern background process that paces your typing

evaluation: 1, 5, and 8 are most surprising and seem buildable in a
weekend
```

The 10-idea floor is the most important part. Without it, you
ship idea #1 (which is usually fine, sometimes great, rarely
surprising).

## Evaluation criteria

After generating, score each idea on:

- **Buildable?** Can YOU build it with the resources at hand?
- **Surprising?** Does it make you smile or raise an eyebrow?
- **Reusable?** Does it generalize to other problems, or is it
  one-shot?
- **Tested?** Does it scratch a real itch you've personally felt,
  or only one you imagine others feel?

The best ideas score high on multiple axes. The most fun-to-build
ideas score high on Surprising. The most likely-to-ship score high
on Buildable + Tested.

## When to stop ideating

Stop when:

- You have 1-2 ideas you're genuinely excited to start on
- The 10-idea list has clear leaders that match the audience
  + resource constraints
- You catch yourself just listing variations of the same idea
  (signal that the constraint isn't tight enough)

Don't stop just because you've hit a quota. Quality > quantity for
the SELECTION; but quantity > quality for the GENERATION step.

## Anti-patterns

- **Brainstorming without constraints**: produces dozens of generic
  ideas, none of which feel like they're for YOU.
- **Idea filtering during generation**: kills the surprising ones.
  Separate generation from evaluation.
- **Stopping at idea 3**: see the 10-idea floor.
- **Identical constraints every time**: leads to similar ideas.
  Rotate the constraint categories session to session.
- **Idea hoarding**: collecting ideas in a backlog forever. The
  goal of ideation is to PICK and BUILD. Pick within the session.

## A note on prompting LLMs for ideation

If using an LLM as a brainstorming partner: give it the
constraints upfront. LLMs are extraordinary constraint-followers
and mediocre unconstrained-creators. The conversation:

> "Generate 10 project ideas. Constraints: audience is X.
> Technical: only Y. Aesthetic: Z. Don't filter — give me all 10
> before picking favorites."

Without the constraints, you get a list of "things AI thinks
might be good." With them, you get ideas that surprise.
