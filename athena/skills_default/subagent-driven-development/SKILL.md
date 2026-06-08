---
description: Delegate substantial work to subagents via the Agent tool — when and how
name: subagent-driven-development
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Subagent-Driven Development

Disciplined use of the Agent tool to delegate substantial work to
subagents. The premise: an agent that does everything itself burns
context fast and loses track. Delegating well-scoped work to
subagents preserves the orchestrator's context for orchestration.

## When to use this skill

Use when:

- The task has independent subtasks that can run in parallel
- A subtask would consume a lot of context (broad searches,
  multi-file reads) that the orchestrator doesn't need to retain
- A subtask needs a specialized agent profile (research, code
  review, planning) different from the orchestrator's
- The task is open-ended ("research X") and you want the
  exploration bounded to a subagent's context

Skip for:

- One-file edits that the orchestrator can do faster directly
- Tasks where the orchestrator needs the full intermediate detail
- Tasks where the answer needs the orchestrator's full context to
  evaluate

## The delegation contract

Before spawning a subagent, write the contract in your head (or
on paper for big tasks):

### 1. Clear goal

One sentence the subagent can act on:

> "Find every place ``user_id`` is used as a string vs an int and
> report inconsistencies."

NOT "look around the codebase and tell me what you find."
Concrete in/out, finite scope.

### 2. Required output shape

What does the orchestrator need back?

- A list of findings with file:line citations?
- A summary paragraph?
- A code patch?

Specify the format in the prompt:

> "Return a markdown table with columns: file:line, current type,
> recommended fix. Maximum 30 rows."

The orchestrator can act on structured output cheaply. Free-form
narrative requires re-parsing.

### 3. Resources budget

Tell the subagent how much exploration is welcome:

> "Spend up to 10 tool calls. If you can't find the answer in
> that budget, report what you found and what's still
> uncertain."

Without a budget, subagents will keep exploring until the
runtime cuts them off.

### 4. Boundary

What's IN scope, what's OUT of scope:

> "Look only in ``athena/``. Skip ``tests/`` and ``vendor/``.
> If you find issues in skipped directories, mention them in
> 'out of scope notes' but don't analyze."

## Two-stage review

For substantial subagent work — anything that produces a code
patch, design doc, or research artifact — run two stages:

### Stage 1: producer

Subagent does the work. Returns a draft.

### Stage 2: reviewer (different subagent)

A FRESH subagent reviews the draft. The reviewer has no
attachment to the draft and applies cold-eye scrutiny.

```
Agent: "Producer: implement X per spec [details]."
Agent: "Reviewer: read the diff at branch foo. Find at least
        3 weaknesses or risks. Be specific."
You: synthesize both outputs, decide what to keep / change.
```

The cost is two agent runs; the win is catching things the
producer rationalized into "good enough." Especially valuable
for code that touches security, persistence, or external
interfaces.

## When to parallelize

Multiple subagents in one orchestrator-message when:

- Tasks are independent (one's output isn't input to another)
- Each task is non-trivial (>3 tool calls worth)
- You don't need to react to intermediate results

```
parallel:
  Agent A: research existing solutions for problem X
  Agent B: enumerate constraints we have
  Agent C: list adjacent problems we've solved
synthesize -> decision
```

If task B depends on A's output: serial, not parallel.

## When NOT to delegate

- **Trivial tasks**: a one-file edit takes you 30 seconds, a
  subagent 2 minutes plus your synthesis time. Net loss.
- **Tasks needing your judgment in the middle**: if you'd want to
  steer the subagent halfway through, you don't really want a
  subagent — you want to do it yourself.
- **Tasks the subagent will fail at**: open-ended research with
  no clear success criteria often returns useless output. Tighten
  the question first.

## Patterns

### Research subagent

```
"Find every codebase pattern for [X] in athena/, return
file:line citations with the pattern shape grouped by
similarity. Limit 20 examples."
```

Useful for understanding before you change something. Cheaper
than the orchestrator reading every file itself.

### Code-write subagent

```
"Implement [function spec]. Add unit tests covering [edge
cases]. Return the diff. Do NOT modify any file outside
[scope]."
```

Useful when the orchestrator has the plan but the implementation
detail would consume too much context.

### Review subagent

```
"Read the diff at [branch/path]. Identify weaknesses: security,
performance, correctness, missing tests. Return as a numbered
list, severity-tagged."
```

The two-stage pattern's reviewer half. Run after a substantial
change.

### Plan subagent

```
"Produce an implementation plan for [feature]. Cover files
touched, steps, test plan, risks. Per [[writing-plans]]
format."
```

Useful when you want a plan written in a specific format from
scratch.

## Anti-patterns

- **"Just do it"** prompts: vague, unbounded subagent work
  returns vague, unbounded output. Be specific.
- **No output shape**: subagent returns a wall of prose; you
  spend more time parsing than you saved delegating.
- **Recursive delegation**: subagent delegates to a sub-subagent
  that delegates further. Loses traceability fast. Limit to
  orchestrator → one level of subagents.
- **Skipping synthesis**: subagent returns; orchestrator pastes
  output to user without integrating. The orchestrator's value
  is synthesis; don't skip it.
- **Treating subagents like background workers**: subagents are
  short-lived agents, not durable workers. Use the task queue /
  background-process system for durable work.

## A note on cost

Subagent invocations cost compute. Treat them like external API
calls — don't issue 20 in a row "just to be thorough." Use them
when the parallel speedup or context savings is real.
